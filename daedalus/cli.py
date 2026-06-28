"""daedalus CLI. Wires the stack from config (real adapters when keys are set,
labelled stubs otherwise) and runs the loop.

  demo [url]      one paid job end to end + a blocked spend + the five numbers
  job <url>       run one paid audit as a product flow (not the scripted demo)
  approve <id>    human approval of an order's spend (the out-of-band gate)
  audit <url>     run the real security audit, print the report
  pnl             read the book
"""

import sys

from . import config
from .audit_log import AuditLog
from .egress import Egress
from .jobs.audit import run_audit, report_markdown
from .ledger import Ledger, dollars
from .memory import MemoryRecorder
from .nemotron import Nemotron
from .orders import OrderStore
from .orchestrator import Orchestrator
from .pricing import Pricing
from .spend_control import SpendControl, mint_approval
from .stripe_earn import StripeEarn
from .stripe_spend import LinkSpender


def build_stack(db_path=None, reset=False):
    db_path = db_path or config.DB_PATH
    order_path = config.ORDER_STORE_PATH
    if reset:
        for p in (db_path, config.AUDIT_LOG_PATH, config.DATA_DIR / "pricing.json", order_path):
            try:
                p.unlink()
            except (FileNotFoundError, TypeError):
                pass
    ledger = Ledger(str(db_path))
    pricing = Pricing()
    orders = OrderStore(order_path)
    memory = MemoryRecorder()
    egress = Egress()
    audit_log = AuditLog()
    spender = LinkSpender() if config.STRIPE_ENABLED else None
    spend = SpendControl(ledger, egress=egress, audit_log=audit_log, mode=config.APPROVAL_MODE, spender=spender)
    earn = StripeEarn(ledger)
    nemo = Nemotron()
    orch = Orchestrator(ledger, pricing, spend, earn, nemo, order_store=orders, memory=memory)
    return {"ledger": ledger, "pricing": pricing, "egress": egress, "audit_log": audit_log,
            "spend": spend, "earn": earn, "nemotron": nemo, "orch": orch,
            "orders": orders, "memory": memory}


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
    print("ACT 2  ·  the gate blocks three bad spends, one per protection")

    def verdict(d):
        return f"{'allowed' if d.allowed else 'BLOCKED'} by {d.protection}: {d.reason}"

    b1 = spend.authorize("data-broker", "scrape.shady.net", 300, approval_token=mint_approval("data-broker", 300))
    print(f"  security:   pay data-broker at scrape.shady.net {dollars(300)}")
    print(f"    -> {verdict(b1)}")
    b2 = spend.authorize("openrouter", "openrouter.ai", 20000, approval_token=mint_approval("openrouter", 20000))
    print(f"  cred cap:   pay openrouter {dollars(20000)}, over its per-vendor cap")
    print(f"    -> {verdict(b2)}")
    b3 = spend.authorize("openrouter", "openrouter.ai", 100, approval_token=None)
    print(f"  economics:  pay openrouter {dollars(100)} with no human approval tap")
    print(f"    -> {verdict(b3)}")

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
    if config.STRIPE_ENABLED and config.OPENROUTER_API_KEY:
        print("running live: real Stripe test-mode charges + Nemotron Ultra. test mode, no real money moved.")
    else:
        print("to run on real money: set STRIPE_SECRET_KEY (test) + OPENROUTER_API_KEY in .env")
    print()


def cmd_job(url):
    s = build_stack()
    orch = s["orch"]
    print(f"\ndaedalus job  ·  Hermes treasury flow  ·  target: {url}")
    _rule()
    r = orch.run_paid_audit(url, customer="judge", approve=mint_approval,
                            test_collect=True, evolve=True, source_tool="cli_job")
    print(f"  order: {r.get('id')}")
    print(f"  state: {r.get('state')}")
    print(f"  price: {dollars(r.get('price_cents', 0))}  est cost: {dollars(r.get('est_cost_cents', 0))}")
    print(f"  checkout: {r.get('checkout_url', '')}")
    for ev in r.get("events", []):
        msg = ev.get("message", "")
        print(f"  [{ev.get('kind')}] {msg}")
    if r.get("report"):
        rep = r["report"]
        print(f"  score: {rep['score']}/100 — {rep['summary']}")
        print(f"  public summary  [cloud Nemotron Ultra, {r.get('nemotron_route') or 'stub'}]:")
        print(f"      {rep.get('ai_summary', '')[:200]}")
        if r.get("financial_note"):
            print(f"  private note    [local Nemotron, {r.get('financial_note_route')}] "
                  f"(never leaves the box):")
            print(f"      {r.get('financial_note', '')[:160]}")
    if r.get("repricing"):
        e = r["repricing"]
        print(f"  pricing: {e.get('reason')}")
    if r.get("pnl"):
        p = r["pnl"]
        print(f"  profit: {dollars(p['profit_cents'])} ({p['margin_pct']}% margin)")
    if r.get("memory_refs"):
        print("  memory: " + ", ".join(m["id"] for m in r["memory_refs"] if m.get("id")))
    if r.get("warnings"):
        print("  warnings: " + "; ".join(r["warnings"]))
    _rule()
    print("five numbers")
    _five(orch)
    print()


def cmd_audit(url):
    print(report_markdown(run_audit(url)))


def cmd_pnl():
    s = build_stack()
    _five(s["orch"])


def cmd_approve(order_id):
    """The out-of-band human approval gate. No treasury tool can do this, so the
    agent cannot approve its own spend; only a human running this command can."""
    s = build_stack()
    o = s["orders"].approve(order_id)
    if not o:
        print(f"unknown order {order_id} (store: {config.DATA_DIR})")
        return
    print(f"approved {order_id}: spend of {dollars(o.get('est_cost_cents', 0))} for "
          f"{o.get('target', '?')}. The agent may now call treasury_fulfill.")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "pnl"
    if cmd == "demo":
        cmd_demo(args[1] if len(args) > 1 else "https://example.com")
    elif cmd == "job":
        if len(args) < 2:
            print("usage: daedalus job <url>")
            return
        cmd_job(args[1])
    elif cmd == "approve":
        if len(args) < 2:
            print("usage: daedalus approve <order_id>")
            return
        cmd_approve(args[1])
    elif cmd == "audit":
        if len(args) < 2:
            print("usage: daedalus audit <url>")
            return
        cmd_audit(args[1])
    elif cmd == "pnl":
        cmd_pnl()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
