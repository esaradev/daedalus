"""Ledger invariants: balanced postings, integer cents, correct P&L fold."""

import pytest

from daedalus.ledger import Ledger, Unbalanced, dollars


def test_balanced_post_ok(ledger):
    txn = ledger.post("t", [("Cash", 1000), ("Revenue", -1000)])
    assert isinstance(txn, int)
    assert ledger.total_imbalance() == 0


def test_unbalanced_post_raises(ledger):
    with pytest.raises(Unbalanced):
        ledger.post("t", [("Cash", 1000), ("Revenue", -999)])


def test_empty_post_raises(ledger):
    with pytest.raises(Unbalanced):
        ledger.post("t", [])


def test_fractional_cents_rejected(ledger):
    with pytest.raises(ValueError):
        ledger.post("t", [("Cash", 10.5), ("Revenue", -10.5)])


def test_earn_books_cash_and_revenue(ledger):
    ledger.earn(1824, ref="pi_x", memo="paid")
    assert ledger.balance("Cash") == 1824
    assert ledger.balance("Revenue") == -1824  # credit-normal
    assert ledger.total_imbalance() == 0


def test_spend_books_cogs_and_cash(ledger):
    ledger.earn(1824)
    ledger.spend(456, "openrouter", ref="card_x")
    assert ledger.balance("COGS") == 456
    assert ledger.balance("Cash") == 1824 - 456
    assert ledger.total_imbalance() == 0


def test_spend_must_be_positive(ledger):
    with pytest.raises(ValueError):
        ledger.spend(0, "x")
    with pytest.raises(ValueError):
        ledger.spend(-5, "x")


def test_pnl_math(ledger):
    ledger.earn(1824)
    ledger.spend(456, "apis")
    p = ledger.pnl()
    assert p["revenue_cents"] == 1824
    assert p["cost_cents"] == 456
    assert p["profit_cents"] == 1824 - 456
    assert p["cash_cents"] == 1824 - 456
    assert p["profit_cents"] == p["cash_cents"]  # all-cash model
    assert p["margin_pct"] == round(100 * 1368 / 1824, 1)


def test_pnl_zero_revenue_safe(ledger):
    assert ledger.pnl()["margin_pct"] == 0.0


def test_book_invariant_holds_over_many(ledger):
    for i in range(50):
        ledger.earn(100 + i)
        if i % 2 == 0:
            ledger.spend(10 + i, "v")
    assert ledger.total_imbalance() == 0


def test_transactions_feed_newest_first(ledger):
    ledger.earn(100)
    ledger.spend(40, "v")
    feed = ledger.transactions()
    assert len(feed) == 2
    assert feed[0]["id"] > feed[1]["id"]
    assert feed[0]["debit"] > 0


def test_persists_to_disk(tmp_path):
    db = tmp_path / "t.db"
    lg = Ledger(str(db))
    lg.earn(500)
    lg.close()
    lg2 = Ledger(str(db))
    assert lg2.balance("Cash") == 500
    lg2.close()


def test_duplicate_nonempty_ref_rejected(ledger):
    ledger.earn(100, ref="pi_1")
    with pytest.raises(ValueError):
        ledger.earn(200, ref="pi_1")  # DB-enforced idempotency
    assert ledger.pnl()["revenue_cents"] == 100


def test_empty_ref_allows_multiple(ledger):
    ledger.earn(100)  # ref ""
    ledger.earn(200)  # ref "" — empty refs are exempt from the unique constraint
    assert ledger.pnl()["revenue_cents"] == 300


def test_dollars_formatting():
    assert dollars(1824) == "$18.24"
    assert dollars(-456) == "-$4.56"
    assert dollars(0) == "$0.00"
