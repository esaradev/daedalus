"""Tool handlers. Each returns a JSON string, matching the Hermes plugin contract."""

import json

from . import desk, ledger, pricing


def _json(payload) -> str:
    return json.dumps(payload, default=str)


def treasury_intake(args: dict, **kwargs) -> str:
    spec = args.get("spec", "").strip()
    if not spec:
        return _json({"error": "need a spec — what does the customer want?"})
    try:
        return _json(desk.intake(spec, args.get("customer", "customer").strip() or "customer"))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_collect(args: dict, **kwargs) -> str:
    order = args.get("order", "").strip()
    if not order:
        return _json({"error": "need an order id"})
    try:
        return _json(desk.collect(order))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_fulfill(args: dict, **kwargs) -> str:
    order = args.get("order", "").strip()
    if not order:
        return _json({"error": "need an order id"})
    try:
        return _json(desk.fulfill(order))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_pnl(args: dict, **kwargs) -> str:
    try:
        p = ledger.pnl(args.get("order") or None)
        p["revenue"] = ledger.dollars(p["revenue_cents"])
        p["spend"] = ledger.dollars(p["spend_cents"])
        p["profit"] = ledger.dollars(p["profit_cents"])
        return _json(p)
    except Exception as e:
        return _json({"error": str(e)})


def treasury_open_orders(args: dict, **kwargs) -> str:
    try:
        return _json({"open": ledger.open_orders()})
    except Exception as e:
        return _json({"error": str(e)})


def treasury_evolve(args: dict, **kwargs) -> str:
    try:
        return _json(pricing.evolve())
    except Exception as e:
        return _json({"error": str(e)})


def treasury_rollback(args: dict, **kwargs) -> str:
    try:
        return _json(pricing.rollback())
    except Exception as e:
        return _json({"error": str(e)})
