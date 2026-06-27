"""Audit job: pure evaluation/scoring offline, plus one live smoke test."""

import pytest

from daedalus.jobs import audit

STRONG = {
    "reachable": True, "status": 200,
    "headers": {
        "strict-transport-security": "max-age=63072000",
        "content-security-policy": "default-src 'self'",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "server": "nginx",
    },
    "redirect_http_to_https": True,
    "tls": {"valid": True, "days_to_expiry": 200, "error": None},
    "latency_ms": 120,
}

WEAK = {
    "reachable": True, "status": 200,
    "headers": {"server": "Apache/2.2.3"},
    "redirect_http_to_https": False,
    "tls": {"valid": False, "days_to_expiry": None, "error": "expired"},
    "latency_ms": 2500,
}


def _by_name(checks):
    return {c["name"]: c for c in checks}


def test_strong_site_scores_high():
    checks = audit.evaluate(STRONG)
    score = audit.score_checks(checks)
    assert score >= 90
    assert _by_name(checks)["tls_certificate"]["status"] == "pass"
    assert _by_name(checks)["https_enforced"]["status"] == "pass"


def test_weak_site_scores_low_with_fails():
    checks = audit.evaluate(WEAK)
    names = _by_name(checks)
    assert audit.score_checks(checks) < 50
    assert names["tls_certificate"]["status"] == "fail"
    assert names["https_enforced"]["status"] == "fail"
    assert names["server_disclosure"]["status"] == "warn"  # leaks version
    assert names["latency"]["status"] == "warn"


def test_unreachable_target():
    checks = audit.evaluate({"reachable": False, "error": "timeout"})
    assert checks == [{"name": "reachability", "status": "fail", "detail": "timeout"}]
    assert audit.score_checks(checks) == 0


def test_expiring_cert_warns():
    f = dict(STRONG, tls={"valid": True, "days_to_expiry": 5, "error": None})
    assert _by_name(audit.evaluate(f))["tls_certificate"]["status"] == "warn"


def test_score_math():
    checks = [{"name": "a", "status": "pass", "detail": ""},
              {"name": "b", "status": "warn", "detail": ""},
              {"name": "c", "status": "fail", "detail": ""}]
    assert audit.score_checks(checks) == round(100 * 1.5 / 3)


def test_report_validates():
    report = audit.build_report("https://x.com", STRONG)
    assert audit.validate_report(report) is True
    assert report["score"] == audit.score_checks(report["checks"])


def test_validate_rejects_malformed():
    assert audit.validate_report({"target": "x"}) is False
    assert audit.validate_report("nope") is False
    bad = audit.build_report("https://x.com", STRONG)
    bad["checks"][0]["status"] = "bogus"
    assert audit.validate_report(bad) is False


def test_markdown_contains_target_and_checks():
    md = audit.report_markdown(audit.build_report("https://x.com", STRONG))
    assert "https://x.com" in md and "tls_certificate" in md


def test_normalize_adds_scheme():
    assert audit._normalize("example.com").startswith("https://")


def test_ipv6_malformed_does_not_crash():
    report = audit.run_audit("https://[::1", timeout=2.0)  # malformed IPv6 literal
    assert audit.validate_report(report)
    assert report["checks"][0]["name"] == "reachability"
    assert report["checks"][0]["status"] == "fail"


def test_evaluate_edge_branches():
    n = _by_name(audit.evaluate(dict(STRONG, tls={"valid": True, "days_to_expiry": None, "error": None})))
    assert n["tls_certificate"]["status"] == "pass"
    n = _by_name(audit.evaluate(dict(STRONG, tls={"valid": True, "days_to_expiry": -1, "error": None})))
    assert n["tls_certificate"]["status"] == "fail"
    n = _by_name(audit.evaluate(dict(STRONG, redirect_http_to_https=None, latency_ms=None)))
    assert n["https_enforced"]["status"] == "warn" and n["latency"]["status"] == "warn"


def _mock_http(monkeypatch):
    import httpx

    def handler(request):
        if request.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://x.test/"})
        return httpx.Response(200, headers={"server": "nginx", "strict-transport-security": "x"})

    real_client = httpx.Client  # capture before patching to avoid recursion

    def fake_client(**kw):
        return real_client(transport=httpx.MockTransport(handler),
                           timeout=kw.get("timeout"), follow_redirects=kw.get("follow_redirects", False))

    monkeypatch.setattr(audit.httpx, "Client", fake_client)


def test_fetch_offline_success(monkeypatch):
    _mock_http(monkeypatch)
    monkeypatch.setattr(audit, "_tls_info", lambda host, **k: {"valid": True, "days_to_expiry": 100, "error": None})
    f = audit.fetch("https://x.test")
    assert f["reachable"] and f["status"] == 200
    assert f["redirect_http_to_https"] is True and f["tls"]["valid"]


def test_fetch_offline_error(monkeypatch):
    import httpx

    class BoomClient:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, *a, **k): raise httpx.ConnectError("boom")

    monkeypatch.setattr(audit.httpx, "Client", BoomClient)
    f = audit.fetch("https://x.test")
    assert f["reachable"] is False and f["error"]


def test_run_audit_offline_full(monkeypatch):
    _mock_http(monkeypatch)
    monkeypatch.setattr(audit, "_tls_info", lambda host, **k: {"valid": True, "days_to_expiry": 100, "error": None})
    report = audit.run_audit("https://x.test")
    assert audit.validate_report(report) and report["score"] >= 80


def test_tls_info_success(monkeypatch):
    class SSock:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def getpeercert(self): return {"notAfter": "Jan 01 00:00:00 2099 GMT"}

    class Ctx:
        def wrap_socket(self, sock, server_hostname=None): return SSock()

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(audit.ssl, "create_default_context", lambda: Ctx())
    monkeypatch.setattr(audit.socket, "create_connection", lambda *a, **k: Conn())
    info = audit._tls_info("x.test")
    assert info["valid"] and info["days_to_expiry"] > 0


def test_tls_info_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(audit.socket, "create_connection", boom)
    info = audit._tls_info("x.test")
    assert info["valid"] is False and info["error"]


@pytest.mark.live
def test_live_audit_real_site():
    try:
        report = audit.run_audit("https://example.com", timeout=8.0)
    except Exception as e:
        pytest.skip(f"network unavailable: {e}")
    if not report["checks"] or report["checks"][0].get("name") == "reachability" \
            and report["checks"][0]["status"] == "fail":
        pytest.skip("target unreachable from this environment")
    assert audit.validate_report(report)
    assert report["target"] == "https://example.com"
