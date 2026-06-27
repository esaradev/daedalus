"""Nemotron: validate-and-retry on bad structured output, plus local routing."""

import pytest

from daedalus import config
from daedalus.nemotron import Nemotron, NemotronError, _extract_json


def test_extract_json_from_noisy_text():
    assert _extract_json('thinking... {"risk": "low"} done') == {"risk": "low"}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        _extract_json("no json here")


def test_structured_retries_then_succeeds():
    calls = {"n": 0}

    def transport(messages, model):
        calls["n"] += 1
        if calls["n"] == 1:
            return "the model stopped early with no json"      # invalid
        if calls["n"] == 2:
            return '{"risk": "high"'                            # malformed json
        return '{"risk": "high", "score": 20}'                 # valid

    n = Nemotron(transport=transport)
    obj = n.structured([{"role": "user", "content": "classify"}],
                       validate=lambda o: "risk" in o, max_retries=3)
    assert obj == {"risk": "high", "score": 20}
    assert calls["n"] == 3


def test_structured_raises_after_max_retries():
    n = Nemotron(transport=lambda m, model: "never any json")
    with pytest.raises(NemotronError):
        n.structured([{"role": "user", "content": "x"}], validate=lambda o: True, max_retries=2)


def test_structured_rejects_failing_validation():
    n = Nemotron(transport=lambda m, model: '{"risk": "low"}')
    with pytest.raises(NemotronError):
        n.structured([{"role": "user", "content": "x"}],
                     validate=lambda o: o.get("risk") == "high", max_retries=2)


def test_chat_uses_transport():
    n = Nemotron(transport=lambda m, model: "hello from " + model)
    assert "hello from" in n.chat("hi")


def test_sensitive_routes_local_when_configured(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "http://localhost:8000/v1")
    seen = {}

    def transport(messages, model):
        return "ok"

    n = Nemotron(transport=transport)
    n.complete([{"role": "user", "content": "the customer card and ledger balance"}], sensitive=True)
    assert n.last_route == "local"
    n.complete([{"role": "user", "content": "public site audit"}], sensitive=False)
    assert n.last_route == "cloud"


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_http_parses_content(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-fake")
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "")
    import daedalus.nemotron as nm
    monkeypatch.setattr(nm.httpx, "post",
                        lambda *a, **k: _FakeResp({"choices": [{"message": {"content": "audit summary"}}]}))
    assert Nemotron().chat("summarize") == "audit summary"


def test_http_no_choices_raises(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-fake")
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "")
    import daedalus.nemotron as nm
    monkeypatch.setattr(nm.httpx, "post", lambda *a, **k: _FakeResp({"choices": []}))
    with pytest.raises(NemotronError):
        Nemotron().chat("x")


def test_http_request_failure_raises(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-fake")
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "")
    import daedalus.nemotron as nm

    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(nm.httpx, "post", boom)
    with pytest.raises(NemotronError):
        Nemotron().chat("x")


def test_sensitive_without_local_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "")
    n = Nemotron(transport=lambda m, model: "x")
    with pytest.raises(NemotronError):
        n.complete([{"role": "user", "content": "the customer card and ledger"}], sensitive=True)


def test_offline_stub_when_no_key(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "LOCAL_NEMOTRON_URL", "")
    n = Nemotron()  # no transport, no key -> labelled stub
    out = n.chat("summarize the audit")
    assert "stub Nemotron" in out
