"""Invariant tests for daedalus. No pytest needed: python -m tests.test_daedalus.

Runs in sandbox (no keys), which exercises the real control flow and all the
money/ledger/pricing logic. The only things it cannot cover are a live Stripe
charge and a live Nemotron call, which need keys.
"""

import os
import shutil
import tempfile

os.environ["DAEDALUS_DIR"] = tempfile.mkdtemp(prefix="ddl_tests_")

from daedalus import ledger, pricing, desk, nemotron, stripe_io, hooks  # noqa: E402

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


# ── plan persistence: quote and spend cannot diverge ──────────────────
def test_plan_persisted_and_reused():
    wipe()
    r = desk.intake("market analysis job")
    plan = ledger.read_plan(r["order"])
    check("plan persisted at intake", plan is not None)
    check("plan cost == quoted est cost", plan["cost_cents"] == r["est_cost_cents"])
    check("cost == sum(vendors)", plan["cost_cents"] == sum(v["cents"] for v in plan["vendors"]))
    desk.collect(r["order"])
    f = desk.fulfill(r["order"], approve_via=approve)
    check("fulfill spends exactly the planned cost", f["spent_cents"] == r["est_cost_cents"])
    check("profit reconciles: price - planned cost", f["profit_cents"] == r["price_cents"] - r["est_cost_cents"])


# ── abandon / lost ────────────────────────────────────────────────────
def test_abandon_marks_lost():
    wipe()
    r = desk.intake("x")
    a = desk.abandon(r["order"])
    check("abandon sets lost", a["state"] == "lost" and ledger.read_order(r["order"])["state"] == "lost")
    check("lost order books no money", ledger.pnl(r["order"])["revenue_cents"] == 0)


def test_cannot_abandon_funded():
    wipe()
    r = desk.intake("x")
    desk.collect(r["order"])
    a = desk.abandon(r["order"])
    check("cannot abandon a funded order", "error" in a)


# ── conversion + demand-aware pricing ─────────────────────────────────
def _funded(n):
    for _ in range(n):
        r = desk.intake("job")
        desk.collect(r["order"])
        desk.fulfill(r["order"], approve_via=approve)


def _lost(n):
    for _ in range(n):
        desk.abandon(desk.intake("job")["order"])


def test_conversion_math():
    wipe()
    _funded(6)
    _lost(4)
    rate, count = pricing.conversion(window=10)
    check("conversion counts decided orders", count == 10)
    check("conversion rate correct (6/10)", rate == 0.6)


def test_evolve_cuts_when_customers_walk():
    wipe()
    _funded(3)
    _lost(7)  # conversion 0.3 -> below cut threshold
    before = pricing.config()["markup"]
    e = pricing.evolve()
    check("low conversion cuts the markup", e["changed"] and e["markup"] < before)


def test_evolve_holds_in_band():
    wipe()
    _funded(7)
    _lost(3)  # conversion 0.7 -> between cut and raise
    e = pricing.evolve()
    check("mid-band conversion holds", e["changed"] is False)


def test_evolve_raises_when_demand_strong():
    wipe()
    _funded(10)  # conversion 1.0, fat margin
    before = pricing.config()["markup"]
    e = pricing.evolve()
    check("strong demand + fat margin raises", e["changed"] and e["markup"] > before)


def test_discovery_does_not_pin_ceiling():
    wipe()
    wtp = [1900, 1400, 2600, 1700, 1200, 2300, 1600, 2000, 1300, 2800]
    markups, cuts = [], 0
    prev = pricing.config()["markup"]
    for i in range(40):
        r = desk.intake("market analysis")
        if r["price_cents"] <= wtp[i % len(wtp)]:
            desk.collect(r["order"]); desk.fulfill(r["order"], approve_via=approve)
        else:
            desk.abandon(r["order"])
        pricing.evolve()
        m = pricing.config()["markup"]
        if m < prev:
            cuts += 1
        markups.append(m); prev = m
    check("markup never pins at the ceiling", max(markups) < pricing.DEFAULTS["ceiling_markup"])
    check("pricing cut back at least once (real discovery)", cuts >= 1)


# ── frontmatter robustness ────────────────────────────────────────────
def test_frontmatter_robust_and_no_dup_id():
    wipe()
    r = desk.intake('spec with: a colon, #hash, "quotes", and a\n--- line in it')
    ledger.set_state(r["order"], "funded")  # rewrites the file via read->write round-trip
    raw = ledger._order_path(r["order"]).read_text()
    id_lines = [ln for ln in raw.splitlines() if ln.startswith("id:")]
    check("exactly one id line in frontmatter", len(id_lines) == 1)
    o = ledger.read_order(r["order"])
    check("state survives round-trip", o["state"] == "funded")
    check("price stays an int", isinstance(o["price_cents"], int))
    check("spec with colon/hash/quotes survives", "colon" in o["spec"] and "hash" in o["spec"])
    check("--- line inside spec preserved", "--- line in it" in o["spec"])


# ── regression: crash/retry and rollback paths (reviewer-found bugs) ──
def test_fulfill_retry_no_double_cogs():
    wipe()
    r = desk.intake("job")
    desk.collect(r["order"])
    boom = nemotron.fulfill
    nemotron.fulfill = lambda spec: (_ for _ in ()).throw(RuntimeError("model down"))
    try:
        try:
            desk.fulfill(r["order"], approve_via=approve)
        except RuntimeError:
            pass
        mid = [p for p in ledger.postings(r["order"]) if p["account"].startswith("cogs")]
        check("crash leaves cogs booked once", len(mid) == 1)
        check("crashed order stuck in fulfilling", ledger.read_order(r["order"])["state"] == "fulfilling")
    finally:
        nemotron.fulfill = boom
    f = desk.fulfill(r["order"], approve_via=approve)  # retry
    cogs = [p for p in ledger.postings(r["order"]) if p["account"].startswith("cogs")]
    check("retry does NOT double-book cogs", len(cogs) == 1)
    check("retry delivers", f.get("approved") and ledger.read_order(r["order"])["state"] == "delivered")
    check("profit correct after retry", f["profit_cents"] == r["price_cents"] - r["est_cost_cents"])


def test_collect_no_double_revenue_on_replay():
    wipe()
    r = desk.intake("job")
    # simulate a prior collect that booked revenue but never advanced state
    ledger.post("revenue", r["price_cents"], order=r["order"], ref="stripe_checkout")
    desk.collect(r["order"])  # must not post a second revenue line
    rev = [p for p in ledger.postings(r["order"]) if p["account"] == "revenue"]
    check("revenue booked exactly once on replay", len(rev) == 1)
    check("state advanced to funded", ledger.read_order(r["order"])["state"] == "funded")


def test_fulfill_missing_plan_errors():
    wipe()
    r = desk.intake("job")
    desk.collect(r["order"])
    ledger._plan_path(r["order"]).unlink()  # corrupt/lost sidecar
    f = desk.fulfill(r["order"], approve_via=approve)
    check("missing plan refuses to fulfill (no re-estimate)", "error" in f)


def test_rollback_survives_session_end():
    wipe()
    _funded(1)  # gives a fat margin + 100% conversion so evolve raises
    before = pricing.config()["markup"]
    e = pricing.evolve()
    check("evolve changed markup", e["changed"] and pricing.config()["markup"] != before)
    hooks.on_session_end(session_id="s1")  # writes a session-end snapshot
    pricing.rollback()
    check("rollback restores pre-evolve markup despite session-end snapshot",
          pricing.config()["markup"] == before)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
