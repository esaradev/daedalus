"""Pricing and bounded self-evolution.

The agent prices a job as cost-to-fulfill times a markup. After a window of
orders it reads its own P&L and adjusts the markup, inside hard bounds it
cannot exceed in one step and cannot cross at all. Every change is snapshotted
so it can roll back. This is the sega `evolve` loop pointed at the ledger.
"""

import json
from datetime import datetime, timezone

from . import ledger

CONFIG = ledger.STORE / "pricing.json"
SNAPSHOTS = ledger.STORE / "pricing_snapshots.jsonl"

DEFAULTS = {
    "markup": 4.0,            # price = cost_to_fulfill * markup
    "floor_markup": 1.3,      # never price below this (would lose money on fees)
    "ceiling_markup": 12.0,   # never gouge past this
    "max_step_pct": 25.0,     # most the markup can move in one evolve cycle
    "min_price_cents": 500,   # never quote below $5
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


def _snapshot(cfg, reason):
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "config": cfg, "reason": reason}
    with SNAPSHOTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def evolve():
    """Read the P&L, propose a bounded markup change, apply it, snapshot.

    Healthy fat margin and we never undercut -> raise. Thin or negative -> cut.
    Returns the decision so the agent can explain it from its own numbers.
    """
    cfg = config()
    p = ledger.pnl()
    old = cfg["markup"]
    margin = p["margin_pct"]

    if p["orders"] < 1 or p["revenue_cents"] <= 0:
        return {"changed": False, "reason": "no settled revenue yet", "markup": old}

    if margin >= 70:
        target = old * 1.15
        why = f"margin {margin}% is fat across {p['orders']} order(s); demand holds, raise price"
    elif margin < 30:
        target = old * 0.9
        why = f"margin {margin}% is thin; cut markup to stay competitive"
    else:
        return {"changed": False, "reason": f"margin {margin}% is healthy, hold", "markup": old}

    step_cap = old * (1 + cfg["max_step_pct"] / 100)
    step_floor = old * (1 - cfg["max_step_pct"] / 100)
    target = max(step_floor, min(step_cap, target))
    target = max(cfg["floor_markup"], min(cfg["ceiling_markup"], target))
    target = round(target, 2)

    if target == old:
        return {"changed": False, "reason": "already at a bound", "markup": old}

    _snapshot(cfg, f"before evolve: {why}")
    cfg["markup"] = target
    _save(cfg)
    return {"changed": True, "old_markup": old, "markup": target, "reason": why,
            "margin_pct": margin, "orders": p["orders"]}


def rollback():
    """Restore the most recent snapshot."""
    if not SNAPSHOTS.exists():
        return {"error": "no snapshots to roll back to"}
    last = None
    for line in SNAPSHOTS.read_text().splitlines():
        if line.strip():
            last = json.loads(line)
    if not last:
        return {"error": "no snapshots to roll back to"}
    _save(last["config"])
    return {"restored": True, "markup": last["config"]["markup"], "from": last["ts"]}
