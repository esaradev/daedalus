"""Pricing. Quote a job as cost-to-fulfill times a markup, cap the fulfillment
spend so a floor margin survives, and reprice over time from the book.

Reprice reads two real signals: margin (are won jobs profitable?) and conversion
(are customers paying at this price, or walking?). It raises only while they keep
buying and cuts when they walk, inside hard bounds. State persists to disk so the
markup carries across runs.
"""

import json
from pathlib import Path

from . import config

DEFAULTS = {
    "markup": 4.0,
    "floor_markup": 1.3,
    "ceiling_markup": 20.0,
    "max_step_pct": 25.0,
    "min_price_cents": 500,
    "margin_floor_pct": 20.0,   # keep at least this margin: caps fulfillment spend
    "raise_above": 0.8,
    "cut_below": 0.5,
    "fat_margin": 70.0,
    "thin_margin": 30.0,
}


class Pricing:
    def __init__(self, state_path=None, **overrides):
        self.state_path = Path(state_path) if state_path else (config.DATA_DIR / "pricing.json")
        self.cfg = dict(DEFAULTS)
        if self.state_path.exists():
            self.cfg.update(json.loads(self.state_path.read_text()))
        self.cfg.update(overrides)
        self.repriced = 0

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.cfg, indent=2))

    @property
    def markup(self):
        return self.cfg["markup"]

    def quote(self, cost_cents):
        price = int(round(cost_cents * self.cfg["markup"]))
        return max(price, self.cfg["min_price_cents"])

    def fulfillment_budget(self, price_cents):
        """Most we may spend on inputs for this job while keeping the floor margin."""
        return int(price_cents * (1 - self.cfg["margin_floor_pct"] / 100))

    def _clamp(self, old, target):
        c = self.cfg
        lo, hi = old * (1 - c["max_step_pct"] / 100), old * (1 + c["max_step_pct"] / 100)
        target = max(lo, min(hi, target))
        return round(max(c["floor_markup"], min(c["ceiling_markup"], target)), 2)

    def evolve(self, pnl, conversion=None):
        c = self.cfg
        old = c["markup"]
        margin = pnl["margin_pct"]
        if pnl["revenue_cents"] <= 0 and conversion is None:
            return {"changed": False, "reason": "no history yet", "markup": old, "conversion": conversion}

        if conversion is not None and conversion < c["cut_below"]:
            target = old * 0.85
            why = f"conversion {conversion:.0%} low; price above market, cut"
        elif margin >= c["fat_margin"] and (conversion is None or conversion >= c["raise_above"]):
            target = old * 1.15
            why = f"margin {margin}% fat, demand holds; raise"
        elif margin < c["thin_margin"]:
            target = old * 0.9
            why = f"margin {margin}% thin; cut"
        else:
            return {"changed": False, "reason": f"margin {margin}%, conversion {conversion}: hold",
                    "markup": old, "conversion": conversion}

        target = self._clamp(old, target)
        if target == old:
            return {"changed": False, "reason": "already at a bound", "markup": old, "conversion": conversion}
        c["markup"] = target
        self.repriced += 1
        self._save()
        return {"changed": True, "old_markup": old, "markup": target, "reason": why, "conversion": conversion}
