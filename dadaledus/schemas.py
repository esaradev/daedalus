"""Tool schemas — what the agent sees."""

INTAKE = {
    "name": "treasury_intake",
    "description": (
        "Take in a customer order. Prices the work as cost-to-fulfill times the "
        "current markup, opens an order, and returns a Stripe checkout link to send "
        "the customer. Fully autonomous — receiving money needs no approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {"type": "string", "description": "What the customer wants delivered"},
            "customer": {"type": "string", "description": "Customer identifier (optional)"},
        },
        "required": ["spec"],
    },
}

COLLECT = {
    "name": "treasury_collect",
    "description": (
        "Check whether an order's checkout has been paid and, if so, book the "
        "revenue to the ledger. Autonomous."
    ),
    "parameters": {
        "type": "object",
        "properties": {"order": {"type": "string", "description": "Order id from treasury_intake"}},
        "required": ["order"],
    },
}

FULFILL = {
    "name": "treasury_fulfill",
    "description": (
        "Fulfill a funded order: estimate the inputs to buy, request ONE scoped "
        "virtual card covering the whole spend (this blocks on a human approval tap "
        "in the Link app — the agent cannot self-approve), then on approval buy the "
        "inputs, produce the deliverable on Nemotron, book the costs, and report the "
        "margin. Only call on a funded order."
    ),
    "parameters": {
        "type": "object",
        "properties": {"order": {"type": "string", "description": "Funded order id"}},
        "required": ["order"],
    },
}

ABANDON = {
    "name": "treasury_abandon",
    "description": (
        "Record that a quoted order was never paid (the customer declined or went "
        "silent). This is the demand signal pricing uses: too many lost orders means "
        "the price is above the market. Call when a checkout link goes unpaid."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "order": {"type": "string", "description": "The quoted order id"},
            "reason": {"type": "string", "description": "Why it was lost (optional)"},
        },
        "required": ["order"],
    },
}

PNL = {
    "name": "treasury_pnl",
    "description": "Profit-and-loss from the ledger. Omit 'order' for the whole book.",
    "parameters": {
        "type": "object",
        "properties": {"order": {"type": "string", "description": "Limit to one order (optional)"}},
    },
}

OPEN_ORDERS = {
    "name": "treasury_open_orders",
    "description": "List orders that are not yet delivered, with their state.",
    "parameters": {"type": "object", "properties": {}},
}

EVOLVE = {
    "name": "treasury_evolve",
    "description": (
        "Read the P&L and adjust the markup within hard bounds: raise it when margins "
        "are fat and demand holds, cut it when margins are thin. Snapshots first so it "
        "can be rolled back. Returns the decision and the reasoning from the numbers."
    ),
    "parameters": {"type": "object", "properties": {}},
}

ROLLBACK = {
    "name": "treasury_rollback",
    "description": "Restore the markup from before the last evolve.",
    "parameters": {"type": "object", "properties": {}},
}
