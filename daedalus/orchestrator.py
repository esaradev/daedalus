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

import json

from . import config
from .jobs.audit import run_audit, report_markdown
from .orders import OrderStore
from .spend_control import mint_approval


class Orchestrator:
    def __init__(self, ledger, pricing, spend_control, earn, nemotron,
                 audit_runner=run_audit, cost_estimate_cents=150,
                 order_store=None, memory=None):
        self.ledger = ledger
        self.pricing = pricing
        self.spend = spend_control
        self.earn = earn
        self.nemotron = nemotron
        self.audit_runner = audit_runner
        self.cost_estimate = cost_estimate_cents
        self.orders = order_store or OrderStore.in_memory()
        self.memory = memory
        self.jobs = 0
        self.paid = 0       # customer paid (funded, fulfilled or not)
        self.lost = 0       # customer declined
        self.delivered = 0  # fulfilled

    def _new_order_id(self):
        import secrets

        return "o_" + secrets.token_hex(3)

    def _completed_event(self, order_id, amount, ref):
        return {"type": "checkout.session.completed", "data": {"object": {
            "id": f"cs_{order_id}", "payment_intent": ref, "amount_total": amount,
            "metadata": {"order_id": order_id}}}}

    def _remember(self, order_id, kind, summary, body="", source_tool="daedalus", evidence=None):
        if not self.memory:
            return {"enabled": False, "error": "memory recorder not configured"}
        ref = self.memory.record(kind=kind, summary=summary, body=body,
                                 source_tool=source_tool, order_id=order_id,
                                 evidence=evidence)
        if ref.get("id"):
            self.orders.append_memory_ref(order_id, ref)
        elif ref.get("error"):
            self.orders.append_warning(order_id, f"memory: {ref['error']}")
        return ref

    def _customer_rate(self, customer):
        """Price from the customer's recalled history. Returns (multiplier, reason)."""
        paid = lost = 0
        for o in self.orders.all(500):
            if o.get("customer") != customer:
                continue
            if o.get("state") in ("funded", "fulfilling", "funded_unfulfilled", "delivered"):
                paid += 1
            elif o.get("state") == "lost":
                lost += 1
        if paid >= 2 and lost == 0:
            return 0.9, f"returning customer, {paid} prior paid audits — 10% loyalty rate"
        if lost > paid:
            return 1.0, f"customer walked on {lost} prior quote(s) — standard rate, no discount"
        return 1.0, "new customer — standard rate"

    def quote_order(self, target_url, customer="customer", source_tool="treasury_intake"):
        self.jobs += 1
        order_id = self._new_order_id()
        list_price = self.pricing.quote(self.cost_estimate)
        rate, rate_reason = self._customer_rate(customer)
        price = max(int(round(list_price * rate)), self.pricing.cfg.get("min_price_cents", 500))
        link = self.earn.create_payment_link(price, f"Security audit: {target_url}", order_id)
        order = self.orders.create({
            "id": order_id,
            "target": target_url,
            "customer": customer,
            "state": "quoted",
            "price_cents": price,
            "list_price_cents": list_price,
            "pricing_note": rate_reason,
            "est_cost_cents": self.cost_estimate,
            "checkout_url": link["url"],
            "payment_link_id": link.get("id", ""),
            "stripe_stub": bool(link.get("stub", False)),
            "source": "hermes",
        })
        self.orders.append_event(order_id, "quote", f"quoted paid audit ({rate_reason})",
                                 price_cents=price, list_price_cents=list_price,
                                 pricing_note=rate_reason, checkout_url=link["url"])
        memory = self._remember(
            order_id,
            "tool-call",
            f"Hermes quoted paid audit {order_id}",
            {"target": target_url, "customer": customer, "price_cents": price,
             "checkout_url": link["url"]},
            source_tool=source_tool,
        )
        order = self.orders.read(order_id)
        return {**order, "memory": memory}

    def collect_order(self, order_id, test_collect=False, source_tool="treasury_collect"):
        order = self.orders.read(order_id)
        if not order:
            return {"error": f"unknown order {order_id}"}
        if order.get("state") in ("funded", "fulfilling", "funded_unfulfilled", "delivered", "blocked"):
            return {**order, "already": True}
        if order.get("state") == "lost":
            return {**order, "paid": False}

        price = int(order["price_cents"])
        if getattr(self.earn, "enabled", False):
            if test_collect:
                collected = self.earn.charge_test(price, f"Security audit: {order['target']}", order_id)
            else:
                paid = self.earn.poll_paid(order.get("payment_link_id", ""))
                if not paid:
                    self.orders.append_event(order_id, "collect", "checkout not paid yet")
                    return {**self.orders.read(order_id), "paid": False}
                collected = self.earn.handle_event(
                    self._completed_event(order_id, price, order.get("payment_link_id") or order_id)
                )
        else:
            ref = order.get("payment_link_id") or order_id
            collected = self.earn.handle_event(self._completed_event(order_id, price, ref))

        if "error" in collected:
            self.orders.append_event(order_id, "collect_error", collected["error"])
            return {**self.orders.read(order_id), "error": collected["error"]}
        self.paid += 1
        order = self.orders.update(order_id, state="funded",
                                   revenue_cents=price,
                                   collect_ref=collected.get("ref", ""))
        self.orders.append_event(order_id, "collect", "customer payment collected",
                                 revenue_cents=price, ref=collected.get("ref", ""))
        memory = self._remember(
            order_id,
            "tool-call",
            f"Hermes collected payment for {order_id}",
            {"target": order["target"], "revenue_cents": price, "stripe": collected},
            source_tool=source_tool,
        )
        order = self.orders.read(order_id)
        return {**order, "paid": True, "collection": collected, "memory": memory}

    def abandon_order(self, order_id, reason="customer declined", source_tool="treasury_abandon"):
        order = self.orders.read(order_id)
        if not order:
            return {"error": f"unknown order {order_id}"}
        if order.get("state") != "quoted":
            return {"error": f"order {order_id} is '{order.get('state')}', only quoted orders can be lost"}
        self.lost += 1
        order = self.orders.update(order_id, state="lost", lost_reason=reason)
        self.orders.append_event(order_id, "lost", "customer did not pay", reason=reason)
        memory = self._remember(order_id, "decision", f"Order {order_id} lost",
                                {"reason": reason, "target": order["target"]},
                                source_tool=source_tool)
        order = self.orders.read(order_id)
        return {**order, "memory": memory}

    def fulfill_order(self, order_id, approve=None, source_tool="treasury_fulfill"):
        order = self.orders.read(order_id)
        if not order:
            return {"error": f"unknown order {order_id}"}
        if order.get("state") == "delivered":
            return {**order, "already": True}
        if order.get("state") not in ("funded", "fulfilling", "funded_unfulfilled",
                                      "blocked", "awaiting_approval"):
            return {"error": f"order {order_id} is '{order.get('state')}', not funded"}

        price = int(order["price_cents"])
        spend_amount = min(int(order.get("est_cost_cents", self.cost_estimate)),
                           self.pricing.fulfillment_budget(price))
        vendor, vhost = "openrouter", "openrouter.ai"

        # Approval resolution. The out-of-band gate: when no explicit approver is
        # passed (the Hermes tool path always passes none), the spend proceeds ONLY
        # if a human set the approval flag via `daedalus approve <order>`. No
        # treasury tool can set that flag, so the agent cannot self-approve.
        if approve is None:
            if order.get("human_approved"):
                approve = mint_approval
            else:
                self.orders.update(order_id, state="awaiting_approval")
                self.orders.append_event(order_id, "approval",
                                         "awaiting human approval before spend")
                msg = (f"Spend of ${spend_amount/100:.2f} needs human approval. A human must run "
                       f"this in a terminal, then call treasury_fulfill again:\n"
                       f"    DAEDALUS_DIR={config.DATA_DIR} daedalus approve {order_id}\n"
                       f"The agent cannot approve its own spend.")
                return {**self.orders.read(order_id), "state": "awaiting_approval",
                        "awaiting_approval": True, "message": msg}

        self.orders.update(order_id, state="fulfilling")
        token = approve(vendor, spend_amount) if approve else None
        decision = self.spend.authorize(vendor, vhost, spend_amount, approval_token=token)
        decision_payload = {"allowed": decision.allowed, "protection": decision.protection,
                            "reason": decision.reason, "vendor": vendor,
                            "amount_cents": spend_amount, "ref": decision.ref,
                            "txn_id": decision.txn_id}
        self.orders.append_event(order_id, "spend", decision.reason, **decision_payload)
        self._remember(order_id, "tool-call", f"Hermes requested spend for {order_id}",
                       decision_payload, source_tool=source_tool)
        if not decision.allowed:
            state = "funded_unfulfilled" if decision.protection == "economics" else "blocked"
            self.orders.update(order_id, state=state, spend_decision=decision_payload)
            return {**self.orders.read(order_id), "spend_decision": decision_payload}

        report = self.audit_runner(order["target"])
        report["ai_summary"] = self._summarize(report)               # public -> cloud Ultra
        summary_route = getattr(self.nemotron, "last_route", None)
        fin_note, fin_route = self._financial_note(report["score"])  # sensitive -> local Nemotron
        self.delivered += 1
        order = self.orders.update(order_id, state="delivered",
                                   spend_decision=decision_payload,
                                   report=report,
                                   report_markdown=report_markdown(report),
                                   nemotron_route=summary_route,
                                   financial_note=fin_note,
                                   financial_note_route=fin_route,
                                   pnl=self.ledger.pnl())
        self.orders.append_event(order_id, "audit", "live audit completed",
                                 score=report["score"], summary=report["summary"])
        self.orders.append_event(order_id, "nemotron", "public summary on cloud Nemotron",
                                 route=summary_route, summary=report["ai_summary"])
        self.orders.append_event(order_id, "nemotron", "sensitive financial note on local Nemotron",
                                 route=fin_route, note=fin_note)
        memory = self._remember(
            order_id,
            "session",
            f"Delivered paid audit {order_id}",
            {"target": order["target"], "score": report["score"],
             "summary": report["summary"], "ai_summary": report["ai_summary"],
             "nemotron_route": summary_route, "financial_note_route": fin_route,
             "pnl": self.ledger.pnl()},
            source_tool=source_tool,
            evidence=[{"kind": "tool_output", "ref": order_id}],
        )
        order = self.orders.read(order_id)
        return {**order, "memory": memory}

    def run_paid_audit(self, target_url, customer="customer", approve=None, pay=True,
                       test_collect=True, evolve=True, source_tool="treasury_run_paid_audit"):
        timeline = []
        quoted = self.quote_order(target_url, customer=customer, source_tool=source_tool)
        timeline.append({"step": "quote", "state": quoted.get("state"), "order": quoted.get("id")})
        if not pay:
            lost = self.abandon_order(quoted["id"], "customer declined", source_tool=source_tool)
            timeline.append({"step": "lost", "state": lost.get("state")})
            return {**lost, "timeline": timeline}
        collected = self.collect_order(quoted["id"], test_collect=test_collect, source_tool=source_tool)
        timeline.append({"step": "collect", "state": collected.get("state"),
                         "paid": collected.get("paid", False)})
        if not collected.get("paid", True) and collected.get("state") != "funded":
            return {**collected, "timeline": timeline}
        fulfilled = self.fulfill_order(quoted["id"], approve=approve, source_tool=source_tool)
        timeline.append({"step": "fulfill", "state": fulfilled.get("state"),
                         "spend": fulfilled.get("spend_decision", {})})
        if evolve and fulfilled.get("state") == "delivered":
            repriced = self.reprice()
            self.orders.append_event(quoted["id"], "reprice", repriced.get("reason", "repriced"), **repriced)
            self._remember(quoted["id"], "decision", f"Pricing decision after {quoted['id']}",
                           repriced, source_tool=source_tool)
            fulfilled = self.orders.update(quoted["id"], repricing=repriced) or fulfilled
            timeline.append({"step": "reprice", "changed": repriced.get("changed"),
                             "reason": repriced.get("reason")})
        elif evolve:
            timeline.append({"step": "reprice", "changed": False,
                             "reason": "skipped until order is delivered"})
        merged = {**(self.orders.read(quoted["id"]) or fulfilled), "timeline": timeline}
        if fulfilled.get("awaiting_approval"):  # keep the transient approval prompt
            merged["awaiting_approval"] = True
            merged["message"] = fulfilled.get("message", "")
        return merged

    def run_job(self, target_url, customer="customer", approve=None, pay=True):
        result = self.run_paid_audit(target_url, customer=customer, approve=approve, pay=pay,
                                     test_collect=True, evolve=False, source_tool="cli_job")
        if "id" in result:
            result["order"] = result["id"]
        return result

    def conversion(self):
        persisted = self.orders.conversion()
        if persisted is not None:
            return persisted
        decided = self.paid + self.lost
        return self.paid / decided if decided else None

    def reprice(self):
        return self.pricing.evolve(self.ledger.pnl(), self.conversion())

    def demo_guardrails(self):
        """Attempt three bad spends and show each protection block a different one.
        For demonstrating the governance live. None of these book money."""
        from .spend_control import mint_approval
        cases = [
            ("security (egress)", "data-broker", "scrape.shady.net", 300, mint_approval("data-broker", 300)),
            ("credential cap", "openrouter", "openrouter.ai", 50000, mint_approval("openrouter", 50000)),
            ("economics (no approval tap)", "openrouter", "openrouter.ai", 100, None),
        ]
        checks = []
        for label, vendor, host, amount, token in cases:
            d = self.spend.authorize(vendor, host, amount, approval_token=token)
            checks.append({"case": label, "vendor": vendor, "host": host,
                           "amount_cents": amount, "allowed": d.allowed,
                           "protection": d.protection, "reason": d.reason})
        return {"guardrails": checks, "all_blocked": all(not c["allowed"] for c in checks)}

    def cfo_brief(self):
        """Reason over the books with the LOCAL Nemotron (financials are sensitive,
        so the privacy router keeps them on the box). Returns a strategy memo plus
        per-customer and per-vendor profitability."""
        p = self.ledger.pnl()
        by_customer = {}
        for o in self.orders.all(500):
            if o.get("state") != "delivered":
                continue
            agg = by_customer.setdefault(o.get("customer", "?"),
                                         {"orders": 0, "revenue_cents": 0, "cost_cents": 0})
            agg["orders"] += 1
            agg["revenue_cents"] += int(o.get("price_cents", 0))
            agg["cost_cents"] += int(o.get("est_cost_cents", 0))
        for a in by_customer.values():
            a["profit_cents"] = a["revenue_cents"] - a["cost_cents"]
        financials = {"pnl": p, "markup": self.pricing.markup,
                      "by_customer": by_customer, "by_vendor": self.ledger.cogs_by_vendor()}
        prompt = ("You are the CFO of an autonomous website-audit business. These numbers are "
                  "confidential. In three short bullets: the most profitable customer, the vendor "
                  "cost to watch, and whether to change pricing (current markup "
                  f"{self.pricing.markup}x). Financials: {json.dumps(financials, default=str)}")
        try:
            memo = self.nemotron.chat(prompt, sensitive=True).strip()
            route = getattr(self.nemotron, "last_route", None)
        except Exception as e:
            memo, route = f"[memo unavailable: {e}]", None
        if self.memory:
            self.memory.record(kind="decision", summary="CFO financial brief",
                               body={"financials": financials, "memo": memo},
                               source_tool="treasury_cfo")
        return {"financials": financials, "memo": memo, "memo_route": route}

    def _summarize(self, report):
        findings = "; ".join(f"{c['name']}={c['status']}" for c in report["checks"])
        prompt = (f"Write a two-sentence executive summary of this website security audit. "
                  f"Score {report['score']}/100. Findings: {findings}")
        try:
            return self.nemotron.chat(prompt, sensitive=False)
        except Exception as e:
            return f"[summary unavailable: {e}]"

    def _financial_note(self, score):
        """Confidential margin note. Touches the ledger, so it routes to the LOCAL
        Nemotron (NemoClaw privacy router) and never leaves the box. Returns
        (text, route). Fails closed: with no local endpoint, the call is refused."""
        p = self.ledger.pnl()
        prompt = (f"Confidential internal finance note. Revenue {p['revenue_cents']}c, "
                  f"cost {p['cost_cents']}c, profit {p['profit_cents']}c, margin {p['margin_pct']}%, "
                  f"audit score {score}/100. In one short sentence, is this job worth repeating?")
        try:
            text = self.nemotron.chat(prompt, sensitive=True)
            return text.strip(), getattr(self.nemotron, "last_route", None)
        except Exception as e:
            # fail-closed: nothing was sent anywhere. Do NOT label it "cloud"
            # (last_route is the attempted route); record it as refused.
            return f"[local note skipped: {e}]", "refused"

    def five_numbers(self):
        p = self.ledger.pnl()
        return {
            "revenue_cents": p["revenue_cents"],
            "cost_cents": p["cost_cents"],
            "profit_cents": p["profit_cents"],
            "blocked_actions": self.spend.audit.count_blocked(),
            "repriced": self.pricing.repriced,
        }
