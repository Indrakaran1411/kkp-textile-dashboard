"""
Textile Dashboard — FastAPI Backend
Serves orders API + Prometheus /metrics endpoint + WebSocket live feed
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse, FileResponse
import json, time, asyncio, random
from datetime import datetime, timezone
from typing import Optional

app = FastAPI(title="Textile Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory order store (replace with MongoDB/PostgreSQL in production) ──────
ORDERS: list[dict] = []

import urllib.request
import urllib.error

def load_seed_data():
    """Fetch startup data dynamically from the external API instead of a local file."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8001/api/external/orders")
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read().decode())
            for o in payload.get("formData", []):
                ORDERS.append({
                    "_id":          o.get("_id"),
                    "date":         o.get("date"),
                    "quality":      o.get("quality"),
                    "weave":        o.get("weave"),
                    "quantity":     o.get("quantity"),
                    "composition":  o.get("composition"),
                    "status":       o.get("status"),
                    "rate":         o.get("rate"),
                    "agentName":    o.get("agentName"),
                    "customerName": o.get("customerName"),
                    "declineReason": o.get("declineReason"),
                })
        print(f"✅ [fetching] Successfully loaded {len(ORDERS)} orders dynamically from API!")
    except (urllib.error.URLError, Exception) as e:
        print(f"⚠️ [fetching] Could not reach external API: {e} – starting empty or relying on incoming real-time traffic.")

load_seed_data()

# ── Prometheus metrics helpers ─────────────────────────────────────────────────
_start_time = time.time()

def compute_metrics() -> dict:
    total        = len(ORDERS)
    confirmed    = sum(1 for o in ORDERS if o["status"] == "Confirmed")
    processed    = sum(1 for o in ORDERS if o["status"] == "Processed")
    total_qty    = sum(o["quantity"] for o in ORDERS)
    total_rev    = sum(o["quantity"] * o["rate"] for o in ORDERS)
    avg_rate     = total_rev / total_qty if total_qty else 0

    # per-agent revenue
    agent_rev: dict[str, float] = {}
    for o in ORDERS:
        agent_rev[o["agentName"]] = agent_rev.get(o["agentName"], 0) + o["quantity"] * o["rate"]

    # per-customer qty
    cust_qty: dict[str, int] = {}
    for o in ORDERS:
        cust_qty[o["customerName"]] = cust_qty.get(o["customerName"], 0) + o["quantity"]

    return {
        "total_orders":    total,
        "confirmed_orders": confirmed,
        "processed_orders": processed,
        "total_quantity_m": total_qty,
        "total_revenue_inr": total_rev,
        "avg_rate_per_m":   round(avg_rate, 2),
        "agent_revenue":    agent_rev,
        "customer_quantity": cust_qty,
        "uptime_seconds":   round(time.time() - _start_time, 1),
    }


# ── /metrics  (Prometheus text format) ────────────────────────────────────────
@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    m = compute_metrics()
    lines = []

    def g(name, value, labels="", help_text="", metric_type="gauge"):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {metric_type}")
        tag = f"{{{labels}}}" if labels else ""
        lines.append(f"{name}{tag} {value}")

    g("textile_total_orders",     m["total_orders"],
      help_text="Total number of textile orders", metric_type="gauge")
    g("textile_confirmed_orders", m["confirmed_orders"],
      help_text="Orders with Confirmed status")
    g("textile_processed_orders", m["processed_orders"],
      help_text="Orders with Processed status")
    g("textile_total_quantity_metres", m["total_quantity_m"],
      help_text="Total fabric quantity ordered in metres")
    g("textile_total_revenue_inr", m["total_revenue_inr"],
      help_text="Total revenue in INR")
    g("textile_avg_rate_per_metre", m["avg_rate_per_m"],
      help_text="Average rate per metre in INR")
    g("textile_uptime_seconds",   m["uptime_seconds"],
      help_text="API server uptime in seconds", metric_type="counter")

    # per-agent revenue labels
    lines.append("# HELP textile_agent_revenue_inr Revenue per sales agent in INR")
    lines.append("# TYPE textile_agent_revenue_inr gauge")
    for agent, rev in m["agent_revenue"].items():
        safe = agent.replace(" ", "_").replace("-", "_")
        lines.append(f'textile_agent_revenue_inr{{agent="{safe}"}} {rev}')

    # per-customer quantity labels
    lines.append("# HELP textile_customer_quantity_metres Fabric quantity per customer")
    lines.append("# TYPE textile_customer_quantity_metres gauge")
    for cust, qty in m["customer_quantity"].items():
        safe = cust.replace(" ", "_").replace("-", "_")
        lines.append(f'textile_customer_quantity_metres{{customer="{safe}"}} {qty}')

    return "\n".join(lines) + "\n"


# ── /api/orders  (REST) ────────────────────────────────────────────────────────
@app.get("/api/orders")
def get_orders(status: Optional[str] = None, agent: Optional[str] = None):
    result = ORDERS
    if status:
        result = [o for o in result if o["status"].lower() == status.lower()]
    if agent:
        result = [o for o in result if o["agentName"].lower() == agent.lower()]
    return {"status": 200, "count": len(result), "formData": result}


@app.post("/api/orders")
async def create_order(order: dict):
    order["_id"] = f"ord{int(time.time()*1000)}"
    order["date"] = datetime.now(timezone.utc).isoformat()
    ORDERS.append(order)
    # broadcast to WebSocket clients
    await manager.broadcast({"event": "new_order", "data": order})
    return {"status": 201, "message": "Order created", "order": order}


@app.get("/api/metrics/summary")
def metrics_summary():
    return JSONResponse(compute_metrics())


# ── WebSocket live feed ────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # send current snapshot on connect
        await websocket.send_json({"event": "snapshot", "data": ORDERS})
        while True:
            # keep connection alive + push metrics every 5 s
            await asyncio.sleep(5)
            await websocket.send_json({
                "event": "metrics_update",
                "data": compute_metrics(),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "uptime": round(time.time() - _start_time, 1)}


# ── UI ────────────────────────────────────────────────────────────────────────
@app.get("/")
def serve_dashboard():
    return FileResponse("textile_dashboard_live.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
