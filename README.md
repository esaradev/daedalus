# daedalus

> The financial control plane for agents that spend money to do paid work.
>
> The moment you let an agent spend, you have no idea if it is profitable.
> daedalus is the missing ledger and spend control.

Built for the Hermes Agent Accelerated Business Hackathon (NVIDIA Nemotron x
Stripe x Nous Research). Standalone-runnable with no keys; ships a Hermes
`SKILL.md` and a NemoClaw `policy.yaml` for the real stack.

## What it does

An agent runs a real service (a website security audit) and keeps its own books:

```
price -> Stripe payment link -> collect -> authorize the input spend
      -> run the audit, summarize on Nemotron -> book double-entry -> reprice
```

Earning is autonomous. Every outbound spend must clear three independent
protections, and the demo shows each one blocking a different bad spend:

1. **egress** (security) — a default-deny allowlist mirroring NemoClaw. Off-list
   host, denied. This is also emitted as a real NemoClaw `policy.yaml`.
2. **credential cap** (rail limit) — a per-vendor cap, the Stripe Projects /
   funded-wallet limit.
3. **economics** (the book) — attended approval (one human tap; the agent cannot
   self-approve) or a standing policy limit, plus a check that the realized
   funds exist.

Then the agent reads its own P&L and reprices: raise while customers keep buying,
cut when they walk.

## The stack, and where each piece is load-bearing

- **NVIDIA Nemotron** (`nvidia/nemotron-3-ultra-550b-a55b:free` on OpenRouter)
  writes the executive summary; the audit checks and score are computed locally
  by `jobs/audit.py`. Sensitive prompts (cards, customer data, the ledger) route
  to a local Nemotron, and a sensitive call is refused rather than sent to the
  cloud when no local endpoint is set. Every structured call is wrapped in
  validate-and-retry, because Nemotron sometimes stops before it emits valid
  output.
- **Stripe** is both sides of the rail: Payment Links + the
  `checkout.session.completed` webhook to earn, and the Link / Projects / MPP
  adapters to spend, each gated by the authorization layer.
- **NemoClaw** is the egress allowlist. daedalus enforces the same default-deny
  shape standalone and emits a `policy.yaml` the real sandbox enforces.
- **Hermes** drives it: `skill/SKILL.md` teaches the agent the discipline.

## Quickstart (no keys, runs the whole loop)

```bash
./run.sh setup          # python 3.12 venv + deps + .env
./run.sh demo           # one paid audit end to end + a blocked spend + the five numbers
./run.sh test           # the full test suite
./run.sh cov            # coverage on the core modules
./run.sh serve          # the live dashboard at http://127.0.0.1:8787
```

`./run.sh demo` runs the real security audit against a live site, prices and
books the job, authorizes one spend and blocks another, prints the five-number
P&L, and reprices. With no keys it labels Stripe and Nemotron as stubs; the
ledger, the gate, and the audit are always real.

## Go live (Stripe test mode + Nemotron)

Fill `.env` (copy from `.env.example`):

```bash
STRIPE_SECRET_KEY=sk_test_...        # https://dashboard.stripe.com/test/apikeys
STRIPE_WEBHOOK_SECRET=whsec_...      # from: stripe listen --forward-to localhost:8787/webhook
OPENROUTER_API_KEY=...               # https://openrouter.ai/keys  (Nemotron Ultra is free)
APPROVAL_MODE=attended               # or: policy (standing limit, no tap)
```

Then the real test-mode loop runs: Payment Links charge real test cards, the
webhook books revenue, the Link adapter creates a real test-mode charge for the
authorized spend, and Nemotron Ultra writes the report. For a local privacy
route, set `LOCAL_NEMOTRON_URL` to an OpenAI-compatible Nemotron endpoint.

## Architecture

```
daedalus/
  config.py         one config + .env loader; PROJECT_NAME is the rename point
  ledger.py         SQLite strict double-entry; every txn sums to zero; live P&L
  spend_control.py  the gate: egress -> credential cap -> economics, in order
  egress.py         default-deny allowlist + NemoClaw policy.yaml emitter
  audit_log.py      append-only record of every spend decision
  pricing.py        quote, fulfillment budget, conversion-aware reprice
  nemotron.py       OpenRouter + local route + validate-and-retry
  jobs/audit.py     the real security-audit workload (read-only, timed)
  stripe_earn.py    payment links + webhook + idempotent booking
  stripe_spend.py   Link / Projects / MPP spend adapters
  orchestrator.py   the full loop
  app.py            FastAPI: webhook + dashboard
  cli.py            demo / audit / pnl / serve
skill/SKILL.md      Hermes skill
deploy/policy.yaml  NemoClaw egress allowlist
integrations/       the original Hermes plugin, preserved
tests/              89 tests; core modules >=90% coverage
```

## What is real vs stubbed

Real: the double-entry ledger, the three-protection gate, the audit (hits real
sites), conversion-aware pricing, the dashboard. With keys: Stripe test-mode
charges and Nemotron Ultra. Stubbed and clearly labelled: the Stripe Link CLI
(needs the mobile app), Stripe Projects provisioning, and MPP chain settlement
(needs a wallet/Tempo). Nothing fakes a result or moves real money.

## License

MIT.
