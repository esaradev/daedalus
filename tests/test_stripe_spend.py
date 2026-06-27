"""Spend adapters: stub refs offline, real charge mocked, MPP funded cap."""

import pytest

from daedalus.stripe_spend import LinkSpender, ProjectsSpender, MPPSpender, get_spender


def test_link_stub_without_key():
    ref = LinkSpender(api_key="")(456, "openrouter")
    assert ref.startswith("vcard_stub")


def test_link_real_charge_mocked(monkeypatch):
    import daedalus.stripe_spend as ss
    seen = {}

    def create(**kw):
        seen.update(kw)
        return type("PI", (), {"id": "pi_live_1"})()

    monkeypatch.setattr(ss.stripe, "PaymentIntent", type("X", (), {"create": staticmethod(create)}))
    ref = LinkSpender(api_key="sk_test_x")(456, "openrouter")
    assert ref == "pi_live_1"
    assert seen["amount"] == 456 and seen["currency"] == "usd"


def test_projects_stub():
    assert ProjectsSpender()(456, "vercel").startswith("proj_")


def test_mpp_funded_spends_and_decrements():
    mpp = MPPSpender(wallet_balance_cents=1000)
    ref = mpp(400, "api")
    assert ref.startswith("x402_") and mpp.wallet == 600


def test_mpp_underfunded_raises():
    with pytest.raises(RuntimeError):
        MPPSpender(wallet_balance_cents=100)(400, "api")


def test_get_spender_selects_rail():
    assert isinstance(get_spender("link"), LinkSpender)
    assert isinstance(get_spender("mpp", wallet_balance_cents=10), MPPSpender)
    with pytest.raises(ValueError):
        get_spender("nope")
