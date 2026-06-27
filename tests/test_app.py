"""Dashboard API: numbers, ledger, events, webhook, page render."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from daedalus import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "AUDIT_LOG_PATH", tmp_path / "d.log")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(config, "STRIPE_ENABLED", False)  # pure stub mode for the dev webhook path
    # seed a little history
    from daedalus.cli import build_stack
    s = build_stack(reset=True)
    s["ledger"].earn(500, ref="seed", memo="seed")
    s["audit_log"].record(action="spend", vendor="x", amount_cents=300,
                          allowed=False, protection="egress", reason="not on allowlist")
    from daedalus.app import app
    return TestClient(app)


def test_numbers(client):
    r = client.get("/api/numbers")
    assert r.status_code == 200
    body = r.json()
    for k in ("revenue_cents", "cost_cents", "profit_cents", "blocked_actions", "repriced", "status"):
        assert k in body
    assert body["revenue_cents"] == 500 and body["blocked_actions"] == 1


def test_ledger(client):
    body = client.get("/api/ledger").json()
    assert body["pnl"]["revenue_cents"] == 500
    assert body["balanced"] is True
    assert len(body["transactions"]) >= 1


def test_events(client):
    events = client.get("/api/events").json()["events"]
    assert events and events[0]["allowed"] is False


def test_dashboard_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200 and "daedalus" in r.text and "no localStorage" not in r.text.lower()


def test_webhook_rejects_unsigned_when_key_set(client, monkeypatch):
    from daedalus import config
    monkeypatch.setattr(config, "STRIPE_ENABLED", True)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "")
    r = client.post("/webhook", json={"type": "checkout.session.completed", "data": {"object": {}}})
    assert r.status_code == 400 and "WEBHOOK_SECRET" in r.json()["error"]


def test_webhook_bad_body_returns_400(client):
    r = client.post("/webhook", content=b"not json at all")
    assert r.status_code == 400


def test_webhook_books_revenue(client):
    event = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_2", "payment_intent": "pi_2", "amount_total": 700, "metadata": {"order_id": "o2"}}}}
    r = client.post("/webhook", json=event)
    assert r.status_code == 200 and r.json()["booked_cents"] == 700
    assert client.get("/api/numbers").json()["revenue_cents"] == 1200  # 500 seed + 700
