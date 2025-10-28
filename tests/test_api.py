from decimal import Decimal

from fastapi.testclient import TestClient

from app.api import create_app


def test_api_endpoints():
    app = create_app()
    client = TestClient(app)

    # Post a sell limit
    r = client.post("/orders", json={
        "symbol": "BTC-USD",
        "side": "sell",
        "type": "limit",
        "quantity": "1.0",
        "price": "30000"
    })
    assert r.status_code == 200
    oid = r.json()["order_id"]

    # Get BBO
    r = client.get("/bbo/BTC-USD")
    assert r.status_code == 200
    data = r.json()
    assert data["ask"]["price"] == "30000"

    # Aggressive buy
    r = client.post("/orders", json={
        "symbol": "BTC-USD",
        "side": "buy",
        "type": "market",
        "quantity": "0.4"
    })
    assert r.status_code == 200
    trades = r.json()["trades"]
    # Price formatted with 8 decimals
    assert trades and trades[0]["price"].startswith("30000")

    # Cancel non-existent
    r = client.delete("/orders/not_there")
    assert r.status_code == 404
