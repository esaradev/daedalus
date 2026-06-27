"""The full loop, in one place.

  price -> payment link -> collect -> authorize input spend -> run the audit
        -> book -> reprice

Earning is autonomous. The input spend (the model that writes the summary) goes
through the gate: in attended mode the caller supplies the approval token (the
tap), and the agent cannot self-approve. The audit only runs if the spend was
authorized, which is the economics rule made literal: no approved spend, no
fulfillment.

Note: the commissioned audit target is NOT added to the spend allowlist. The
spend gate's egress set stays restricted to money/inference endpoints (Stripe,
OpenRouter). Reaching the target under real NemoClaw is a separate reachability
concern, declared in deploy/policy.yaml, not a spend authorization.
"""

import secrets

from .jobs.audit import run_audit, report_markdown


class Orchestrator:
    def __init__(self, ledger, pricing, spend_control, earn, nemotron,
                 audit_runner=run_audit, cost_estimate_cents=120):
        self.ledger = ledger
        self.pricing = pricing
        self.spend = spend_control
        self.earn = earn
        self.nemotron = nemotron
        self.audit_runner = audit_runner
        self.cost_estimate = cost_estimate_cents
        self.jobs = 0
        self.paid = 0       # customer paid (funded, fulfilled or not)
        self.lost = 0       # customer declined
        self.delivered = 0  # fulfilled

    def _completed_event(self, order_id, amount, ref):
        return {"type": "checkout.session.completed", "data": {"object": {
            "id": f"cs_{order_id}", "payment_intent": ref, "amount_total": amount,
            "metadata": {"order_id": order_id}}}}

    def run_job(self, target_url, customer="customer", approve=None, pay=True):
        self.jobs += 1
        order_id = "o_" + secrets.token_hex(3)

        price = self.pricing.quote(self.cost_estimate)
        link = self.earn.create_payment_link(price, f"Security audit: {target_url}", order_id)
        result = {"order": order_id, "target": target_url, "customer": customer,
                  "price_cents": price, "checkout_url": link["url"], "state": "quoted"}

        if not pay:  # customer declined: a lost deal, feeds the conversion signal
            self.lost += 1
            result["state"] = "lost"
            return result

        if getattr(self.earn, "enabled", False):
            collected = self.earn.charge_test(price, f"Security audit: {target_url}", order_id)
        else:
            ref = link.get("id") or order_id
            collected = self.earn.handle_event(self._completed_event(order_id, price, ref))
        self.paid += 1
        result["revenue_cents"] = price
        result["collect_ref"] = collected.get("ref", "")
        result["state"] = "funded"

        # spend on inputs, capped so the floor margin survives
        spend_amount = min(self.cost_estimate, self.pricing.fulfillment_budget(price))
        vendor, vhost = "openrouter", "openrouter.ai"
        token = approve(vendor, spend_amount) if approve else None
        decision = self.spend.authorize(vendor, vhost, spend_amount, approval_token=token)
        result["spend_decision"] = {"allowed": decision.allowed,
                                    "protection": decision.protection, "reason": decision.reason}
        if not decision.allowed:
            result["state"] = "funded_unfulfilled"
            return result

        report = self.audit_runner(target_url)
        report["ai_summary"] = self._summarize(report)
        self.delivered += 1
        result["report"] = report
        result["report_markdown"] = report_markdown(report)
        result["state"] = "delivered"
        result["pnl"] = self.ledger.pnl()
        return result

    def conversion(self):
        decided = self.paid + self.lost
        return self.paid / decided if decided else None

    def reprice(self):
        return self.pricing.evolve(self.ledger.pnl(), self.conversion())

    def _summarize(self, report):
        findings = "; ".join(f"{c['name']}={c['status']}" for c in report["checks"])
        prompt = (f"Write a two-sentence executive summary of this website security audit. "
                  f"Score {report['score']}/100. Findings: {findings}")
        try:
            return self.nemotron.chat(prompt, sensitive=False)
        except Exception as e:
            return f"[summary unavailable: {e}]"

    def five_numbers(self):
        p = self.ledger.pnl()
        return {
            "revenue_cents": p["revenue_cents"],
            "cost_cents": p["cost_cents"],
            "profit_cents": p["profit_cents"],
            "blocked_actions": self.spend.audit.count_blocked(),
            "repriced": self.pricing.repriced,
        }
