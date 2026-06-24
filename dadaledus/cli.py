"""dadaledus CLI: inspect the books, or run the loop.

  dadaledus pnl
  dadaledus orders
  dadaledus demo "competitive analysis of the EV charging market"
  dadaledus discover [N]     # simulated market: watch pricing find the demand ceiling
  dadaledus showcase         # the full story in one run, for recording
  dadaledus evolve
"""

import shutil
import sys

from . import desk, ledger, pricing, stripe_io


def _approve(*a, **k):
    return {"approved": True, "card": "vcard_demo"}


def _print_pnl(order=None):
    p = ledger.pnl(order)
    print(f"  revenue  {ledger.dollars(p['revenue_cents']):>12}")
    print(f"  spend    {ledger.dollars(p['spend_cents']):>12}")
    print(f"  profit   {ledger.dollars(p['profit_cents']):>12}   ({p['margin_pct']}% margin, "
          f"{p['orders']} orders)")
    for acct, c in sorted(p["by_vendor"].items()):
        print(f"     {acct:<16} {ledger.dollars(c):>10}")


def _demo(spec):
    mode = "SANDBOX (no Stripe key — no real money moves)" if stripe_io.SANDBOX else "STRIPE TEST MODE"
    print(f"=== dadaledus demo · {mode} ===\n")

    print(f"1. order in: {spec}")
    r = desk.intake(spec)
    print(f"   priced {ledger.dollars(r['price_cents'])} "
          f"(est cost {ledger.dollars(r['est_cost_cents'])}, markup {pricing.config()['markup']}x)")
    print(f"   checkout: {r['checkout_url']}\n")

    print("2. customer pays -> book revenue")
    print(f"   {desk.collect(r['order'])}\n")

    print("3. fulfill: request ONE scoped card for the whole spend")
    print("   (real mode blocks here until you tap approve in the Link app)")
    f = desk.fulfill(r["order"])
    if not f.get("approved"):
        print(f"   not approved: {f}")
        return
    print(f"   approved, spent {ledger.dollars(f['spent_cents'])}, "
          f"delivered via {f['route']} Nemotron")
    print(f"   --- deliverable ---\n   {f['deliverable'][:160].replace(chr(10), ' ')}...\n")

    print("4. the book:")
    _print_pnl()
    print("\n5. evolve pricing from the book:")
    print(f"   {pricing.evolve()}")


# Simulated customers, so price discovery is visible offline. Each customer has
# a willingness to pay; they buy only if the quoted price is at or under it.
# This is a clearly-labelled SIMULATION of demand, not a claim about real sales.
_WTP_CENTS = [1900, 1400, 2600, 1700, 1200, 2300, 1600, 2000, 1300, 2800,
              1500, 2100, 1800, 1100, 2400, 1650, 2200, 1450, 1950, 1350]


def _discover(n):
    print("=== dadaledus discover · SIMULATED MARKET (no real money) ===")
    print("watching the markup find the demand ceiling instead of a hardcoded cap\n")
    print(f"{'#':>3} {'price':>8} {'WTP':>8}  outcome   {'markup':>7} {'conv':>5}")
    spec = "market analysis"
    for i in range(n):
        wtp = _WTP_CENTS[i % len(_WTP_CENTS)]
        r = desk.intake(spec)
        price = r["price_cents"]
        if price <= wtp:
            desk.collect(r["order"])
            desk.fulfill(r["order"], approve_via=_approve)
            outcome = "PAID"
        else:
            desk.abandon(r["order"])
            outcome = "lost"
        e = pricing.evolve()
        conv = e.get("conversion")
        print(f"{i+1:>3} {ledger.dollars(price):>8} {ledger.dollars(wtp):>8}  "
              f"{outcome:<8}  {pricing.config()['markup']:>6}x "
              f"{('n/a' if conv is None else format(conv, '.0%')):>5}")
    print()
    _print_pnl()


def _reset_book():
    shutil.rmtree(ledger.ORDERS, ignore_errors=True)
    for f in (ledger.LEDGER, pricing.CONFIG, pricing.SNAPSHOTS):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def _rule():
    print("-" * 66)


def _showcase():
    _reset_book()
    mode = "SANDBOX  (no keys, no real money — plug in your own to go live)" \
        if stripe_io.SANDBOX else "STRIPE TEST MODE"
    print()
    print("dadaledus  ·  an agent that runs a business and keeps its own books")
    print(mode)

    # Act 1 — one order, the whole loop, with the approval gate in the open.
    _rule()
    print("ACT 1  ·  one order, end to end\n")
    spec = "competitive analysis of the EV charging market"
    print(f"order in:  {spec}")
    r = desk.intake(spec)
    print(f"  priced {ledger.dollars(r['price_cents'])} "
          f"(cost to fulfill {ledger.dollars(r['est_cost_cents'])}, markup {pricing.config()['markup']}x)")
    print(f"  checkout link sent:  {r['checkout_url']}")
    print(f"  {desk.collect(r['order'])['state']}: customer paid, revenue booked\n")

    def approve(order_id, total, vendors):
        line = ", ".join(f"{v['name']} {ledger.dollars(v['cents'])}" for v in vendors)
        print(f"  APPROVAL REQUESTED  ->  spend {ledger.dollars(total)}  ({line})")
        print(f"     revenue {ledger.dollars(r['price_cents'])}, "
              f"projected margin {ledger.dollars(r['price_cents'] - total)}")
        print("     real mode blocks here until you tap approve in the Stripe Link app.")
        print("     the agent cannot approve its own spend. that gate is the safety.")
        print("     [sandbox] auto-approving so the demo can continue")
        return {"approved": True, "card": f"vcard_demo_{order_id}"}

    f = desk.fulfill(r["order"], approve_via=approve)
    print(f"  bought inputs, produced on {f['route']} Nemotron, delivered")
    print(f"  PROFIT BOOKED:  {ledger.dollars(f['profit_cents'])}  ({f['margin_pct']}% margin)\n")
    _print_pnl()

    # Act 2 — the agent prices itself by watching who actually pays.
    _rule()
    print("ACT 2  ·  the agent finds its own price\n")
    print("a week of orders. customers buy only if the price clears their budget.")
    print("the agent raises while they keep buying, cuts when they walk away.\n")
    print(f"  {'#':>3} {'price':>8} {'budget':>8}  outcome   {'markup':>7} {'sold':>5}")
    for i in range(20):
        wtp = _WTP_CENTS[i % len(_WTP_CENTS)]
        o = desk.intake("market analysis")
        if o["price_cents"] <= wtp:
            desk.collect(o["order"]); desk.fulfill(o["order"], approve_via=_approve)
            outcome = "PAID"
        else:
            desk.abandon(o["order"]); outcome = "lost"
        e = pricing.evolve()
        conv = e.get("conversion")
        print(f"  {i+1:>3} {ledger.dollars(o['price_cents']):>8} {ledger.dollars(wtp):>8}  "
              f"{outcome:<8}  {pricing.config()['markup']:>6}x "
              f"{('n/a' if conv is None else format(conv, '.0%')):>5}")

    # Close — the book, and the call to action.
    _rule()
    print("THE BOOK\n")
    _print_pnl()
    print()
    print("every dollar above was earned, spent, and booked by the agent itself.")
    print("the only thing it could not do alone was approve its own spend.")
    print()
    print("to run it on real money: set STRIPE_API_KEY (test mode) and a Nemotron")
    print("endpoint, then drive it from Hermes. the loop above does not change.")
    print()


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "pnl"
    if cmd == "pnl":
        _print_pnl(args[1] if len(args) > 1 else None)
    elif cmd == "orders":
        for o in ledger.open_orders():
            print(f"  {o['id']}  {o.get('state', '?'):<10} "
                  f"{ledger.dollars(o.get('price_cents', 0))}  {o.get('spec', '')[:60]}")
    elif cmd == "demo":
        _demo(" ".join(args[1:]) or "competitive analysis of the EV charging market")
    elif cmd == "discover":
        _discover(int(args[1]) if len(args) > 1 else 24)
    elif cmd == "showcase":
        _showcase()
    elif cmd == "evolve":
        print(pricing.evolve())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
