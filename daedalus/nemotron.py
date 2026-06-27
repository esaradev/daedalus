"""Nemotron reasoning, routed NemoClaw-style.

Two endpoints, picked per call by data sensitivity:
  local  — Nemotron Nano on your box. Anything touching money, cards, customer
           PII, or the ledger routes here and never leaves your infrastructure.
  cloud  — hosted Nemotron Ultra (NIM). Heavy non-sensitive reasoning, e.g.
           writing the deliverable.

This mirrors NemoClaw's Privacy Router. With no endpoints configured it runs a
deterministic SANDBOX stub so the loop is exercisable offline. The stub is
clearly labelled; it never pretends to be a live model.
"""

import json
import os
import re
import urllib.request

LOCAL_BASE = os.environ.get("NEMOTRON_LOCAL_BASE_URL", os.environ.get("NEMOTRON_BASE_URL", ""))
CLOUD_BASE = os.environ.get("NEMOTRON_CLOUD_BASE_URL", "")
LOCAL_MODEL = os.environ.get("NEMOTRON_LOCAL_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16")
CLOUD_MODEL = os.environ.get("NEMOTRON_CLOUD_MODEL", "nvidia/nemotron-3-ultra")
API_KEY = os.environ.get("NEMOTRON_API_KEY", "x")

SENSITIVE = re.compile(
    r"(?i)\b(card|cvc|ssn|invoice|payment|ledger|customer email|account number|"
    r"routing|balance|\$\d|spend|refund|charge)\b"
)


def route(text):
    """Return ('local'|'cloud', base_url, model). Sensitive -> local, always."""
    if SENSITIVE.search(text or ""):
        return "local", LOCAL_BASE, LOCAL_MODEL
    return "cloud", CLOUD_BASE or LOCAL_BASE, CLOUD_MODEL if CLOUD_BASE else LOCAL_MODEL


def _chat(base_url, model, messages, max_tokens=700):
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


def estimate_cost(spec):
    """Estimate cost-to-fulfill in cents. Routes local: it reasons over pricing."""
    lane, base, model = route("spend invoice ledger " + spec)
    if not base:
        return _sandbox_cost(spec), lane
    prompt = (
        "You price the cost to fulfill an agent service order. Reply with ONLY a JSON "
        'object {"cost_cents": int, "vendors": [{"name": str, "cents": int}]}. '
        "Cost is the real third-party spend to deliver (paid APIs, datasets, model "
        f"tokens). Order spec:\n{spec}"
    )
    raw = _chat(base, model, [{"role": "user", "content": prompt}], max_tokens=300)
    m = re.search(r"\{.*\}", raw, re.S)
    obj = json.loads(m.group(0)) if m else {"cost_cents": _sandbox_cost(spec), "vendors": []}
    return obj, lane


def fulfill(spec):
    """Produce the deliverable. Non-sensitive -> cloud Ultra."""
    lane, base, model = route(spec)
    if not base:
        return _sandbox_fulfill(spec), lane
    prompt = f"Produce the deliverable for this order. Be concrete and complete.\n\n{spec}"
    return _chat(base, model, [{"role": "user", "content": prompt}], max_tokens=1500), lane


# ── sandbox stubs (clearly labelled, offline only) ────────────────────

def _sandbox_cost(spec):
    base = 180 + 6 * min(len(spec), 400)
    return base


def _sandbox_fulfill(spec):
    return f"[SANDBOX deliverable — no Nemotron endpoint configured]\n\nRe: {spec}\n\n" \
           "1. Findings ...\n2. Analysis ...\n3. Recommendation ..."
