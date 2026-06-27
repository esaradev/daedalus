"""Pricing and bounded self-evolution.

The agent prices a job as cost-to-fulfill times a markup. After a window of
orders it reads two real signals off its own book and moves the markup inside
hard bounds:

  margin     — are the orders we win profitable?     (from the ledger)
  conversion — are customers actually paying at this  (funded vs lost orders)
               price, or walking away?

Raise only while customers keep buying. When conversion falls, you have found
the demand ceiling: cut back. That is price discovery, not a ratchet to a cap.
Every change is snapshotted so it can be rolled back. This is the sega `evolve`
loop pointed at the ledger.
"""

import json
from datetime import datetime, timezone

from . import ledger

CONFIG = ledger.STORE / "pricing.json"
SNAPSHOTS = ledger.STORE / "pricing_snapshots.jsonl"

DEFAULTS = {
    "markup": 4.0,            # price = cost_to_fulfill * markup
    "floor_markup": 1.3,      # never price below this (fees would eat it)
    "ceiling_markup": 20.0,   # hard safety stop, not the normal limit
    "max_step_pct": 25.0,     # most the markup can move in one evolve cycle
    "min_price_cents": 500,   # never quote below $5
    "window": 10,             # how many recent decided orders to read
    "raise_above": 0.8,       # conversion at/above this -> room to raise
    "cut_below": 0.5,         # conversion below this -> priced too high
    "fat_margin": 70.0,       # margin at/above this is "fat"
    "thin_margin": 30.0,      # margin below this is "thin"
}


def config():
    if CONFIG.exists():
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    return dict(DEFAULTS)


def _save(cfg):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))


def quote_price(cost_to_fulfill_cents):
    cfg = config()
    price = int(round(cost_to_fulfill_cents * cfg["markup"]))
    return max(price, cfg["min_price_cents"])


def conversion(window):
    """Share of recently *decided* orders that the customer paid for.

    Decided = funded/fulfilling/delivered (paid) or lost (declined). Orders
    still 'quoted' have not decided yet and do not count. Returns (rate, n).
    """
    decided = [o for o in ledger.all_orders()
               if o.get("state") in ("funded", "fulfilling", "delivered", "lost")]
    decided = decided[-window:]
    if not decided:
        return None, 0
    paid = sum(1 for o in decided if o.get("state") != "lost")
    return paid / len(decided), len(decided)


def _snapshot(cfg, reason, kind="evolve"):
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
           "config": cfg, "reason": reason}
    with SNAPSHOTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _clamp(old, target, cfg):
    step_cap = old * (1 + cfg["max_step_pct"] / 100)
    step_floor = old * (1 - cfg["max_step_pct"] / 100)
    target = max(step_floor, min(step_cap, target))
    target = max(cfg["floor_markup"], min(cfg["ceiling_markup"], target))
    return round(target, 2)


def evolve():
    """Read margin and conversion, move the markup within bounds, snapshot."""
    cfg = config()
    p = ledger.pnl()
    old = cfg["markup"]
    margin = p["margin_pct"]
    conv, n = conversion(cfg["window"])

    if p["orders"] < 1 and n == 0:
        return {"changed": False, "reason": "no order history yet", "markup": old, "conversion": conv}

    # conversion is the dominant signal: if customers are walking, cut regardless of margin.
    if conv is not None and conv < cfg["cut_below"]:
        target = old * 0.85
        why = f"conversion {conv:.0%} over {n} orders is low; price is above the market, cut"
    elif margin >= cfg["fat_margin"] and (conv is None or conv >= cfg["raise_above"]):
        target = old * 1.15
        why = (f"margin {margin}% fat and conversion {('n/a' if conv is None else format(conv, '.0%'))}"
               f" holding; customers still buy, raise")
    elif margin < cfg["thin_margin"]:
        target = old * 0.9
        why = f"margin {margin}% thin; cut markup"
    else:
        return {"changed": False,
                "reason": f"margin {margin}%, conversion {('n/a' if conv is None else format(conv, '.0%'))}: hold",
                "markup": old, "conversion": conv}

    target = _clamp(old, target, cfg)
    if target == old:
        return {"changed": False, "reason": "already at a bound", "markup": old, "conversion": conv}

    _snapshot(cfg, f"before evolve: {why}")
    cfg["markup"] = target
    _save(cfg)
    return {"changed": True, "old_markup": old, "markup": target, "reason": why,
            "margin_pct": margin, "conversion": conv, "orders": p["orders"]}


def rollback():
    """Restore the most recent snapshot."""
    if not SNAPSHOTS.exists():
        return {"error": "no snapshots to roll back to"}
    last = None
    for line in SNAPSHOTS.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("kind", "evolve") == "evolve":  # ignore session-end markers
            last = rec
    if not last:
        return {"error": "no pricing changes to roll back"}
    _save(last["config"])
    return {"restored": True, "markup": last["config"]["markup"], "from": last["ts"]}
