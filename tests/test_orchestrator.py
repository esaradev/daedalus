"""End-to-end: price -> pay -> authorize spend -> audit -> book -> reprice."""

import pytest

from daedalus.audit_log import AuditLog
from daedalus.egress import Egress
from daedalus.jobs.audit import build_report
from daedalus.ledger import Ledger
from daedalus.nemotron import Nemotron
from daedalus.orchestrator import Orchestrator
from daedalus.pricing import Pricing
from daedalus.spend_control import SpendControl, mint_approval
from daedalus.stripe_earn import StripeEarn

FETCHED = {
    "reachable": True, "status": 200,
    "headers": {"strict-transport-security": "x", "content-security-policy": "x",
                "x-content-type-options": "nosniff", "x-frame-options": "DENY",
                "referrer-policy": "no-referrer", "server": "nginx"},
    "redirect_http_to_https": True,
    "tls": {"valid": True, "days_to_expiry": 200, "error": None},
    "latency_ms": 100,
}


def _tap(vendor, amount):
    return mint_approval(vendor, amount)


def build(tmp_path, mode="attended"):
    ledger = Ledger(":memory:")
    pricing = Pricing(state_path=tmp_path / "p.json")
    audit = AuditLog(tmp_path / "d.log")
    sc = SpendControl(ledger, egress=Egress(allowed={("openrouter.ai", 443)}),
                      audit_log=audit, caps={"openrouter": 10000}, mode=mode)
    earn = StripeEarn(ledger, api_key="")
    nemo = Nemotron(transport=lambda m, model: "The site is adequately secured. No critical gaps.")
    orch = Orchestrator(ledger, pricing, sc, earn, nemo,
                        audit_runner=lambda url, timeout=8: build_report(url, FETCHED),
                        cost_estimate_cents=120)
    return orch, ledger, audit


def test_full_loop_delivers_and_balances(tmp_path):
    orch, ledger, _ = build(tmp_path)
    r = orch.run_job("https://example.com", approve=_tap)
    assert r["state"] == "delivered"
    assert r["price_cents"] == 500 and r["spend_decision"]["allowed"] is True
    assert ledger.total_imbalance() == 0
    p = ledger.pnl()
    assert p["revenue_cents"] == 500 and p["cost_cents"] == 120 and p["profit_cents"] == 380
    assert "ai_summary" in r["report"] and r["report"]["score"] >= 90
    five = orch.five_numbers()
    assert five == {"revenue_cents": 500, "cost_cents": 120, "profit_cents": 380,
                    "blocked_actions": 0, "repriced": 0}


def test_attended_without_tap_blocks_fulfillment(tmp_path):
    orch, ledger, audit = build(tmp_path)
    r = orch.run_job("https://example.com", approve=None)  # no human tap
    assert r["state"] == "funded_unfulfilled"
    assert r["spend_decision"]["allowed"] is False
    assert r["spend_decision"]["protection"] == "economics"
    assert ledger.balance("COGS") == 0          # no spend booked
    assert ledger.pnl()["revenue_cents"] == 500  # but revenue was collected
    assert audit.count_blocked() == 1
    assert orch.five_numbers()["blocked_actions"] == 1


def test_lost_job_feeds_conversion(tmp_path):
    orch, _, _ = build(tmp_path)
    r = orch.run_job("https://example.com", pay=False)
    assert r["state"] == "lost"
    assert orch.conversion() == 0.0  # 0 delivered of 1


def test_reprice_after_profitable_jobs(tmp_path):
    orch, _, _ = build(tmp_path)
    for _ in range(3):
        orch.run_job("https://example.com", approve=_tap)
    before = orch.pricing.markup
    e = orch.reprice()
    assert e["changed"] is True and orch.pricing.markup > before
    assert orch.five_numbers()["repriced"] == 1


def test_blocked_paid_job_keeps_conversion(tmp_path):
    orch, _, _ = build(tmp_path)
    orch.run_job("https://example.com", approve=_tap)   # delivered (customer paid)
    orch.run_job("https://example.com", approve=None)   # funded_unfulfilled (paid, self-blocked)
    # both customers paid; a self-blocked spend must not count as a lost sale
    assert orch.conversion() == 1.0


def test_target_host_not_added_to_spend_allowlist(tmp_path):
    orch, _, audit = build(tmp_path)
    # auditing a shady host must NOT make it a permitted spend destination
    orch.run_job("https://scrape.shady.net", approve=_tap)
    d = orch.spend.authorize("data-broker", "scrape.shady.net", 300,
                             approval_token=mint_approval("data-broker", 300))
    assert d.allowed is False and d.protection == "egress"


def test_book_balances_across_mixed_outcomes(tmp_path):
    orch, ledger, audit = build(tmp_path)
    orch.run_job("https://example.com", approve=_tap)   # delivered
    orch.run_job("https://example.com", approve=None)   # funded, blocked spend
    orch.run_job("https://example.com", pay=False)      # lost
    assert ledger.total_imbalance() == 0
    assert orch.delivered == 1 and orch.jobs == 3
    assert audit.count_blocked() == 1
