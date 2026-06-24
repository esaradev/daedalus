"""The autonomous service desk: one order, earn -> spend -> fulfill -> book.

Earning is autonomous. Spending stops at the human approval gate by design.
Every money movement is booked to the ledger as it happens.

The fulfillment plan (what to buy, and the cost the price was based on) is
computed once at intake and persisted, so the price the customer paid and the
spend at fulfill cannot drift apart. The books always reconcile:
  booked spend == sum(plan vendors) == the cost the quote was built from.
"""

from . import ledger, nemotron, pricing, stripe_io


def _plan_for(spec):
    """Estimate cost once, normalise to vendors, keep cost == sum(vendors)."""
    obj, lane = nemotron.estimate_cost(spec)
    if isinstance(obj, dict):
        vendors = obj.get("vendors") or []
        cost = obj.get("cost_cents", 0)
    else:
        vendors, cost = [], int(obj)
    vendors = [{"name": str(v["name"]), "cents": int(v["cents"])}
               for v in vendors if int(v.get("cents", 0)) > 0]
    if not vendors:
        vendors = [{"name": "apis", "cents": int(cost)}]
    return {"cost_cents": sum(v["cents"] for v in vendors), "vendors": vendors, "route": lane}


def intake(spec, customer="customer"):
    """Price the work and send a payment link. Fully autonomous."""
    plan = _plan_for(spec)
    price = pricing.quote_price(plan["cost_cents"])

    order_id = ledger.new_id("o")
    link = stripe_io.create_payment_link(order_id, price, spec[:120])
    ledger.write_plan(order_id, plan)
    ledger.write_order(order_id, {
        "state": "quoted",
        "created": ledger._now(),
        "customer": customer,
        "price_cents": price,
        "est_cost_cents": plan["cost_cents"],
        "payment_link_id": link.get("id", ""),
        "route": plan["route"],
    }, spec=spec)
    return {"order": order_id, "price_cents": price, "est_cost_cents": plan["cost_cents"],
            "checkout_url": link["url"], "vendors": plan["vendors"], "route": plan["route"]}


def collect(order_id):
    """If the customer has paid, book revenue. Autonomous."""
    o = ledger.read_order(order_id)
    if not o:
        return {"error": f"unknown order {order_id}"}
    if o.get("state") in ("funded", "fulfilling", "delivered"):
        return {"order": order_id, "state": o["state"], "already": True}
    if o.get("state") == "lost":
        return {"order": order_id, "state": "lost", "paid": False}
    if not stripe_io.check_paid(order_id, o.get("payment_link_id")):
        return {"order": order_id, "state": "quoted", "paid": False}
    # Idempotent: if a prior collect booked revenue but crashed before advancing
    # state, just advance the state — don't double-book.
    if not any(p["account"] == "revenue" for p in ledger.postings(order_id)):
        ledger.post("revenue", o["price_cents"], order=order_id, ref="stripe_checkout",
                    memo=f"paid by {o.get('customer','customer')}")
    ledger.set_state(order_id, "funded")
    return {"order": order_id, "state": "funded", "revenue_cents": o["price_cents"]}


def abandon(order_id, reason="customer declined"):
    """Mark a quoted order the customer never paid as lost. Feeds price discovery."""
    o = ledger.read_order(order_id)
    if not o:
        return {"error": f"unknown order {order_id}"}
    if o.get("state") != "quoted":
        return {"error": f"order is '{o.get('state')}', only a quoted order can be lost"}
    ledger.set_state(order_id, "lost", lost_reason=reason)
    return {"order": order_id, "state": "lost", "reason": reason}


def fulfill(order_id, approve_via=stripe_io.request_spend):
    """Buy inputs (gated by the human tap), do the work, book costs, deliver."""
    o = ledger.read_order(order_id)
    if not o:
        return {"error": f"unknown order {order_id}"}
    if o.get("state") not in ("funded", "fulfilling"):
        return {"error": f"order {order_id} is '{o.get('state')}', not funded"}

    plan = ledger.read_plan(order_id)
    if not plan:
        return {"error": f"order {order_id} has no priced plan; cannot fulfill without "
                          "the cost basis the quote was built from"}
    vendors = plan["vendors"]
    total = sum(v["cents"] for v in vendors)

    # Idempotent on retry: if a prior fulfill already booked the inputs but
    # crashed before delivery (e.g. the model call failed), the order is left
    # 'fulfilling' with cogs posted. Don't re-approve or double-book — just
    # finish delivery. (The realistic crash point is the model call below,
    # which runs after the cogs loop, so "any cogs" means "all cogs booked".)
    already_paid = any(p["account"].startswith("cogs") for p in ledger.postings(order_id))

    ledger.set_state(order_id, "fulfilling")
    if not already_paid:
        approval = approve_via(order_id, total, vendors)
        if not approval.get("approved"):
            ledger.set_state(order_id, "funded")
            return {"order": order_id, "approved": False,
                    "reason": approval.get("reason", "denied"),
                    "note": "spend needs a human tap in the Link app; agent cannot self-approve"}
        for v in vendors:
            ledger.post(f"cogs:{v['name']}", -v["cents"], order=order_id,
                        ref=approval.get("card", ""), memo=v["name"])

    deliverable, lane = nemotron.fulfill(o.get("spec", ""))
    ledger.set_state(order_id, "delivered", deliverable_route=lane)

    p = ledger.pnl(order_id)
    return {"order": order_id, "approved": True, "spent_cents": total,
            "profit_cents": p["profit_cents"], "margin_pct": p["margin_pct"],
            "deliverable": deliverable, "route": lane}
