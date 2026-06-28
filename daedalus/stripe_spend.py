"""Spend adapters. The gate authorizes; these execute. Each is a callable
`spender(amount_cents, vendor) -> ref` matching the three real Stripe spend
rails:

  LinkSpender     attended virtual card. The Link CLI needs the mobile app + US,
                  so the real path here is a genuine Stripe TEST-MODE charge that
                  stands in for the card and yields a real, bookable charge id.
  ProjectsSpender provisions SaaS via Stripe Projects (per-provider cap enforced
                  at the gate). The Projects CLI isn't runnable headless; stubbed.
  MPPSpender      unattended 402 pay-and-retry against a pre-funded wallet. No tap
                  when funded; real settlement needs a wallet/Tempo, so stubbed,
                  with the funded balance acting as the hard cap.

Without a key every adapter returns a clearly-labelled stub ref.
"""

import secrets

from . import config

try:
    import stripe
except ModuleNotFoundError:  # the plugin still loads; Stripe paths run as stubs
    stripe = None


def _stub(prefix):
    return f"{prefix}_{secrets.token_hex(4)}"


class LinkSpender:
    rail = "stripe-link"

    def __init__(self, api_key=None):
        self.api_key = api_key if api_key is not None else config.STRIPE_SECRET_KEY
        self.enabled = bool(self.api_key) and stripe is not None
        if self.enabled:
            stripe.api_key = self.api_key

    def __call__(self, amount_cents, vendor):
        if not self.enabled:
            return _stub("vcard_stub")
        # real Stripe TEST-MODE charge standing in for the Link virtual card
        pi = stripe.PaymentIntent.create(
            amount=int(amount_cents), currency="usd",
            payment_method="pm_card_visa", confirm=True, off_session=True,
            description=f"{config.PROJECT_NAME} spend: {vendor}")
        return pi.id


class ProjectsSpender:
    rail = "stripe-projects"

    def __init__(self, api_key=None):
        self.api_key = api_key if api_key is not None else config.STRIPE_SECRET_KEY

    def __call__(self, amount_cents, vendor):
        return _stub("proj")  # Projects CLI not runnable headless; labelled stub


class MPPSpender:
    rail = "mpp-x402"

    def __init__(self, wallet_balance_cents=0):
        self.wallet = int(wallet_balance_cents)

    def __call__(self, amount_cents, vendor):
        if amount_cents > self.wallet:
            raise RuntimeError(f"MPP wallet underfunded: {self.wallet}c < {amount_cents}c")
        self.wallet -= int(amount_cents)
        return _stub("x402")


def get_spender(rail="link", **kw):
    rails = {"link": LinkSpender, "projects": ProjectsSpender, "mpp": MPPSpender}
    if rail not in rails:
        raise ValueError(f"unknown spend rail '{rail}', choose from {list(rails)}")
    return rails[rail](**kw)
