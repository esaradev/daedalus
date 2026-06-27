"""Pricing: quote math, fulfillment budget, conversion-aware reprice, bounds."""

import pytest

from daedalus.pricing import Pricing, DEFAULTS


@pytest.fixture
def pricing(tmp_path):
    return Pricing(state_path=tmp_path / "pricing.json")


def test_quote_is_cost_times_markup(pricing):
    assert pricing.quote(456) == round(456 * 4.0)


def test_quote_min_price_floor(pricing):
    assert pricing.quote(1) == DEFAULTS["min_price_cents"]


def test_fulfillment_budget_keeps_margin(pricing):
    # 20% floor margin -> may spend at most 80% of price
    assert pricing.fulfillment_budget(1000) == 800


def test_evolve_raises_on_fat_margin_and_demand(pricing):
    e = pricing.evolve({"revenue_cents": 2000, "margin_pct": 80.0}, conversion=1.0)
    assert e["changed"] and e["markup"] > 4.0 and pricing.repriced == 1


def test_evolve_cuts_when_customers_walk(pricing):
    e = pricing.evolve({"revenue_cents": 2000, "margin_pct": 80.0}, conversion=0.3)
    assert e["changed"] and e["markup"] < 4.0


def test_evolve_cuts_on_thin_margin(pricing):
    e = pricing.evolve({"revenue_cents": 2000, "margin_pct": 20.0}, conversion=0.9)
    assert e["changed"] and e["markup"] < 4.0


def test_evolve_holds_in_band(pricing):
    e = pricing.evolve({"revenue_cents": 2000, "margin_pct": 50.0}, conversion=0.65)
    assert e["changed"] is False


def test_evolve_no_history(pricing):
    assert pricing.evolve({"revenue_cents": 0, "margin_pct": 0.0})["changed"] is False


def test_markup_never_exceeds_ceiling(pricing):
    for _ in range(60):
        pricing.evolve({"revenue_cents": 2000, "margin_pct": 90.0}, conversion=1.0)
    assert pricing.markup <= DEFAULTS["ceiling_markup"]


def test_step_capped(pricing):
    old = pricing.markup
    e = pricing.evolve({"revenue_cents": 2000, "margin_pct": 95.0}, conversion=1.0)
    assert e["markup"] <= old * (1 + DEFAULTS["max_step_pct"] / 100) + 1e-9


def test_state_persists(tmp_path):
    p1 = Pricing(state_path=tmp_path / "p.json")
    p1.evolve({"revenue_cents": 2000, "margin_pct": 80.0}, conversion=1.0)
    moved = p1.markup
    p2 = Pricing(state_path=tmp_path / "p.json")
    assert p2.markup == moved
