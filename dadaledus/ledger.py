"""The spine. An append-only, double-entry ledger on disk.

Money is integer cents. Postings are never mutated. P&L is a fold over the
postings file. Orders are one markdown file each so a human (or a judge) can
read the books by scrolling a folder.

  ~/fabric/dadaledus/
  ├── ledger.jsonl          one immutable posting per line
  └── orders/<id>.md        one order, YAML frontmatter + spec

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
    os.environ.get("DADALEDUS_DIR")
    or (Path(os.environ.get("FABRIC_DIR", Path.home() / "fabric")) / "dadaledus")
)
LEDGER = STORE / "ledger.jsonl"
ORDERS = STORE / "orders"

ORDER_STATES = ("quoted", "funded", "fulfilling", "delivered")


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


def write_order(order_id, fields, spec=""):
    """Create or overwrite an order's markdown file. fields -> YAML frontmatter."""
    _ensure()
    lines = ["---", f"id: {order_id}"]
    for k, v in fields.items():
        lines.append(f"{k}: {json.dumps(v) if isinstance(v, str) and (':' in v or '#' in v) else v}")
    lines += ["---", "", spec or fields.get("spec", ""), ""]
    _order_path(order_id).write_text("\n".join(lines))


def read_order(order_id):
    path = _order_path(order_id)
    if not path.exists():
        return None
    text = path.read_text()
    fields = {}
    spec_lines = []
    in_front = False
    done_front = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_front and not done_front:
                in_front = True
            elif in_front:
                in_front = False
                done_front = True
            continue
        if in_front:
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = _coerce(v.strip())
        elif done_front:
            spec_lines.append(line)
    fields["spec"] = "\n".join(spec_lines).strip()
    return fields


def _coerce(v):
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
        return int(v)
    return v


def set_state(order_id, state, **extra):
    o = read_order(order_id) or {"id": order_id}
    o["state"] = state
    o.update(extra)
    spec = o.pop("spec", "")
    write_order(order_id, o, spec=spec)
    return o


def open_orders():
    _ensure()
    out = []
    for p in sorted(ORDERS.glob("*.md")):
        o = read_order(p.stem)
        if o and o.get("state") != "delivered":
            out.append(o)
    return out


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
        "margin_pct": round(100 * profit / revenue, 1) if revenue else 0.0,
        "by_vendor": by_vendor,
    }


def dollars(cents):
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"
