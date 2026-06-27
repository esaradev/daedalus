"""daedalus — the financial control plane for agents that spend to earn.

A double-entry ledger plus a spend-authorization gate, so an agent can run paid
work and know whether it is profitable. Standalone-runnable; ships a Hermes
SKILL.md and a NemoClaw policy.yaml for the real stack.
"""

from . import config

__all__ = ["config"]
__version__ = "0.2.0"
