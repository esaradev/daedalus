"""dadaledus CLI: inspect the books, or run the full loop for the demo.

  dadaledus pnl
  dadaledus orders
  dadaledus demo "competitive analysis of the EV charging market"
  dadaledus evolve
"""

import sys

from . import desk, ledger, pricing, stripe_io


def _print_pnl(order=None):
    p = ledger.pnl(order)
    print(f"  revenue  {ledger.dollars(p['revenue_cents']):>12}")
    print(f"  spend    {ledger.dollars(p['spend_cents']):>12}")
    print(f"  profit   {ledger.dollars(p['profit_cents']):>12}   ({p['margin_pct']}% margin, "
          f"{p['orders']} orders)")
    if p["by_vendor"]:
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
    c = desk.collect(r["order"])
    print(f"   {c}\n")

    print("3. fulfill: request ONE scoped card for the whole spend")
    print("   (real mode blocks here until you tap approve in the Link app)")
    f = desk.fulfill(r["order"])
    if not f.get("approved"):
        print(f"   not approved: {f}")
        return
    print(f"   approved, spent {ledger.dollars(f['spent_cents'])}, "
          f"delivered via {f['route']} Nemotron")
    print(f"   --- deliverable ---\n   {f['deliverable'][:160].replace(chr(10),' ')}...\n")

    print("4. the book:")
    _print_pnl()
    print("\n5. evolve pricing from the book:")
    e = pricing.evolve()
    print(f"   {e}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "pnl"
    if cmd == "pnl":
        _print_pnl(args[1] if len(args) > 1 else None)
    elif cmd == "orders":
        for o in ledger.open_orders():
            print(f"  {o['id']}  {o.get('state','?'):<10} "
                  f"{ledger.dollars(o.get('price_cents',0))}  {o.get('spec','')[:60]}")
    elif cmd == "demo":
        _demo(" ".join(args[1:]) or "competitive analysis of the EV charging market")
    elif cmd == "evolve":
        print(pricing.evolve())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
