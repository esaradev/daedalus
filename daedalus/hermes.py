"""Hermes tool contract for Daedalus.

Hermes is the agent runtime. These handlers expose Daedalus as its treasury:
quote, collect, fulfill, read the books, and evolve pricing.
"""

import json

from .cli import build_stack
from .spend_control import mint_approval


def _json(payload):
    return json.dumps(payload, default=str)


def _url(args):
    return (args.get("target") or args.get("url") or args.get("spec") or "").strip()


def _stack():
    return build_stack()


def treasury_intake(args, **kwargs):
    target = _url(args)
    if not target:
        return _json({"error": "need a target URL"})
    customer = (args.get("customer") or "customer").strip() or "customer"
    try:
        return _json(_stack()["orch"].quote_order(target, customer=customer,
                                                  source_tool="treasury_intake"))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_collect(args, **kwargs):
    order = (args.get("order") or "").strip()
    if not order:
        return _json({"error": "need an order id"})
    try:
        return _json(_stack()["orch"].collect_order(
            order,
            test_collect=bool(args.get("test_collect", False)),
            source_tool="treasury_collect",
        ))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_fulfill(args, **kwargs):
    order = (args.get("order") or "").strip()
    if not order:
        return _json({"error": "need an order id"})
    try:
        # No approval argument: the spend proceeds only if a human approved this
        # order out of band via `daedalus approve`. The agent cannot self-approve.
        return _json(_stack()["orch"].fulfill_order(order, source_tool="treasury_fulfill"))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_run_paid_audit(args, **kwargs):
    target = _url(args)
    if not target:
        return _json({"error": "need a target URL"})
    customer = (args.get("customer") or "customer").strip() or "customer"
    try:
        # Quotes and collects, then stops at the spend for out-of-band human
        # approval (`daedalus approve <order>`). The agent cannot self-approve.
        return _json(_stack()["orch"].run_paid_audit(
            target,
            customer=customer,
            test_collect=bool(args.get("test_collect", True)),
            evolve=bool(args.get("evolve", True)),
            source_tool="treasury_run_paid_audit",
        ))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_abandon(args, **kwargs):
    order = (args.get("order") or "").strip()
    if not order:
        return _json({"error": "need an order id"})
    try:
        return _json(_stack()["orch"].abandon_order(
            order,
            reason=(args.get("reason") or "customer declined").strip(),
            source_tool="treasury_abandon",
        ))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_pnl(args, **kwargs):
    try:
        s = _stack()
        return _json({"pnl": s["ledger"].pnl(), "five_numbers": s["orch"].five_numbers()})
    except Exception as e:
        return _json({"error": str(e)})


def treasury_open_orders(args, **kwargs):
    try:
        s = _stack()
        return _json({"open": s["orders"].open_orders(), "orders": s["orders"].all(50)})
    except Exception as e:
        return _json({"error": str(e)})


def treasury_evolve(args, **kwargs):
    try:
        s = _stack()
        result = s["orch"].reprice()
        s["memory"].record(kind="decision", summary="Daedalus pricing evolved",
                           body=result, source_tool="treasury_evolve")
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def treasury_rollback(args, **kwargs):
    try:
        s = _stack()
        result = s["pricing"].rollback()
        s["memory"].record(kind="decision", summary="Daedalus pricing rollback",
                           body=result, source_tool="treasury_rollback")
        return _json(result)
    except Exception as e:
        return _json({"error": str(e)})


def treasury_test_guardrails(args, **kwargs):
    try:
        return _json(_stack()["orch"].demo_guardrails())
    except Exception as e:
        return _json({"error": str(e)})


def treasury_recall(args, **kwargs):
    query = (args.get("query") or "paid audit pricing spend decision").strip()
    try:
        return _json(_stack()["memory"].recall(query, k=int(args.get("k", 5))))
    except Exception as e:
        return _json({"error": str(e)})


def treasury_cfo(args, **kwargs):
    try:
        return _json(_stack()["orch"].cfo_brief())
    except Exception as e:
        return _json({"error": str(e)})


SCHEMAS = {
    "treasury_intake": {
        "name": "treasury_intake",
        "description": "Quote a paid website security audit, create a Stripe Payment Link, and persist the order.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Website URL to audit"},
            "customer": {"type": "string", "description": "Customer identifier"},
        }, "required": ["target"]},
    },
    "treasury_collect": {
        "name": "treasury_collect",
        "description": "Collect/book payment for an order. Use test_collect only for Stripe test-mode judging.",
        "parameters": {"type": "object", "properties": {
            "order": {"type": "string"},
            "test_collect": {"type": "boolean"},
        }, "required": ["order"]},
    },
    "treasury_fulfill": {
        "name": "treasury_fulfill",
        "description": "Spend on inputs (gated), run the live audit, ask Nemotron for the summary, and book costs. The spend requires out-of-band human approval (a human runs `daedalus approve <order>`); if not yet approved this returns awaiting_approval with the exact command. You cannot approve it yourself.",
        "parameters": {"type": "object", "properties": {
            "order": {"type": "string"},
        }, "required": ["order"]},
    },
    "treasury_run_paid_audit": {
        "name": "treasury_run_paid_audit",
        "description": "Full paid audit flow: quote, collect, then stop for out-of-band human approval of the spend. Returns awaiting_approval with the exact `daedalus approve <order>` command. After a human approves, call treasury_fulfill. You cannot approve the spend yourself.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string"},
            "customer": {"type": "string"},
            "test_collect": {"type": "boolean"},
            "evolve": {"type": "boolean"},
        }, "required": ["target"]},
    },
    "treasury_abandon": {
        "name": "treasury_abandon",
        "description": "Mark an unpaid quoted order as lost so pricing can learn from demand.",
        "parameters": {"type": "object", "properties": {
            "order": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["order"]},
    },
    "treasury_pnl": {
        "name": "treasury_pnl",
        "description": "Read the current double-entry book and five operating numbers.",
        "parameters": {"type": "object", "properties": {}},
    },
    "treasury_open_orders": {
        "name": "treasury_open_orders",
        "description": "List open and recent orders.",
        "parameters": {"type": "object", "properties": {}},
    },
    "treasury_evolve": {
        "name": "treasury_evolve",
        "description": "Reprice from the book and conversion signal within hard bounds.",
        "parameters": {"type": "object", "properties": {}},
    },
    "treasury_rollback": {
        "name": "treasury_rollback",
        "description": "Restore the previous markup after the last pricing change.",
        "parameters": {"type": "object", "properties": {}},
    },
    "treasury_test_guardrails": {
        "name": "treasury_test_guardrails",
        "description": "Demonstrate the spend gate: attempt three bad spends and show each protection (egress / credential cap / economics) block a different one. No money moves; for showing the governance live.",
        "parameters": {"type": "object", "properties": {}},
    },
    "treasury_recall": {
        "name": "treasury_recall",
        "description": "Recall daedalus's own business memory (past audits, pricing and spend decisions) from Icarus markdown memory, to inform a decision across sessions. Use before pricing or before repeating work for a customer.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to recall, e.g. 'pricing decisions' or a target/customer"},
            "k": {"type": "integer", "description": "How many results (default 5)"},
        }},
    },
    "treasury_cfo": {
        "name": "treasury_cfo",
        "description": "Act as CFO: reason over the books with the local Nemotron (financials stay on-box) and return a strategy memo with per-customer profitability, the vendor cost to watch, and a pricing recommendation.",
        "parameters": {"type": "object", "properties": {}},
    },
}


HANDLERS = {
    "treasury_intake": treasury_intake,
    "treasury_collect": treasury_collect,
    "treasury_fulfill": treasury_fulfill,
    "treasury_run_paid_audit": treasury_run_paid_audit,
    "treasury_abandon": treasury_abandon,
    "treasury_pnl": treasury_pnl,
    "treasury_open_orders": treasury_open_orders,
    "treasury_evolve": treasury_evolve,
    "treasury_rollback": treasury_rollback,
    "treasury_test_guardrails": treasury_test_guardrails,
    "treasury_recall": treasury_recall,
    "treasury_cfo": treasury_cfo,
}


def on_session_start(session_id="", platform="", **kwargs):
    s = _stack()
    p = s["ledger"].pnl()
    orders = s["orders"].open_orders()
    lines = [f"[daedalus treasury] revenue {p['revenue_cents']}c, cost {p['cost_cents']}c, "
             f"profit {p['profit_cents']}c, open orders {len(orders)}."]
    if orders:
        lines.append("Funded orders need treasury_fulfill and human_approved=true only after approval.")
    mem = s["memory"].recall("paid audit pricing spend decision", k=3)
    if mem.get("hits"):
        lines.append("[daedalus memory] recent business decisions you have made:")
        for h in mem["hits"]:
            lines.append(f"  - {h['type']}: {h['summary']}")
        lines.append("Call treasury_recall to look up more before pricing or repeating work.")
    return "\n".join(lines)


def on_session_end(session_id="", platform="", completed=False, **kwargs):
    s = _stack()
    s["memory"].record(kind="session", summary=f"Hermes session ended for daedalus ({session_id})",
                       body={"completed": completed, "five_numbers": s["orch"].five_numbers()},
                       source_tool="hermes")
    return None


def register(ctx):
    toolset = "treasury"
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset=toolset, schema=schema, handler=HANDLERS[name])
    ctx.register_hook("on_session_start", on_session_start)
    ctx.register_hook("on_session_end", on_session_end)

