"""dadaledus CLI: inspect the books, or run the loop.

  dadaledus pnl
  dadaledus orders
  dadaledus demo "competitive analysis of the EV charging market"
  dadaledus discover [N]     # simulated market: watch pricing find the demand ceiling
  dadaledus evolve
"""

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
    elif cmd == "evolve":
        print(pricing.evolve())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
