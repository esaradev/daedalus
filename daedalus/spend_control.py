"""The authorization gate. A spend must clear three independent protections,
in order. They fail for different reasons, and the demo shows each one as the
binding constraint:

  1. egress         is this host even allowed to be contacted?      (security)
  2. credential cap is this within the vendor's funded/provider cap? (rail limit)
  3. economics      attended tap or policy limit, and do we have the
                    realized funds to cover it?                      (the book)

Only if all three pass does the spend execute and book COGS to the ledger.
Every decision, allowed or blocked, is written to the audit log.

Attended mode requires an approval token that stands in for the Stripe Link
tap. `mint_approval` represents that external authority (the Link app). In the
real stack the agent genuinely cannot produce it; here it is a labelled
simulation, and the gate only ever *verifies* a token, never mints one itself.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass

from . import config
from .audit_log import AuditLog
from .egress import Egress

_APPROVAL_SECRET = os.urandom(16)  # process-local; represents the Link app key

# Per-vendor credential cap in cents (Stripe Projects defaults to $100/mo/provider).
DEFAULT_CAPS = {
    "openrouter": 10000,
    "stripe-projects": 10000,
    "audit-data": 2000,
}


def mint_approval(vendor, amount_cents, secret=None):
    """The simulated tap. Returns the token the human/app produces on approval."""
    s = secret or _APPROVAL_SECRET
    msg = f"{vendor}:{int(amount_cents)}".encode()
    return hmac.new(s, msg, hashlib.sha256).hexdigest()[:16]


@dataclass
class Decision:
    allowed: bool
    protection: str          # which check decided: egress|credential_cap|economics|ok
    reason: str
    vendor: str
    amount_cents: int
    ref: str = ""
    txn_id: int = 0


class SpendControl:
    def __init__(self, ledger, egress=None, audit_log=None, caps=None,
                 mode=None, policy_limit_cents=None, spender=None, approval_secret=None):
        self.ledger = ledger
        self.egress = egress or Egress()
        self.audit = audit_log or AuditLog()
        self.caps = dict(DEFAULT_CAPS if caps is None else caps)
        self.mode = mode or config.APPROVAL_MODE
        self.policy_limit = (config.POLICY_SPEND_LIMIT_CENTS
                             if policy_limit_cents is None else policy_limit_cents)
        self.spender = spender
        self.approval_secret = approval_secret or _APPROVAL_SECRET

    def _log_and_return(self, d):
        self.audit.record(action="spend", vendor=d.vendor, amount_cents=d.amount_cents,
                          allowed=d.allowed, protection=d.protection, reason=d.reason)
        return d

    def authorize(self, vendor, host, amount_cents, port=443, approval_token=None):
        amount_cents = int(amount_cents)
        if amount_cents <= 0:
            return self._log_and_return(Decision(False, "economics",
                                                 "spend amount must be positive", vendor, amount_cents))

        # 1. egress (security)
        ok, reason = self.egress.check(host, port)
        if not ok:
            return self._log_and_return(Decision(False, "egress", reason, vendor, amount_cents))

        # 2. credential cap (rail-specific)
        cap = self.caps.get(vendor)
        if cap is not None and amount_cents > cap:
            return self._log_and_return(Decision(
                False, "credential_cap",
                f"{vendor} cap is {cap}c, remaining can't cover {amount_cents}c", vendor, amount_cents))

        # 3. economics (the authoritative business check)
        if self.mode == "attended":
            expected = mint_approval(vendor, amount_cents, self.approval_secret)
            if not approval_token or not hmac.compare_digest(approval_token, expected):
                return self._log_and_return(Decision(
                    False, "economics",
                    "attended mode: spend needs a human approval tap; agent cannot self-approve",
                    vendor, amount_cents))
        elif self.mode == "policy":
            if amount_cents > self.policy_limit:
                return self._log_and_return(Decision(
                    False, "economics",
                    f"over the standing policy limit of {self.policy_limit}c", vendor, amount_cents))

        available = self.ledger.pnl()["cash_cents"]
        if amount_cents > available:
            return self._log_and_return(Decision(
                False, "economics",
                f"insufficient realized funds: have {available}c, need {amount_cents}c", vendor, amount_cents))

        # all three cleared -> execute and book
        ref = self.spender(amount_cents, vendor) if self.spender else f"stub:{vendor}"
        txn_id = self.ledger.spend(amount_cents, vendor, ref=ref, memo=vendor)
        if cap is not None:
            self.caps[vendor] = cap - amount_cents
        return self._log_and_return(Decision(True, "ok", "authorized and booked",
                                              vendor, amount_cents, ref=ref, txn_id=txn_id))
