"""daedalus CLI. Wires the stack from config (real adapters when keys are set,
labelled stubs otherwise) and runs the loop.

  demo [url]   one paid job end to end + a blocked spend + the five numbers
  audit <url>  run the real security audit, print the report
  pnl          read the book
  serve        launch the dashboard
"""

import sys

from . import config
from .audit_log import AuditLog
from .egress import Egress
from .jobs.audit import run_audit, report_markdown
from .ledger import Ledger, dollars
from .nemotron import Nemotron
from .orchestrator import Orchestrator
from .pricing import Pricing
from .spend_control import SpendControl, mint_approval
from .stripe_earn import StripeEarn
from .stripe_spend import LinkSpender


def build_stack(db_path=None, reset=False):
    db_path = db_path or config.DB_PATH
    if reset:
        for p in (db_path, config.AUDIT_LOG_PATH, config.DATA_DIR / "pricing.json"):
            try:
                p.unlink()
            except (FileNotFoundError, TypeError):
                pass
    ledger = Ledger(str(db_path))
    pricing = Pricing()
    egress = Egress()
    audit_log = AuditLog()
    spender = LinkSpender() if config.STRIPE_ENABLED else None
    spend = SpendControl(ledger, egress=egress, audit_log=audit_log, mode=config.APPROVAL_MODE, spender=spender)
    earn = StripeEarn(ledger)
    nemo = Nemotron()
    orch = Orchestrator(ledger, pricing, spend, earn, nemo)
    return {"ledger": ledger, "pricing": pricing, "egress": egress, "audit_log": audit_log,
            "spend": spend, "earn": earn, "nemotron": nemo, "orch": orch}


def _rule():
    print("-" * 68)


def _five(orch):
    f = orch.five_numbers()
    print(f"  revenue {dollars(f['revenue_cents']):>10}   cost {dollars(f['cost_cents']):>9}   "
          f"profit {dollars(f['profit_cents']):>10}")
    print(f"  blocked actions: {f['blocked_actions']}     repriced: {f['repriced']}")


def cmd_demo(url):
    s = build_stack(reset=True)
    orch, spend = s["orch"], s["spend"]
    st = config.status()
    mode = f"stripe={st['stripe']}  nemotron={st['nemotron']}  approval={st['approval_mode']}"
    print(f"\ndaedalus demo  ·  {mode}")
    print("(labelled stubs where no key is set; the gate, ledger and audit are always real)")

    _rule()
    print(f"ACT 1  ·  one paid security audit, end to end\n  target: {url}")
    r = orch.run_job(url, customer="acme", approve=mint_approval)
    print(f"  priced {dollars(r['price_cents'])} (cost {dollars(orch.cost_estimate)}, "
          f"markup {orch.pricing.markup}x); checkout {r['checkout_url']}")
    print("  customer paid -> revenue booked")
    d = r["spend_decision"]
    print(f"  APPROVAL: buy the report model for {dollars(orch.cost_estimate)} "
          f"-> {'authorized' if d['allowed'] else 'blocked'} ({d['protection']})")
    print("    attended: the agent cannot self-approve; the demo supplies the human tap")
    if r["state"] == "delivered":
        rep = r["report"]
        print(f"  audited live: score {rep['score']}/100 — {rep['summary']}")
        print(f"  ai summary: {rep['ai_summary'][:140]}")
        print(f"  PROFIT BOOKED: {dollars(r['pnl']['profit_cents'])} ({r['pnl']['margin_pct']}% margin)")

    _rule()
    print("ACT 2  ·  the gate blocks a bad spend")
    bad = spend.authorize("data-broker", "scrape.shady.net", 300, approval_token=mint_approval("data-broker", 300))
    print(f"  agent tries to pay data-broker at scrape.shady.net ({dollars(300)})")
    print(f"  -> {'allowed' if bad.allowed else 'BLOCKED'} by {bad.protection}: {bad.reason}")

    _rule()
    print("THE FIVE NUMBERS")
    _five(orch)

    _rule()
    print("ACT 3  ·  reprice from the book")
    e = orch.reprice()
    print(f"  {e['reason']}")
    if e["changed"]:
        print(f"  markup {e['old_markup']}x -> {e['markup']}x")
    print()
    print("to run on real money: set STRIPE_SECRET_KEY (test) + OPENROUTER_API_KEY in .env")
    print()


def cmd_audit(url):
    print(report_markdown(run_audit(url)))


def cmd_pnl():
    s = build_stack()
    _five(s["orch"])


def cmd_serve():
    from .app import serve
    serve()


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "pnl"
    if cmd == "demo":
        cmd_demo(args[1] if len(args) > 1 else "https://example.com")
    elif cmd == "audit":
        if len(args) < 2:
            print("usage: daedalus audit <url>")
            return
        cmd_audit(args[1])
    elif cmd == "pnl":
        cmd_pnl()
    elif cmd == "serve":
        cmd_serve()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
