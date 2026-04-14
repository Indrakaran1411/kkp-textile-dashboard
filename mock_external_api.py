import json
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Mock External Data System")

@app.get("/api/external/orders")
def get_external_orders():
    # In a real environment, this would query an external enterprise database.
    try:
        with open("data2.json") as f:
            data = json.load(f)
            return data
    except Exception as e:
        return {"formData": []}

if __name__ == "__main__":
    uvicorn.run("mock_external_api:app", host="0.0.0.0", port=8001, reload=True)
