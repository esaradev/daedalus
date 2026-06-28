"""Protection-free side of the rail: earning. Stripe Checkout / Payment Links
in TEST MODE, the checkout.session.completed webhook, and a polling fallback.

Receiving money needs no approval, so this runs fully autonomously. Booking is
idempotent: a webhook delivered twice books revenue once, keyed on the Stripe
session/payment id.

Without a key it runs a labelled stub so the loop is exercisable offline.
"""

import secrets

from . import config

try:
    import stripe
except ModuleNotFoundError:  # the plugin still loads; Stripe paths run as stubs
    stripe = None


class StripeEarn:
    def __init__(self, ledger, api_key=None, webhook_secret=None):
        self.ledger = ledger
        self.api_key = api_key if api_key is not None else config.STRIPE_SECRET_KEY
        self.webhook_secret = webhook_secret if webhook_secret is not None else config.STRIPE_WEBHOOK_SECRET
        self.enabled = bool(self.api_key) and stripe is not None
        if self.enabled:
            stripe.api_key = self.api_key

    def create_payment_link(self, amount_cents, description, order_id=""):
        if not self.enabled:
            return {"stub": True, "id": "plink_" + secrets.token_hex(4),
                    "url": f"https://checkout.test/{order_id or secrets.token_hex(3)}",
                    "amount_cents": amount_cents}
        price = stripe.Price.create(
            currency="usd", unit_amount=amount_cents,
            product_data={"name": description[:250]})
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={"order_id": order_id})
        return {"stub": False, "id": link.id, "url": link.url, "amount_cents": amount_cents}

    def charge_test(self, amount_cents, description, order_id=""):
        """Autonomous collect for the live demo: a real Stripe TEST-MODE charge
        standing in for the customer paying the link, booked idempotently. The
        production path is the Payment Link + webhook (handle_event)."""
        if not self.enabled:
            ref = "pi_stub_" + secrets.token_hex(4)
            self.ledger.earn(int(amount_cents), ref=ref, memo=f"stub charge {order_id}")
            return {"stub": True, "ref": ref, "booked_cents": int(amount_cents)}
        pi = stripe.PaymentIntent.create(
            amount=int(amount_cents), currency="usd",
            payment_method="pm_card_visa", confirm=True, off_session=True,
            description=description[:200], metadata={"order_id": order_id})
        ref = pi.id
        if self.ledger.has_ref(ref):
            return {"already_booked": True, "ref": ref}
        self.ledger.earn(int(amount_cents), ref=ref, memo=f"stripe charge {order_id}")
        return {"booked_cents": int(amount_cents), "ref": ref, "status": pi.status}

    def verify_webhook(self, payload, sig_header):
        """Verify the Stripe signature and return the event. Raises on tamper."""
        return stripe.Webhook.construct_event(payload, sig_header, self.webhook_secret)

    def handle_event(self, event):
        """Book revenue on a completed checkout. Idempotent. Returns a result dict."""
        etype = event["type"] if isinstance(event, dict) else event.type
        if etype != "checkout.session.completed":
            return {"ignored": etype}
        session = event["data"]["object"]
        ref = session.get("payment_intent") or session.get("id") or ""
        amount = session.get("amount_total")
        order_id = (session.get("metadata") or {}).get("order_id", "")
        if amount is None:
            return {"error": "session has no amount_total"}
        if not ref:
            return {"error": "session has no payment_intent/id; refusing to book without an idempotency ref"}
        if self.ledger.has_ref(ref):
            return {"already_booked": True, "ref": ref}
        self.ledger.earn(int(amount), ref=ref, memo=f"stripe checkout {order_id}")
        return {"booked_cents": int(amount), "ref": ref, "order_id": order_id}

    def poll_paid(self, payment_link_id):
        """Fallback when no webhook listener: has any session for this link been paid?"""
        if not self.enabled:
            return False
        sessions = stripe.checkout.Session.list(payment_link=payment_link_id, limit=1)
        data = sessions.get("data", [])
        return bool(data) and data[0].get("payment_status") == "paid"
