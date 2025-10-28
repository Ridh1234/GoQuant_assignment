import asyncio
import json
import random
from decimal import Decimal

import httpx
import websockets

API = "http://localhost:8000"


async def stream_ws(path: str, label: str):
    url = API.replace("http", "ws") + path
    async with websockets.connect(url) as ws:
        while True:
            msg = await ws.recv()
            print(f"[{label}] {msg}")


async def submit_orders():
    async with httpx.AsyncClient(base_url=API) as client:
        # Seed
        for i in range(10):
            await client.post("/orders", json={
                "symbol": "BTC-USD",
                "side": "sell",
                "type": "limit",
                "quantity": "0.1",
                "price": str(30000 + i)
            })
        # Random flow
        while True:
            side = random.choice(["buy", "sell"])
            typ = random.choice(["market", "limit", "ioc"])
            price = None
            if typ != "market":
                price = str(29950 + random.randint(-50, 50))
            qty = str(Decimal("0.01"))
            await client.post("/orders", json={
                "symbol": "BTC-USD",
                "side": side,
                "type": typ,
                "quantity": qty,
                "price": price
            })
            await asyncio.sleep(0.05)


async def main():
    tasks = [
        asyncio.create_task(stream_ws("/ws/marketdata", "MD")),
        asyncio.create_task(stream_ws("/ws/trades", "TR")),
        asyncio.create_task(submit_orders()),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
