"""Strict double-entry ledger on SQLite.

Every transaction is a set of entries whose signed amounts sum to exactly zero.
Amounts are integer cents. Sign convention: debit positive, credit negative,
applied uniformly across all accounts, so a balanced transaction sums to 0 and
the whole book always sums to 0.

  Cash      asset   (debit-normal)   balance = sum of its entries
  COGS      expense (debit-normal)
  Revenue   income  (credit-normal)  reported revenue = -balance
  Equity    equity  (credit-normal)  retained margin

Earn $18.24:  debit Cash +1824, credit Revenue -1824
Spend $4.56:  debit COGS  +456, credit Cash    -456

P&L is a fold over the entries. Nothing is ever mutated or deleted.
"""

import sqlite3
import time
from pathlib import Path

from . import config

INCOME_ACCOUNTS = ("Revenue", "Equity")  # credit-normal: negate to report positive


class Unbalanced(ValueError):
    pass


class Ledger:
    def __init__(self, db_path=None):
        self.path = Path(db_path) if db_path else config.DB_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS txn (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      REAL    NOT NULL,
                kind    TEXT    NOT NULL,
                ref     TEXT    NOT NULL DEFAULT '',
                memo    TEXT    NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS entry (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id   INTEGER NOT NULL REFERENCES txn(id),
                account  TEXT    NOT NULL,
                amount   INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_entry_account ON entry(account);
            CREATE INDEX IF NOT EXISTS idx_entry_txn ON entry(txn_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_ref ON txn(ref) WHERE ref != '';
            """
        )
        self.conn.commit()

    # ── posting ───────────────────────────────────────────────────────
    def post(self, kind, entries, ref="", memo=""):
        """entries: list of (account, amount_cents). Must sum to zero."""
        clean = []
        for a, amt in entries:
            iamt = int(amt)
            if amt != iamt:
                raise ValueError(f"amount {amt!r} for {a} is not whole cents")
            clean.append((str(a), iamt))
        entries = clean
        total = sum(amt for _, amt in entries)
        if total != 0:
            raise Unbalanced(
                f"transaction '{kind}' is unbalanced: entries sum to {total}, must be 0. "
                f"Every posting needs equal debits and credits."
            )
        if not entries:
            raise Unbalanced(f"transaction '{kind}' has no entries")
        cur = self.conn.cursor()
        try:
            cur.execute("INSERT INTO txn (ts, kind, ref, memo) VALUES (?,?,?,?)",
                        (time.time(), kind, ref, memo))
            txn_id = cur.lastrowid
            cur.executemany("INSERT INTO entry (txn_id, account, amount) VALUES (?,?,?)",
                            [(txn_id, a, amt) for a, amt in entries])
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise ValueError(f"ref '{ref}' already booked; refusing to double-book")
        return txn_id

    def earn(self, amount_cents, ref="", memo=""):
        return self.post("earn", [("Cash", amount_cents), ("Revenue", -amount_cents)],
                         ref=ref, memo=memo)

    def spend(self, amount_cents, vendor, ref="", memo=""):
        if amount_cents <= 0:
            raise ValueError("spend amount must be positive")
        return self.post(f"spend:{vendor}",
                         [("COGS", amount_cents), ("Cash", -amount_cents)],
                         ref=ref, memo=memo or vendor)

    # ── reads ─────────────────────────────────────────────────────────
    def balance(self, account):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS b FROM entry WHERE account=?", (account,)
        ).fetchone()
        return row["b"]

    def has_ref(self, ref):
        """Has any transaction already been booked against this external ref?"""
        if not ref:
            return False
        row = self.conn.execute("SELECT 1 FROM txn WHERE ref=? LIMIT 1", (ref,)).fetchone()
        return row is not None

    def total_imbalance(self):
        """Whole-book invariant: every entry summed must be exactly zero."""
        row = self.conn.execute("SELECT COALESCE(SUM(amount),0) AS b FROM entry").fetchone()
        return row["b"]

    def pnl(self):
        revenue = -self.balance("Revenue")        # credit-normal -> report positive
        cogs = self.balance("COGS")
        profit = revenue - cogs
        return {
            "revenue_cents": revenue,
            "cost_cents": cogs,
            "profit_cents": profit,
            "cash_cents": self.balance("Cash"),
            "margin_pct": round(100 * profit / revenue, 1) if revenue > 0 else 0.0,
        }

    def transactions(self, limit=50):
        rows = self.conn.execute(
            """SELECT t.id, t.ts, t.kind, t.ref, t.memo,
                      COALESCE(SUM(CASE WHEN e.amount>0 THEN e.amount END),0) AS debit
               FROM txn t JOIN entry e ON e.txn_id=t.id
               GROUP BY t.id ORDER BY t.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


def dollars(cents):
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"
