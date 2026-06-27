"""The spine. An append-only, double-entry ledger on disk.

Money is integer cents. Postings are never mutated. P&L is a fold over the
postings file. Orders are one markdown file each so a human (or a judge) can
read the books by scrolling a folder; structured fulfillment plans live in a
sidecar JSON so the order file stays readable.

  ~/fabric/daedalus/
  ├── ledger.jsonl              one immutable posting per line
  └── orders/<id>.md            one order, YAML frontmatter + spec
      orders/<id>.plan.json     the priced fulfillment plan (cost + vendors)

A posting is a signed movement against an account:
  revenue        money the agent earned   (+)
  cogs:<vendor>  money the agent spent     (-)
  fees:stripe    payment fees              (-)
"""

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(
    os.environ.get("DAEDALUS_DIR")
    or (Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric")) / "daedalus")
)
LEDGER = STORE / "ledger.jsonl"
ORDERS = STORE / "orders"

ORDER_STATES = ("quoted", "funded", "fulfilling", "delivered", "lost")
RESERVED_FIELDS = ("id", "spec")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure():
    ORDERS.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        LEDGER.touch()


def new_id(prefix):
    return f"{prefix}_{secrets.token_hex(4)}"


# ── postings ──────────────────────────────────────────────────────────

def post(account, amount_cents, order=None, ref="", memo="", status="settled"):
    """Append one posting. amount_cents is signed: revenue +, costs -."""
    _ensure()
    entry = {
        "id": new_id("p"),
        "ts": _now(),
        "order": order,
        "account": account,
        "amount": int(amount_cents),
        "ref": ref,
        "memo": memo,
        "status": status,
    }
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def postings(order=None):
    _ensure()
    out = []
    with LEDGER.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            if order is None or p.get("order") == order:
                out.append(p)
    return out


# ── orders ────────────────────────────────────────────────────────────

def _order_path(order_id):
    return ORDERS / f"{order_id}.md"


def _plan_path(order_id):
    return ORDERS / f"{order_id}.plan.json"


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))  # quoted + escaped: safe for colons, hashes, quotes


def _coerce(v):
    v = v.strip()
    if v == "":
        return ""
    if v[0] == '"':
        try:
            return json.loads(v)
        except ValueError:
            return v.strip('"')
    if v in ("true", "false"):
        return v == "true"
    if v.lstrip("-").isdigit():
        return int(v)
    return v


def write_order(order_id, fields, spec=""):
    """Create or overwrite an order's markdown file. Reversible frontmatter."""
    _ensure()
    lines = ["---", f"id: {order_id}"]
    for k, val in fields.items():
        if k in RESERVED_FIELDS:
            continue
        lines.append(f"{k}: {_fmt(val)}")
    body = spec if spec else fields.get("spec", "")
    lines += ["---", "", body, ""]
    _order_path(order_id).write_text("\n".join(lines))


def read_order(order_id):
    path = _order_path(order_id)
    if not path.exists():
        return None
    text = path.read_text()
    fields = {}
    spec_lines = []
    seen_front = 0
    for line in text.splitlines():
        if line.strip() == "---" and seen_front < 2:
            seen_front += 1
            continue
        if seen_front == 1:
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = _coerce(v)
        elif seen_front >= 2:
            spec_lines.append(line)
    fields["spec"] = "\n".join(spec_lines).strip()
    return fields


def write_plan(order_id, plan):
    _ensure()
    _plan_path(order_id).write_text(json.dumps(plan, indent=2))


def read_plan(order_id):
    p = _plan_path(order_id)
    return json.loads(p.read_text()) if p.exists() else None


def set_state(order_id, state, **extra):
    if state not in ORDER_STATES:
        raise ValueError(f"unknown order state '{state}'")
    o = read_order(order_id) or {"id": order_id}
    o["state"] = state
    o.update(extra)
    spec = o.pop("spec", "")
    write_order(order_id, o, spec=spec)
    return o


def all_orders():
    _ensure()
    out = [read_order(p.stem) for p in ORDERS.glob("*.md")]
    out = [o for o in out if o]
    out.sort(key=lambda o: (o.get("created", ""), o.get("id", "")))
    return out


def open_orders():
    return [o for o in all_orders() if o.get("state") not in ("delivered", "lost")]


# ── P&L: a fold over the postings ─────────────────────────────────────

def pnl(order=None):
    """Roll up postings into a profit-and-loss statement."""
    ps = postings(order)
    revenue = sum(p["amount"] for p in ps if p["account"] == "revenue")
    cogs = sum(p["amount"] for p in ps if p["account"].startswith("cogs"))
    fees = sum(p["amount"] for p in ps if p["account"].startswith("fees"))
    spend = cogs + fees  # negative
    profit = revenue + spend
    by_vendor = {}
    for p in ps:
        if p["amount"] < 0:
            by_vendor[p["account"]] = by_vendor.get(p["account"], 0) + p["amount"]
    return {
        "orders": len({p["order"] for p in ps if p["order"]}),
        "revenue_cents": revenue,
        "spend_cents": spend,
        "profit_cents": profit,
        "margin_pct": round(100 * profit / revenue, 1) if revenue > 0 else 0.0,
        "by_vendor": by_vendor,
    }


def dollars(cents):
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"
