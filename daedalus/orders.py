"""Persistent order state for Hermes-driven jobs.

The original demo kept the whole business loop inside one process call. Hermes
tools are naturally split across turns, so orders need a small durable state
machine that separate tool invocations can resume.
"""

import json
import time
from copy import deepcopy
from pathlib import Path

from . import config


TERMINAL_STATES = {"delivered", "lost"}
PAID_STATES = {"funded", "fulfilling", "funded_unfulfilled", "delivered", "blocked"}


class OrderStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._memory = {} if self.path is None else None

    @classmethod
    def in_memory(cls):
        return cls(path=None)

    def _load(self):
        if self._memory is not None:
            return deepcopy(self._memory)
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data):
        if self._memory is not None:
            self._memory = deepcopy(data)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(self.path)

    def create(self, order):
        data = self._load()
        now = time.time()
        clean = dict(order)
        clean.setdefault("created", now)
        clean["updated"] = now
        clean.setdefault("events", [])
        clean.setdefault("warnings", [])
        clean.setdefault("memory_refs", [])
        data[clean["id"]] = clean
        self._save(data)
        return deepcopy(clean)

    def read(self, order_id):
        order = self._load().get(order_id)
        return deepcopy(order) if order else None

    def update(self, order_id, **fields):
        data = self._load()
        if order_id not in data:
            return None
        data[order_id].update(fields)
        data[order_id]["updated"] = time.time()
        self._save(data)
        return deepcopy(data[order_id])

    def approve(self, order_id):
        """Record human approval for an order's spend. This is the out-of-band
        gate: called ONLY by the `daedalus approve` CLI (a human action) and never
        by a treasury tool, so the agent cannot self-approve."""
        data = self._load()
        if order_id not in data:
            return None
        data[order_id]["human_approved"] = True
        data[order_id]["approved_at"] = time.time()
        data[order_id]["updated"] = time.time()
        self._save(data)
        return deepcopy(data[order_id])

    def append_event(self, order_id, kind, message, **data_fields):
        data = self._load()
        if order_id not in data:
            return None
        ev = {"ts": time.time(), "kind": kind, "message": message}
        ev.update(data_fields)
        data[order_id].setdefault("events", []).append(ev)
        data[order_id]["updated"] = ev["ts"]
        self._save(data)
        return deepcopy(data[order_id])

    def append_warning(self, order_id, warning):
        data = self._load()
        if order_id not in data:
            return None
        warnings = data[order_id].setdefault("warnings", [])
        warning = str(warning)
        if warning not in warnings:
            warnings.append(warning)
        data[order_id]["updated"] = time.time()
        self._save(data)
        return deepcopy(data[order_id])

    def append_memory_ref(self, order_id, memory_ref):
        if not memory_ref or not memory_ref.get("id"):
            return self.read(order_id)
        data = self._load()
        if order_id not in data:
            return None
        data[order_id].setdefault("memory_refs", []).append(memory_ref)
        data[order_id]["updated"] = time.time()
        self._save(data)
        return deepcopy(data[order_id])

    def all(self, limit=50):
        orders = list(self._load().values())
        orders.sort(key=lambda o: o.get("updated", o.get("created", 0)), reverse=True)
        return deepcopy(orders[:limit])

    def open_orders(self):
        return [o for o in self.all(200) if o.get("state") not in TERMINAL_STATES]

    def conversion(self):
        orders = self.all(10000)
        paid = sum(1 for o in orders if o.get("state") in PAID_STATES)
        lost = sum(1 for o in orders if o.get("state") == "lost")
        decided = paid + lost
        return paid / decided if decided else None

    def counts(self):
        orders = self.all(10000)
        paid = sum(1 for o in orders if o.get("state") in PAID_STATES)
        lost = sum(1 for o in orders if o.get("state") == "lost")
        delivered = sum(1 for o in orders if o.get("state") == "delivered")
        return {"jobs": len(orders), "paid": paid, "lost": lost, "delivered": delivered}
