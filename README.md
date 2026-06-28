# daedalus

> The financial control plane for Hermes agents that spend money to do paid work.
>
> The moment you let an agent spend, you have no idea if it is profitable.
> daedalus is the missing ledger and spend control.

Built for the Hermes Agent Accelerated Business Hackathon (NVIDIA Nemotron x
Stripe x Nous Research). Hermes is the runtime; Daedalus is the treasury it
uses to quote, collect, spend, fulfill, remember, and reprice.

## What it does

Hermes runs a real service (a website security audit) and keeps its own books:

```
Hermes tool call -> quote -> Stripe Payment Link -> collect
                 -> authorize spend -> live audit -> Nemotron summary
                 -> double-entry ledger -> Icarus markdown memory -> reprice
```

Earning is autonomous. Every outbound spend must clear three independent
protections:

1. **egress** (security) — a default-deny allowlist mirroring NemoClaw. Off-list
   host, denied. This is also emitted as a real NemoClaw `policy.yaml`.
2. **credential cap** (rail limit) — a per-vendor cap, the Stripe Projects /
   funded-wallet limit.
3. **economics** (the book) — attended approval (one human tap; the agent cannot
   self-approve) or a standing policy limit, plus a check that the realized
   funds exist.

Then Hermes reads its own P&L and reprices: raise while customers keep buying,
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
- **Hermes** is the primary runtime. The core package exports `register(ctx)`
  and registers treasury tools (`treasury_intake`, `treasury_collect`,
  `treasury_fulfill`, `treasury_run_paid_audit`, `treasury_pnl`,
  `treasury_evolve`) plus session hooks.
- **Icarus markdown memory** is the provenance layer. When `icarus-memory` is
  installed, Daedalus writes Hermes tool calls, spend decisions, Nemotron route
  decisions, delivered reports, and repricing decisions into `~/fabric`.

## Install into Hermes (one command)

```bash
hermes plugins install esaradev/daedalus/daedalus --enable
```

That clones the repo, installs the `daedalus/` plugin, and prompts you for two
keys (both optional — skip either and that side runs as a labelled stub):

- `OPENROUTER_API_KEY` — for NVIDIA Nemotron (Nemotron 3 Ultra is free). https://openrouter.ai/keys
- `STRIPE_SECRET_KEY` — a Stripe TEST-MODE key, `sk_test_...`. https://dashboard.stripe.com/test/apikeys

The plugin needs the `stripe` Python package in the Hermes runtime. `httpx` ships
with Hermes; `stripe` may not, so install it once (skip only if you're staying in
stub mode):

```bash
~/.hermes/hermes-agent/venv/bin/python -m pip install stripe
```

Verify, then drive it from a chat:

```bash
hermes tools list | grep treasury     # 12 treasury_* tools
hermes chat
```

> Run a paid security audit of https://developer.nvidia.com for a customer.
> Quote it, collect payment in test mode, then fulfill it after I approve the spend.

See `JUDGE_DEMO.md` for the full walkthrough.

### Optional: local Nemotron (the privacy split)

Confidential financial reasoning routes to a Nemotron on your own machine and
never leaves the box. To enable, run any OpenAI-compatible Nemotron locally and
point at it:

```bash
ollama pull nemotron-mini
# in ~/.hermes/.env:
#   LOCAL_NEMOTRON_URL=http://localhost:11434/v1
#   LOCAL_NEMOTRON_MODEL=nemotron-mini
```

Without it, sensitive calls fail closed (refused), never sent to the cloud.

### Optional: Icarus markdown memory (provenance + recall)

```bash
~/.hermes/hermes-agent/venv/bin/python -m pip install \
  "icarus-memory @ git+https://github.com/esaradev/icarus-memory-infra.git@main"
```

Without it, the business runs fine; it just skips writing provenance to `~/fabric`.

## Run standalone (no Hermes needed)

For local judging without a Hermes shell, everything runs from the repo:

```bash
./run.sh setup                              # venv + deps + .env
./run.sh demo                               # full loop end to end, labels stub vs real
./run.sh job https://developer.nvidia.com   # one real product flow
./run.sh pnl                                # the five numbers from the book
```

## Developer quickstart

```bash
./run.sh setup          # python 3.12 venv + deps + .env
./run.sh job <url>      # one paid audit through quote/collect/spend/audit/reprice
./run.sh demo           # scripted sponsor-story run, including three blocked spends
./run.sh test           # the full test suite
./run.sh cov            # coverage on the core modules
```

`./run.sh job` is the non-demo path: it creates a persistent order, creates or
stubs a Stripe Payment Link, books collection, runs the spend gate, audits the
target, asks Nemotron for the customer summary, writes memory if available, and
reprices from the book.

## Go live (Stripe test mode + Nemotron)

Fill `.env` (copy from `.env.example`):

```bash
STRIPE_SECRET_KEY=sk_test_...        # https://dashboard.stripe.com/test/apikeys
OPENROUTER_API_KEY=...               # https://openrouter.ai/keys  (Nemotron Ultra is free)
APPROVAL_MODE=attended               # or: policy (standing limit, no tap)
DAEDALUS_MEMORY_ENABLED=auto          # auto|true|false
DAEDALUS_MEMORY_ROOT=~/fabric         # Icarus markdown memory root
```

Then the real test-mode loop runs: `treasury_collect`/`treasury_run_paid_audit`
create a real test-mode charge for the customer payment, the Link adapter creates
a real test-mode charge for the authorized spend, and Nemotron Ultra writes the
summary. Collection is driven by the agent's tools, so no webhook server is
needed; the `stripe_earn` webhook handler stays available if you wire your own
endpoint. For a local privacy route, set `LOCAL_NEMOTRON_URL` to an
OpenAI-compatible Nemotron endpoint.

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
  orders.py         persistent order state for split Hermes tool calls
  memory.py         optional Icarus markdown-memory provenance
  jobs/audit.py     the real security-audit workload (read-only, timed)
  stripe_earn.py    payment links + webhook + idempotent booking
  stripe_spend.py   Link / Projects / MPP spend adapters
  orchestrator.py   resumable quote/collect/fulfill/job workflow
  hermes.py         Hermes register(ctx), treasury tools, schemas, hooks
  cli.py            job / demo / audit / pnl
skill/SKILL.md      Hermes skill
deploy/policy.yaml  NemoClaw egress allowlist
integrations/       compatibility shim for older Hermes plugin installs
tests/              full unit/integration suite; core modules >=90% coverage
```

## What is real vs stubbed

Real: the double-entry ledger, the three-protection gate, the audit (hits real
sites), conversion-aware pricing. With keys: Stripe test-mode charges and
Nemotron Ultra. Stubbed and clearly labelled: the Stripe Link CLI
(needs the mobile app), Stripe Projects provisioning, and MPP chain settlement
(needs a wallet/Tempo). Nothing fakes a result or moves real money.

## License

MIT.
