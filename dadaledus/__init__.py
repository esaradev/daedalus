"""dadaledus — the financial control plane for Hermes agents.

Daedalus built the apparatus. This is the apparatus that lets an agent run a
business: a double-entry ledger, Stripe earn + approval-gated spend, and
bounded self-evolving pricing. Sibling to the Icarus memory plugins; shares the
same ~/fabric store.

Tools:
  treasury_intake       price an order, send a Stripe checkout link    (autonomous)
  treasury_collect      book revenue once the customer pays            (autonomous)
  treasury_fulfill      approval-gated spend, deliver, book the margin
  treasury_pnl          profit-and-loss from the ledger
  treasury_open_orders  orders still in flight
  treasury_evolve       reprice from the books, within hard bounds
  treasury_rollback     undo the last pricing change

Hooks:
  on_session_start  brief the agent on the book and orders in flight
  on_session_end    snapshot pricing
"""

import logging

from . import schemas, tools, hooks

logger = logging.getLogger(__name__)


def register(ctx):
    t = "treasury"
    ctx.register_tool(name="treasury_intake", toolset=t,
                      schema=schemas.INTAKE, handler=tools.treasury_intake)
    ctx.register_tool(name="treasury_collect", toolset=t,
                      schema=schemas.COLLECT, handler=tools.treasury_collect)
    ctx.register_tool(name="treasury_fulfill", toolset=t,
                      schema=schemas.FULFILL, handler=tools.treasury_fulfill)
    ctx.register_tool(name="treasury_pnl", toolset=t,
                      schema=schemas.PNL, handler=tools.treasury_pnl)
    ctx.register_tool(name="treasury_open_orders", toolset=t,
                      schema=schemas.OPEN_ORDERS, handler=tools.treasury_open_orders)
    ctx.register_tool(name="treasury_evolve", toolset=t,
                      schema=schemas.EVOLVE, handler=tools.treasury_evolve)
    ctx.register_tool(name="treasury_rollback", toolset=t,
                      schema=schemas.ROLLBACK, handler=tools.treasury_rollback)

    ctx.register_hook("on_session_start", hooks.on_session_start)
    ctx.register_hook("on_session_end", hooks.on_session_end)

    logger.info("dadaledus registered (7 tools, 2 hooks)")
