# daedalus demo script (3 minutes)

Record a terminal full-screen, large font, plus one cut to the dashboard.
Run `./run.sh demo` for the loop and `./run.sh serve` for the dashboard.

## 0:00 - 0:25 — the pain

On camera: a terminal at a $0.00 P&L.

"Stripe just gave agents the ability to spend money. The moment you let an agent
spend, you have no idea if it is profitable, or whether it is about to pay
someone it never should. This is daedalus. It gives an agent a P&L and a spend
gate. Watch it run a real business and turn a profit, by itself."

## 0:25 - 1:25 — the loop, once, live

Run `./run.sh demo`. Narrate as it prints:

- "A customer wants a security audit. The agent prices it, cost to fulfill times
  its markup, and sends a Stripe payment link. Earning is autonomous."
- "Paid. Revenue booked, double-entry."
- "To do the work it has to buy the model that writes the report. That spend hits
  the gate. In attended mode it needs a human tap. The agent cannot approve its
  own money. I approve once."
- "Now it runs the real audit, on NVIDIA Nemotron." Point at the live findings:
  TLS, the missing https redirect, the absent security headers, a real score.
- "Profit booked. It earned more than it spent."

## 1:25 - 2:05 — the gate blocks a bad spend

Same run, Act 2 on screen.

"Now the agent tries to pay a data broker that is not on its allowlist. Blocked,
by egress, before any money moves. This is NemoClaw's default-deny policy, and
daedalus emits the exact policy.yaml the sandbox enforces. Three independent
protections: who it can talk to, the per-vendor cap, and the book. A spend has to
clear all three."

## 2:05 - 2:35 — the five numbers

Cut to `./run.sh serve`, the dashboard.

"Revenue, cost, profit, blocked actions, repriced. Live, off the agent's own
double-entry ledger. The book always balances to zero. This is the thing finance
needs before it lets fifty agents touch a card."

## 2:35 - 3:00 — it reprices itself, and the close

Back to the terminal, Act 3.

"It read its own P&L and raised its price, because margins were fat and customers
kept paying. Earn, spend through the gate, book every dollar, reprice. NVIDIA
Nemotron does the work, NemoClaw guards the egress, Stripe moves the money. This
is daedalus. It drops into any Hermes agent. The repo is open."
