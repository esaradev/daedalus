"""Append-only record of every spend decision. Allowed or blocked, with reason.

This is the audit trail a finance team needs before letting agents touch a card,
and it feeds the dashboard's "blocked actions" number and the event feed. One
JSON object per line; never mutated.
"""

import json
import time
from pathlib import Path

from . import config


class AuditLog:
    def __init__(self, path=None):
        self.path = Path(path) if path else config.AUDIT_LOG_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, action, vendor, amount_cents, allowed, protection, reason):
        entry = {
            "ts": time.time(),
            "action": action,
            "vendor": vendor,
            "amount_cents": amount_cents,
            "allowed": bool(allowed),
            "protection": protection,
            "reason": reason,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def entries(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def count_blocked(self):
        return sum(1 for e in self.entries() if not e["allowed"])

    def recent(self, n=20):
        return self.entries()[-n:][::-1]
