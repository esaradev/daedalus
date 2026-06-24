"""The autonomous service desk: one order, earn -> spend -> fulfill -> book.

Earning is autonomous. Spending stops at the human approval gate by design.
Every money movement is booked to the ledger as it happens.
"""

from . import ledger, nemotron, pricing, stripe_io


def intake(spec, customer="customer"):
    """Price the work and send a payment link. Fully autonomous."""
    cost_obj, lane = nemotron.estimate_cost(spec)
    cost = cost_obj["cost_cents"] if isinstance(cost_obj, dict) else cost_obj
    vendors = cost_obj.get("vendors", []) if isinstance(cost_obj, dict) else []
    price = pricing.quote_price(cost)

    order_id = ledger.new_id("o")
    link = stripe_io.create_payment_link(order_id, price, spec[:120])
    ledger.write_order(order_id, {
        "state": "quoted",
        "customer": customer,
        "price_cents": price,
        "est_cost_cents": cost,
        "payment_link_id": link.get("id", ""),
        "route": lane,
    }, spec=spec)
    return {"order": order_id, "price_cents": price, "est_cost_cents": cost,
            "checkout_url": link["url"], "vendors": vendors, "route": lane}


def collect(order_id):
    """If the customer has paid, book revenue. Autonomous."""
    o = ledger.read_order(order_id)
    if not o:
        return {"error": f"unknown order {order_id}"}
    if o.get("state") in ("funded", "fulfilling", "delivered"):
        return {"order": order_id, "state": o["state"], "already": True}
    if not stripe_io.check_paid(order_id, o.get("payment_link_id")):
        return {"order": order_id, "state": "quoted", "paid": False}
    ledger.post("revenue", o["price_cents"], order=order_id, ref="stripe_checkout",
                memo=f"paid by {o.get('customer','customer')}")
    ledger.set_state(order_id, "funded")
    return {"order": order_id, "state": "funded", "revenue_cents": o["price_cents"]}


def fulfill(order_id, approve_via=stripe_io.request_spend):
    """Buy inputs (gated by the human tap), do the work, book costs, deliver."""
    o = ledger.read_order(order_id)
    if not o:
        return {"error": f"unknown order {order_id}"}
    if o.get("state") not in ("funded", "fulfilling"):
        return {"error": f"order {order_id} is '{o.get('state')}', not funded"}

    spec = o.get("spec", "")
    cost_obj, _ = nemotron.estimate_cost(spec)
    vendors = cost_obj.get("vendors") if isinstance(cost_obj, dict) else None
    if not vendors:
        c = cost_obj["cost_cents"] if isinstance(cost_obj, dict) else cost_obj
        vendors = [{"name": "apis", "cents": c}]
    total = sum(v["cents"] for v in vendors)

    ledger.set_state(order_id, "fulfilling")
    approval = approve_via(order_id, total, vendors)
    if not approval.get("approved"):
        ledger.set_state(order_id, "funded")
        return {"order": order_id, "approved": False,
                "reason": approval.get("reason", "denied"),
                "note": "spend needs a human tap in the Link app; agent cannot self-approve"}

    for v in vendors:
        ledger.post(f"cogs:{v['name']}", -v["cents"], order=order_id,
                    ref=approval.get("card", ""), memo=v["name"])

    deliverable, lane = nemotron.fulfill(spec)
    ledger.set_state(order_id, "delivered", deliverable_route=lane)

    p = ledger.pnl(order_id)
    return {"order": order_id, "approved": True, "spent_cents": total,
            "profit_cents": p["profit_cents"], "margin_pct": p["margin_pct"],
            "deliverable": deliverable, "route": lane}
