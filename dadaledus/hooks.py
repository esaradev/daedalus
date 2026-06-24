"""Hooks. Brief the agent on the books at session start; snapshot at end."""

from . import ledger, pricing


def on_session_start(session_id="", platform="", **kwargs):
    p = ledger.pnl()
    cfg = pricing.config()
    parts = [
        f"[treasury] book: revenue {ledger.dollars(p['revenue_cents'])}, "
        f"spend {ledger.dollars(p['spend_cents'])}, "
        f"profit {ledger.dollars(p['profit_cents'])} ({p['margin_pct']}% margin) "
        f"across {p['orders']} order(s). markup {cfg['markup']}x."
    ]
    open_o = ledger.open_orders()
    if open_o:
        parts.append(f"[treasury] {len(open_o)} order(s) in flight:")
        for o in open_o[:5]:
            parts.append(f"  - {o['id']}: {o.get('state','?')} "
                         f"({ledger.dollars(o.get('price_cents',0))}) {o.get('spec','')[:50]}")
        parts.append("  Funded orders need treasury_fulfill (you'll be asked to approve spend).")
    return "\n".join(parts)


def on_session_end(session_id="", platform="", completed=False, **kwargs):
    # snapshot current pricing so the book has a marker per session
    pricing._snapshot(pricing.config(), f"session end {session_id}")
    return None
