"""FastAPI app: the Stripe webhook and a live dashboard over the book.

The dashboard page fetches everything from the API (no localStorage anywhere)
and shows the five numbers plus an event feed. Each request reads the current
book from disk, so the numbers are always live.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config
from .audit_log import AuditLog
from .cli import build_stack

app = FastAPI(title=f"{config.PROJECT_NAME} dashboard")
_STATIC = Path(__file__).parent / "static"


@app.get("/api/numbers")
def api_numbers():
    s = build_stack()
    five = s["orch"].five_numbers()
    five["status"] = config.status()
    return five


@app.get("/api/ledger")
def api_ledger():
    s = build_stack()
    lg = s["ledger"]
    return {"pnl": lg.pnl(), "transactions": lg.transactions(limit=50),
            "balanced": lg.total_imbalance() == 0}


@app.get("/api/events")
def api_events():
    return {"events": AuditLog().recent(30)}


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    s = build_stack()
    earn = s["earn"]
    if config.STRIPE_WEBHOOK_SECRET:
        try:
            event = earn.verify_webhook(payload, sig)
        except Exception as e:
            return JSONResponse({"error": f"signature check failed: {e}"}, status_code=400)
    else:
        import json
        event = json.loads(payload or b"{}")  # dev mode: no secret configured
    return earn.handle_event(event)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (_STATIC / "dashboard.html").read_text()


def serve(host="127.0.0.1", port=8787):
    import uvicorn
    print(f"daedalus dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
