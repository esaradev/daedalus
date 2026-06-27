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
