"""Invariant tests for dadaledus. No pytest needed: python -m tests.test_dadaledus.

Runs in sandbox (no keys), which exercises the real control flow and all the
money/ledger/pricing logic. The only things it cannot cover are a live Stripe
charge and a live Nemotron call, which need keys.
"""

import os
import shutil
import tempfile

os.environ["DADALEDUS_DIR"] = tempfile.mkdtemp(prefix="ddl_tests_")

from dadaledus import ledger, pricing, desk, nemotron, stripe_io  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def wipe():
    shutil.rmtree(ledger.STORE, ignore_errors=True)
    pricing.CONFIG.parent.mkdir(parents=True, exist_ok=True)


def approve(*a, **k):
    return {"approved": True, "card": "vcard_test"}


def deny(*a, **k):
    return {"approved": False, "reason": "human tapped deny"}


# ── money + ledger invariants ─────────────────────────────────────────
def test_money_is_integer_cents():
    wipe()
    p = ledger.post("revenue", 1234, order="o1")
    check("posting amount is int", isinstance(p["amount"], int))
    check("dollars formats positive", ledger.dollars(1234) == "$12.34")
    check("dollars formats negative", ledger.dollars(-456) == "-$4.56")


def test_double_entry_signs():
    wipe()
    ledger.post("revenue", 4000, order="o1")
    ledger.post("cogs:apis", -420, order="o1")
    ps = ledger.postings("o1")
    rev = [x for x in ps if x["account"] == "revenue"][0]
    cog = [x for x in ps if x["account"].startswith("cogs")][0]
    check("revenue is positive", rev["amount"] > 0)
    check("cogs is negative", cog["amount"] < 0)


def test_pnl_fold_math():
    wipe()
    ledger.post("revenue", 4000, order="o1")
    ledger.post("cogs:apis", -420, order="o1")
    ledger.post("fees:stripe", -130, order="o1")
    p = ledger.pnl()
    check("revenue summed", p["revenue_cents"] == 4000)
    check("spend summed (cogs+fees)", p["spend_cents"] == -550)
    check("profit = revenue + spend", p["profit_cents"] == 3450)
    check("margin pct correct", p["margin_pct"] == round(100 * 3450 / 4000, 1))
    check("vendor breakdown present", p["by_vendor"]["cogs:apis"] == -420)


def test_append_only():
    wipe()
    ledger.post("revenue", 100, order="o1")
    before = ledger.LEDGER.read_text()
    ledger.post("revenue", 200, order="o2")
    after = ledger.LEDGER.read_text()
    check("ledger only grows (old line intact)", after.startswith(before))
    check("ledger has 2 lines", len(after.strip().splitlines()) == 2)


# ── order lifecycle + the approval gate ───────────────────────────────
def test_full_loop_books_profit():
    wipe()
    r = desk.intake("competitive analysis of EV charging")
    check("priced above cost", r["price_cents"] > r["est_cost_cents"])
    c = desk.collect(r["order"])
    check("revenue booked on collect", c["state"] == "funded")
    f = desk.fulfill(r["order"], approve_via=approve)
    check("approved fulfill delivers", f["approved"] and f["profit_cents"] > 0)
    check("profit = price - spend", f["profit_cents"] == r["price_cents"] - f["spent_cents"])


def test_cannot_fulfill_unfunded():
    wipe()
    r = desk.intake("x")
    f = desk.fulfill(r["order"], approve_via=approve)
    check("fulfill blocked until funded", "error" in f)


def test_collect_is_idempotent():
    wipe()
    r = desk.intake("x")
    desk.collect(r["order"])
    desk.collect(r["order"])  # second call must not double-book
    p = ledger.pnl(r["order"])
    check("revenue booked exactly once", p["revenue_cents"] == r["price_cents"])


def test_denied_spend_books_nothing():
    wipe()
    r = desk.intake("x")
    desk.collect(r["order"])
    f = desk.fulfill(r["order"], approve_via=deny)
    accts = [p["account"] for p in ledger.postings(r["order"])]
    check("denied: not approved", f["approved"] is False)
    check("denied: order stays funded", ledger.read_order(r["order"])["state"] == "funded")
    check("denied: no cogs booked", not any(a.startswith("cogs") for a in accts))
    check("denied: revenue still there", "revenue" in accts)


# ── pricing: bounds, step cap, rollback ───────────────────────────────
def test_pricing_respects_ceiling():
    wipe()
    # run many fat-margin orders; markup must never cross the ceiling
    for _ in range(40):
        r = desk.intake("research job")
        desk.collect(r["order"])
        desk.fulfill(r["order"], approve_via=approve)
        pricing.evolve()
    check("markup never exceeds ceiling", pricing.config()["markup"] <= pricing.DEFAULTS["ceiling_markup"])


def test_pricing_step_cap():
    wipe()
    old = pricing.config()["markup"]
    r = desk.intake("research job"); desk.collect(r["order"]); desk.fulfill(r["order"], approve_via=approve)
    e = pricing.evolve()
    if e.get("changed"):
        check("single step <= max_step_pct", e["markup"] <= old * (1 + pricing.DEFAULTS["max_step_pct"] / 100) + 1e-9)
    else:
        check("step cap (no change is also valid)", True)


def test_min_price_floor():
    wipe()
    check("tiny cost still priced >= min_price", pricing.quote_price(1) >= pricing.DEFAULTS["min_price_cents"])


def test_rollback_restores_markup():
    wipe()
    r = desk.intake("research job"); desk.collect(r["order"]); desk.fulfill(r["order"], approve_via=approve)
    before = pricing.config()["markup"]
    e = pricing.evolve()
    if e.get("changed"):
        check("evolve moved markup", pricing.config()["markup"] != before)
        pricing.rollback()
        check("rollback restored markup", pricing.config()["markup"] == before)
    else:
        check("rollback (nothing to undo is valid)", True)


# ── order markdown round-trip + routing ───────────────────────────────
def test_order_md_roundtrip():
    wipe()
    r = desk.intake("a spec with: a colon and #hash in it")
    o = ledger.read_order(r["order"])
    check("state persisted", o["state"] == "quoted")
    check("price persisted as int", o["price_cents"] == r["price_cents"] and isinstance(o["price_cents"], int))
    check("spec persisted", "colon" in o["spec"])


def test_sensitive_routes_local():
    lane_money, _, _ = nemotron.route("here is the customer card and invoice balance $40")
    lane_plain, _, _ = nemotron.route("write a history of bicycles")
    check("financial content routes local", lane_money == "local")
    check("plain content routes cloud", lane_plain == "cloud")


def test_sandbox_is_honest():
    check("sandbox flagged when no stripe key", stripe_io.SANDBOX is True)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
