"""Both sides of the rail.

EARN  — create a Stripe Checkout/Payment Link and receive money. No approval
        needed to be paid, so this side runs fully autonomous.
SPEND — the Stripe Link CLI issues a scoped, single-use virtual card, but every
        spend is gated by a human tap in the Link app. The agent CANNOT
        self-approve. We batch a whole order's spend into one approval request
        so the human is interrupted once per order, not once per API call.

Real Stripe is used when STRIPE_API_KEY (test mode sk_test_...) is set and the
Link CLI is on PATH. Otherwise a labelled SANDBOX path runs the same control
flow so the loop is exercisable. Sandbox never claims a real charge happened.
"""

import json
import os
import subprocess
import urllib.parse
import urllib.request

STRIPE_KEY = os.environ.get("STRIPE_API_KEY", "")
LINK_CLI = os.environ.get("STRIPE_LINK_CLI", "link-cli")
SANDBOX = not STRIPE_KEY


def _stripe(path, params):
    data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/" + path,
        data=data,
        headers={"Authorization": f"Bearer {STRIPE_KEY}",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ── EARN ──────────────────────────────────────────────────────────────

def create_payment_link(order_id, amount_cents, description):
    """Return a checkout URL the customer pays. Autonomous, no approval."""
    if SANDBOX:
        return {"sandbox": True, "url": f"https://checkout.test/{order_id}",
                "amount_cents": amount_cents}
    price = _stripe("prices", {
        "currency": "usd",
        "unit_amount": amount_cents,
        "product_data[name]": description[:250],
    })
    link = _stripe("payment_links", {
        "line_items[0][price]": price["id"],
        "line_items[0][quantity]": 1,
        "metadata[order_id]": order_id,
    })
    return {"sandbox": False, "url": link["url"], "id": link["id"], "amount_cents": amount_cents}


def check_paid(order_id, payment_link_id=None):
    """Has this order been paid? In real mode, look for a completed session.

    Production wires a webhook on checkout.session.completed; for the demo we
    poll sessions filtered by the payment link.
    """
    if SANDBOX:
        return True  # sandbox treats the link as paid so the loop proceeds
    if not payment_link_id:
        return False
    sessions = _stripe_get("checkout/sessions", {"payment_link": payment_link_id, "limit": 1})
    data = sessions.get("data", [])
    return bool(data) and data[0].get("payment_status") == "paid"


def _stripe_get(path, params):
    url = "https://api.stripe.com/v1/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {STRIPE_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ── SPEND ─────────────────────────────────────────────────────────────

def request_spend(order_id, amount_cents, vendors, merchant_lock=None):
    """Ask for ONE scoped virtual card covering the whole order's spend.

    Blocks on the human's approval in the Link app. Returns the card handle on
    approval or a denial. The agent has no way to bypass this.
    """
    line = ", ".join(f"{v['name']} {v['cents']/100:.2f}" for v in vendors)
    memo = f"order {order_id}: {line}"
    if SANDBOX:
        return {"sandbox": True, "approved": True, "card": f"vcard_sandbox_{order_id}",
                "amount_cents": amount_cents, "memo": memo,
                "note": "SANDBOX auto-approval — no money moved"}
    cmd = [LINK_CLI, "card", "create",
           "--amount", str(amount_cents),
           "--currency", "usd",
           "--memo", memo,
           "--request-approval"]
    if merchant_lock:
        cmd += ["--merchant", merchant_lock]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"approved": False, "reason": "approval timed out (no human tap)"}
    if out.returncode != 0:
        return {"approved": False, "reason": out.stderr.strip() or "denied"}
    res = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {"raw": out.stdout}
    return {"sandbox": False, "approved": True, "card": res.get("card_id", res.get("raw")),
            "amount_cents": amount_cents, "memo": memo}
