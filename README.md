# Textile Dashboard — Real-Time Stack

## Architecture

```
Your Data Source (MongoDB / JSON)
         │
         ▼
   FastAPI (port 8000)
   ├── /api/orders       → REST endpoint
   ├── /ws/live          → WebSocket (push new orders instantly)
   └── /metrics          → Prometheus text format (scraped every 5s)
         │
         ├──▶ Prometheus (port 9090)  — stores time-series metrics
         │         │
         │         └──▶ Grafana (port 3000)  — live charts & alerts
         │
         └──▶ textile_dashboard_live.html  — your custom UI (WebSocket)
```

---

## Quick Start

### 1. Prerequisites
- Docker + Docker Compose installed
- Python 3.11+ (only needed if running outside Docker)

### 2. Start Everything
```bash
# Place data2.json in this folder (already done if cloned)
docker-compose up --build -d
```

This starts:
| Service       | URL                        | Notes                        |
|---------------|----------------------------|------------------------------|
| REST API      | http://localhost:8000      | API + metrics + WebSocket    |
| Data API      | http://localhost:8001      | Mock decoupled data provider |
| Prometheus    | http://localhost:9090      | Metric storage               |
| Grafana       | http://localhost:3000      | Dashboards (auto-provisioned)|

### 3. Open Grafana
- URL: http://localhost:3000
- User: `admin`
- Password: `textile123`
- The "Textile Sales — Live Dashboard" opens automatically.

### 4. Open Your HTML Dashboard
Open `textile_dashboard_live.html` in a browser.
- It will connect via WebSocket to `ws://localhost:8000/ws/live`
- Falls back to REST polling every 8s if WebSocket fails
- Works offline with embedded seed data

---

## Run Without Docker (Dev Mode)

```bash
pip install fastapi uvicorn websockets requests

# In Terminal 1 (Start the Data DB API):
python mock_external_api.py

# In Terminal 2 (Start the Main Backend):
python backend.py

# Both servers are required. The main Backend starts at http://localhost:8000
```

---

## Add a New Order (Test Real-Time)
```bash
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "quality": "60sX60s/92X72(G)",
    "weave": "plain",
    "quantity": 3000,
    "composition": "100% Kasturi Cotton",
    "status": "Confirmed",
    "rate": 195,
    "agentName": "Ravi Kumar",
    "customerName": "Export House"
  }'
```
You'll see the order appear instantly in the HTML dashboard via WebSocket.

---

## Prometheus Queries (PromQL)
| Metric                                     | What it shows             |
|--------------------------------------------|---------------------------|
| `textile_total_orders`                     | Total order count         |
| `textile_confirmed_orders`                 | Confirmed orders          |
| `textile_total_revenue_inr`                | Revenue in ₹              |
| `textile_avg_rate_per_metre`               | Average ₹/m               |
| `textile_agent_revenue_inr{agent="..."}`   | Revenue per agent         |
| `textile_customer_quantity_metres{...}`    | Fabric qty per customer   |

---

## Connect to Real MongoDB (Production)
In `backend.py`, replace the `ORDERS` list with Motor (async MongoDB):
```python
from motor.motor_asyncio import AsyncIOMotorClient
client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["textile"]

async def get_orders():
    return await db.orders.find().to_list(None)
```

---

## Files
```
textile_realtime/
├── backend.py                          # FastAPI app (Client Facing)
├── mock_external_api.py                # Simulated Decoupled Data Interface
├── requirements.txt
├── Dockerfile.api
├── docker-compose.yml
├── prometheus.yml
├── data2.json                          # seed data payload
├── textile_dashboard_live.html         # upgraded live frontend
└── grafana/
    └── provisioning/
        ├── datasources/prometheus.yml
        └── dashboards/
            ├── dashboards.yml
            └── textile.json            # Grafana dashboard (auto-loaded)
```
