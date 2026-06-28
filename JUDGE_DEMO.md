# daedalus — judge demo (run in `hermes chat`)

A Hermes-native plugin. Everything below is the agent calling its own treasury
tools. Real Stripe test-mode money, a real audit, two Nemotron models.

Install (prompts for your OpenRouter + Stripe TEST keys, both optional):
```bash
hermes plugins install esaradev/daedalus/daedalus --enable
~/.hermes/hermes-agent/venv/bin/python -m pip install stripe   # one-time, for real charges
```

Setup:
```bash
rm -rf /tmp/dae-hermes      # clean books
ollama ps                   # show nemotron-mini loaded locally (keep this terminal visible)
hermes chat
```

Paste these one at a time and let the tool calls render.

## 1. The surface and an empty book
> What treasury tools do you have, and what is our current P&L?

Shows the toolset and a $0.00 double-entry book. (`treasury_pnl`)

## 2. The loop, on a real site — and the approval gate
> A customer wants a paid security audit of https://developer.nvidia.com.
> Quote it, collect payment in test mode, then try to fulfill it.

The agent quotes ($5, real Stripe payment link), collects (real test charge),
and on fulfill the gate STOPS it: "needs human approval; the agent cannot
self-approve." It turns to you.

## 3. You approve
> Approved. Fulfill it.

Now it runs the live audit of NVIDIA's site, books the cost, and delivers.
Profit lands on the book, double-entry.

## 4. Two Nemotron models, one local
> Which Nemotron model wrote the public summary, and which wrote the
> confidential financial note?

Public summary ran on cloud Nemotron Ultra. The confidential financial note ran
on a Nemotron on this machine and never left the box (NemoClaw privacy router).
Point at `ollama ps` to show nemotron-mini active.

## 5. Prove the guardrails
> Prove the spend gate works — test the guardrails.

`treasury_test_guardrails` attempts three bad spends; each is blocked by a
different protection: egress (off-allowlist host), credential cap (over the
per-vendor limit), economics (no approval tap). No money moves.

## 6. It remembers its business, across sessions
> What do you remember about past audits and pricing decisions?

`treasury_recall` pulls its own history out of Icarus markdown memory. The brief
at the top of every chat already lists recent decisions — proof it remembers
across sessions, not just within one. Every order, spend decision, audit, and
repricing is written to `~/fabric` as a markdown file with full provenance
(agent, evidence, source tool). Show one: `cat ~/fabric/2026/06/*.md | head`.

To make the cross-session point on camera: deliver one audit, quit `hermes chat`,
start it again — the opening brief recalls the job you just ran.

## 7. It prices per customer, and thinks like a CFO
> A returning customer, "acme", wants another audit of https://developer.nvidia.com.
> Quote it. Then act as our CFO and brief me on the business.

The quote recalls acme's history and applies a loyalty rate — a returning
customer pays less ($5.40 vs the $6.00 list), with the reason stated. Then
`treasury_cfo` has the LOCAL Nemotron reason over the confidential books and
return a strategy memo: most-profitable customer, the vendor cost to watch, and
a pricing recommendation. That financial reasoning never leaves the box.

## 8. It prices itself
> Run two more audits of https://developer.nvidia.com, then reprice from the book.

It runs the jobs and `treasury_evolve` raises the markup, explaining the decision
from its own margin and conversion.

## 9. The books and the audit trail
> Show me the full P&L and the open orders.

`treasury_pnl` + `treasury_open_orders`: revenue, cost, profit, blocked actions,
repriced — off the agent's own ledger, which always balances to zero. Every
spend decision is in the append-only audit log; every step is in Icarus memory.

## Close
> One agent. It earns through Stripe, spends only through a gate it cannot bypass,
> does real work on NVIDIA Nemotron (cloud and local), keeps a real double-entry
> book, and prices itself. It drops into any Hermes agent.

## Proof points to say out loud
- The book balances to exactly zero, every run.
- Real Stripe test charges — show dashboard.stripe.com/test/payments.
- 105 tests; a 25-agent adversarial review found and fixed 15 real bugs.
- Every sponsor is load-bearing: Stripe both rails, two Nemotron models, a
  NemoClaw policy.yaml, and it runs as a Hermes plugin.
