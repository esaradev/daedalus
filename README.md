# dadaledus

> The financial control plane for Hermes agents.
>
> An agent that spends money is flying blind. This gives it a P&L.

Daedalus built the apparatus that made flight possible. `dadaledus` is the
apparatus that lets a Hermes agent run a business: a double-entry ledger, Stripe
on both sides of the rail, and pricing that tunes itself from the books. Sibling
to the Icarus memory plugins, and it shares the same `~/fabric/` store.

Built for the Hermes Agent Accelerated Business Hackathon (NVIDIA x Stripe x
Nous Research).

## The loop

```
order in
  treasury_intake   price = cost-to-fulfill x markup, send Stripe checkout   [autonomous]
  treasury_collect  customer pays -> book revenue                            [autonomous]
  treasury_fulfill  ONE scoped virtual card for the whole spend
                      -> blocks on a human approval tap in the Link app   <- only human touch
                      -> buy inputs, produce on Nemotron, book the costs
  treasury_pnl      profit on the board
  treasury_evolve   reprice from the book, within hard bounds
```

Earning is fully autonomous. Spending stops at a human tap, by Stripe's design.
The agent **cannot** approve its own spend. That gate is the safety feature, not
a limitation, and the agent batches a whole order's spend into one approval so
the human is interrupted once per order, not once per API call.

## Why three sponsors, load-bearing

- **Nous / Hermes** — the runtime. This is a Hermes plugin, same contract as the
  Icarus family (`register(ctx)`, `register_tool`, `register_hook`).
- **Stripe** — both sides of the ledger. Payment Links to earn, the Link CLI
  with scoped single-use virtual cards to spend, the approval gate for trust.
- **NVIDIA** — Nemotron does the billable reasoning. NemoClaw-style routing keeps
  card numbers, customer PII, and the ledger on a **local** Nemotron and never
  ships them to the cloud. Self-evolving pricing is the pattern from NVIDIA's own
  Hermes + NemoClaw launch.

## Install (as a Hermes plugin)

```bash
git clone https://github.com/esaradev/dadaledus.git
mkdir -p ~/.hermes/plugins/dadaledus
cp -r dadaledus/dadaledus/* ~/.hermes/plugins/dadaledus/
cp -r dadaledus/dadaledus/skill ~/.hermes/skills/dadaledus
```

Start Hermes, `/plugins` should show `dadaledus (7 tools, 2 hooks)`.

## Configure

```bash
# where the books live (defaults to ~/fabric/dadaledus)
export DADALEDUS_DIR=~/fabric/dadaledus

# Stripe — test mode is fine. Without it, runs in a labelled SANDBOX.
export STRIPE_API_KEY=sk_test_...
export STRIPE_LINK_CLI=link-cli          # the @stripe/link-cli binary

# Nemotron — local (sensitive) and cloud (heavy). Without either, sandbox stub.
export NEMOTRON_LOCAL_BASE_URL=http://localhost:8000/v1
export NEMOTRON_CLOUD_BASE_URL=https://integrate.api.nvidia.com/v1
export NEMOTRON_API_KEY=...
```

## See it run, no keys needed

```bash
pip install -e .
dadaledus showcase    # the full story in one run: one order end to end,
                      # then the agent discovering its own price
```

Other commands: `dadaledus demo "<spec>"` (one order), `dadaledus discover`
(the pricing loop), `dadaledus pnl` / `dadaledus orders` (read the book).

Sandbox mode runs the exact same control flow with no money moving and is
clearly labelled at every step. It never claims a real charge happened. Set the
Stripe and Nemotron env vars to run it for real in test mode.

## The books

Append-only, double-entry, on disk. Money is integer cents; postings are never
mutated; P&L is a fold over the file. One markdown file per order, so you can
read the books by scrolling a folder.

```
~/fabric/dadaledus/
├── ledger.jsonl          one immutable posting per line
├── orders/<id>.md        one order each, YAML frontmatter + spec
├── pricing.json          current markup and bounds
└── pricing_snapshots.jsonl
```

## License

MIT.
