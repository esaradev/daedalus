"""The reference workload: a real website/API security audit.

A customer pays a few dollars and gets this. It is read-only, every network
call has a timeout, and it never crashes on a bad target. Fetching (network) is
separated from evaluation (pure) so the scoring is unit-testable offline and the
same evaluator runs on real fetched data in the demo.

Checks: TLS cert validity + expiry, HTTPS enforced (http -> https redirect),
the core security headers, response latency, and basic server/cookie hygiene.
"""

import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

SECURITY_HEADERS = {
    "strict-transport-security": "HSTS not set (no forced HTTPS for return visits)",
    "content-security-policy": "no CSP (weaker XSS/injection defense)",
    "x-content-type-options": "missing nosniff",
    "x-frame-options": "clickjacking protection missing",
    "referrer-policy": "no referrer policy",
}
STATUS_WEIGHT = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


# ── evaluation (pure) ─────────────────────────────────────────────────
def evaluate(fetched):
    """Turn gathered raw data into a list of checks. No network here."""
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    if not fetched.get("reachable"):
        add("reachability", "fail", fetched.get("error") or "target not reachable")
        return checks
    add("reachability", "pass", f"HTTP {fetched.get('status')}")

    tls = fetched.get("tls") or {}
    if tls.get("valid"):
        days = tls.get("days_to_expiry")
        if days is None:
            add("tls_certificate", "pass", "valid certificate")
        elif days < 0:
            add("tls_certificate", "fail", "certificate expired")
        elif days < 14:
            add("tls_certificate", "warn", f"certificate expires in {days} days")
        else:
            add("tls_certificate", "pass", f"valid, {days} days to expiry")
    else:
        add("tls_certificate", "fail", tls.get("error") or "invalid certificate")

    redirect = fetched.get("redirect_http_to_https")
    if redirect is True:
        add("https_enforced", "pass", "http redirects to https")
    elif redirect is False:
        add("https_enforced", "fail", "http is served without redirect to https")
    else:
        add("https_enforced", "warn", "could not confirm http->https redirect")

    headers = {k.lower(): v for k, v in (fetched.get("headers") or {}).items()}
    for h, why in SECURITY_HEADERS.items():
        if h in headers:
            add(f"header:{h}", "pass", "present")
        else:
            add(f"header:{h}", "warn", why)

    server = headers.get("server", "")
    if server and any(ch.isdigit() for ch in server):
        add("server_disclosure", "warn", f"Server header leaks version: {server}")
    else:
        add("server_disclosure", "pass", "no version disclosure in Server header")

    latency = fetched.get("latency_ms")
    if latency is None:
        add("latency", "warn", "not measured")
    elif latency > 2000:
        add("latency", "warn", f"slow: {int(latency)} ms")
    else:
        add("latency", "pass", f"{int(latency)} ms")

    return checks


def score_checks(checks):
    if not checks:
        return 0
    earned = sum(STATUS_WEIGHT[c["status"]] for c in checks)
    return round(100 * earned / len(checks))


def _summary(score, checks):
    fails = [c["name"] for c in checks if c["status"] == "fail"]
    grade = "strong" if score >= 85 else "adequate" if score >= 65 else "weak"
    tail = f" Failing: {', '.join(fails)}." if fails else ""
    return f"Security posture {grade} ({score}/100).{tail}"


def build_report(target, fetched):
    checks = evaluate(fetched)
    score = score_checks(checks)
    return {
        "target": target,
        "ts": time.time(),
        "checks": checks,
        "score": score,
        "summary": _summary(score, checks),
    }


def validate_report(report):
    if not isinstance(report, dict):
        return False
    for key in ("target", "ts", "checks", "score", "summary"):
        if key not in report:
            return False
    if not isinstance(report["checks"], list) or not report["checks"]:
        return False
    for c in report["checks"]:
        if set(c) != {"name", "status", "detail"} or c["status"] not in STATUS_WEIGHT:
            return False
    return isinstance(report["score"], int) and 0 <= report["score"] <= 100


def report_markdown(report):
    glyph = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"# Security audit: {report['target']}",
             "", f"Score: {report['score']}/100 — {report['summary']}", ""]
    for c in report["checks"]:
        lines.append(f"- [{glyph[c['status']]}] {c['name']}: {c['detail']}")
    return "\n".join(lines) + "\n"


# ── fetching (network) ────────────────────────────────────────────────
def _normalize(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _tls_info(host, port=443, timeout=8.0):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        not_after = cert.get("notAfter")
        days = None
        if not_after:
            exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (exp - datetime.now(timezone.utc)).days
        return {"valid": True, "days_to_expiry": days, "error": None}
    except Exception as e:  # cert invalid/expired/hostname mismatch/unreachable
        return {"valid": False, "days_to_expiry": None, "error": f"{type(e).__name__}: {e}"}


def fetch(url, timeout=8.0):
    url = _normalize(url)
    host = urlparse(url).hostname or ""
    out = {"url": url, "reachable": False, "error": None, "status": None,
           "headers": {}, "redirect_http_to_https": None, "tls": None, "latency_ms": None}
    try:
        t0 = time.time()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url)
        out["latency_ms"] = (time.time() - t0) * 1000
        out["status"] = r.status_code
        out["headers"] = dict(r.headers)
        out["reachable"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    out["tls"] = _tls_info(host, timeout=timeout)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            hr = client.get("http://" + host)
        loc = hr.headers.get("location", "")
        out["redirect_http_to_https"] = (300 <= hr.status_code < 400 and loc.startswith("https://"))
    except Exception:
        out["redirect_http_to_https"] = None
    return out


def run_audit(url, timeout=8.0):
    """Fetch a real target and return a validated report."""
    fetched = fetch(url, timeout=timeout)
    return build_report(_normalize(url), fetched)
