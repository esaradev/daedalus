"""Stripe earn: payment links, webhook booking, idempotency."""

import pytest

from daedalus.stripe_earn import StripeEarn


def _event(amount=1824, sid="cs_1", pi="pi_1", order="o1", etype="checkout.session.completed"):
    return {"type": etype, "data": {"object": {
        "id": sid, "payment_intent": pi, "amount_total": amount,
        "metadata": {"order_id": order}}}}


def test_stub_payment_link_without_key(ledger):
    earn = StripeEarn(ledger, api_key="")
    link = earn.create_payment_link(1824, "audit", order_id="o1")
    assert link["stub"] is True and link["amount_cents"] == 1824 and link["url"]


def test_webhook_books_revenue(ledger):
    earn = StripeEarn(ledger, api_key="")
    res = earn.handle_event(_event(1824))
    assert res["booked_cents"] == 1824
    assert ledger.pnl()["revenue_cents"] == 1824


def test_webhook_idempotent(ledger):
    earn = StripeEarn(ledger, api_key="")
    earn.handle_event(_event(1824, pi="pi_dup"))
    res2 = earn.handle_event(_event(1824, pi="pi_dup"))
    assert res2.get("already_booked") is True
    assert ledger.pnl()["revenue_cents"] == 1824  # booked once


def test_webhook_ignores_other_events(ledger):
    earn = StripeEarn(ledger, api_key="")
    res = earn.handle_event(_event(etype="payment_intent.created"))
    assert "ignored" in res
    assert ledger.pnl()["revenue_cents"] == 0


def test_webhook_missing_amount(ledger):
    earn = StripeEarn(ledger, api_key="")
    ev = _event()
    ev["data"]["object"]["amount_total"] = None
    assert "error" in earn.handle_event(ev)


def test_real_payment_link_calls_sdk(ledger, monkeypatch):
    import daedalus.stripe_earn as se

    class _Obj:
        id = "price_1"
        url = "https://checkout.stripe.com/abc"

    monkeypatch.setattr(se.stripe, "Price", type("P", (), {"create": staticmethod(lambda **k: _Obj())}))
    monkeypatch.setattr(se.stripe, "PaymentLink", type("L", (), {"create": staticmethod(lambda **k: _Obj())}))
    earn = StripeEarn(ledger, api_key="sk_test_x")
    link = earn.create_payment_link(500, "audit", order_id="o2")
    assert link["stub"] is False and link["url"].startswith("https://checkout.stripe.com")


def test_charge_test_stub_books_revenue(ledger):
    earn = StripeEarn(ledger, api_key="")
    res = earn.charge_test(500, "audit", order_id="o1")
    assert res["stub"] is True and res["booked_cents"] == 500
    assert ledger.pnl()["revenue_cents"] == 500


def test_charge_test_real_mocked_and_idempotent(ledger, monkeypatch):
    import daedalus.stripe_earn as se

    def create(**kw):
        return type("PI", (), {"id": "pi_real_1", "status": "succeeded"})()

    monkeypatch.setattr(se.stripe, "PaymentIntent", type("X", (), {"create": staticmethod(create)}))
    earn = StripeEarn(ledger, api_key="sk_test_x")
    r1 = earn.charge_test(500, "audit", order_id="o1")
    assert r1["booked_cents"] == 500 and r1["ref"] == "pi_real_1"
    r2 = earn.charge_test(500, "audit", order_id="o1")  # same PI id -> idempotent
    # different PI each real call in practice; here we force the same id to prove the guard
    assert r2.get("already_booked") is True
    assert ledger.pnl()["revenue_cents"] == 500


def test_verify_webhook_delegates(ledger, monkeypatch):
    import daedalus.stripe_earn as se
    called = {}

    def fake_construct(payload, sig, secret):
        called["ok"] = (payload, sig, secret)
        return {"type": "checkout.session.completed"}

    monkeypatch.setattr(se.stripe.Webhook, "construct_event", staticmethod(fake_construct))
    earn = StripeEarn(ledger, api_key="sk_test_x", webhook_secret="whsec_x")
    ev = earn.verify_webhook(b"{}", "sig")
    assert ev["type"] == "checkout.session.completed" and called["ok"][2] == "whsec_x"
