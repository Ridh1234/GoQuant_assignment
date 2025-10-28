from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

from fastapi import FastAPI, WebSocket, APIRouter, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .engine import MatchingEngine
from .models import OrderRequest
from .utils import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="GoQuant Matching Engine", version="0.1.0")
    # Dev CORS: allow local file/index.html and localhost tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = APIRouter()

    frontend_dir = (Path(__file__).resolve().parent.parent / "frontend").resolve()
    index_path = frontend_dir / "index.html"
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def _serve_index():
            return FileResponse(index_path)

    engine = MatchingEngine()
    app.state.engine = engine

    @app.on_event("startup")
    async def _startup():
        # Load persisted state and start background persistence task
        await engine.load_state()
        app.state.persist_task = asyncio.create_task(engine.save_state_periodic(5.0))
        # Periodic trigger scan as a safety net
        async def _trigger_loop():
            while True:
                await asyncio.sleep(0.5)
                for sym in list(engine.books.keys()):
                    await engine.process_triggers(sym)
        app.state.trigger_task = asyncio.create_task(_trigger_loop())
        # WebSocket keepalive heartbeat
        app.state.heartbeat_task = asyncio.create_task(engine.ws.heartbeat(10.0))

    @app.on_event("shutdown")
    async def _shutdown():
        for task_name in ("persist_task", "trigger_task", "heartbeat_task"):
            t = getattr(app.state, task_name, None)
            if t:
                t.cancel()
        await engine.save_state()

    # REST endpoints
    @router.post("/orders")
    async def post_order(req: OrderRequest):
        order, trades = await engine.submit_order(req)
        filled = order.quantity - order.remaining
        return JSONResponse(
            {
                "order_id": order.order_id,
                "status": "accepted",
                "filled_quantity": str(filled),
                "remaining_quantity": str(order.remaining),
                "trades": [
                    {
                        "trade_id": t.trade_id,
                        "price": str(t.price),
                        "quantity": str(t.quantity),
                        "aggressor_side": t.aggressor_side.value,
                        "maker_order_id": t.maker_order_id,
                        "taker_order_id": t.taker_order_id,
                        "timestamp": t.timestamp,
                        "maker_fee": str(t.maker_fee),
                        "taker_fee": str(t.taker_fee),
                    }
                    for t in trades
                ],
            }
        )

    @router.delete("/orders/{order_id}")
    async def delete_order(order_id: str):
        removed = await engine.cancel_order(order_id)
        if not removed:
            raise HTTPException(status_code=404, detail="order not found")
        return {"order_id": order_id, "status": "cancelled"}

    @router.get("/orderbook/{symbol}")
    async def get_orderbook(symbol: str, depth: int = 10):
        return engine.get_l2(symbol, depth)

    @router.get("/bbo/{symbol}")
    async def get_bbo(symbol: str):
        bbo = engine.get_bbo(symbol)
        payload = {
            "symbol": bbo.symbol,
            "bid": None if not bbo.bid else {"price": str(bbo.bid.price), "quantity": str(bbo.bid.quantity)},
            "ask": None if not bbo.ask else {"price": str(bbo.ask.price), "quantity": str(bbo.ask.quantity)},
            "timestamp": bbo.timestamp,
        }
        return payload

    @router.get("/trades/{symbol}")
    async def get_trades(symbol: str):
        trs = engine.get_trades(symbol)
        return {
            "symbol": symbol,
            "trades": [
                {
                    "trade_id": t.trade_id,
                    "price": str(t.price),
                    "quantity": str(t.quantity),
                    "aggressor_side": t.aggressor_side.value,
                    "maker_order_id": t.maker_order_id,
                    "taker_order_id": t.taker_order_id,
                    "timestamp": t.timestamp,
                    "maker_fee": str(t.maker_fee),
                    "taker_fee": str(t.taker_fee),
                }
                for t in trs
            ],
        }

    @router.get("/poll/{symbol}")
    async def poll_updates(symbol: str, depth: int = 10, since: str | None = None):
        orderbook = engine.get_l2(symbol, depth)
        trades, latest_id = engine.get_trades_since(symbol, since)
        return {
            "orderbook": orderbook,
            "trades": [
                {
                    "trade_id": t.trade_id,
                    "price": str(t.price),
                    "quantity": str(t.quantity),
                    "aggressor_side": t.aggressor_side.value,
                    "maker_order_id": t.maker_order_id,
                    "taker_order_id": t.taker_order_id,
                    "timestamp": t.timestamp,
                    "maker_fee": str(t.maker_fee),
                    "taker_fee": str(t.taker_fee),
                }
                for t in trades
            ],
            "latest_trade_id": latest_id,
        }

    # Streaming endpoints (SSE)
    @router.get("/stream/marketdata")
    async def stream_marketdata(request: Request):
        queue = await engine.ws.register_marketdata_stream()

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {data}\n\n"
            finally:
                await engine.ws.unregister_marketdata_stream(queue)

        headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    @router.get("/stream/trades")
    async def stream_trades(request: Request):
        queue = await engine.ws.register_trade_stream()

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {data}\n\n"
            finally:
                await engine.ws.unregister_trade_stream(queue)

        headers = {"Cache-Control": "no-cache", "Connection": "keep-alive"}
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    # WebSocket endpoints
    @app.websocket("/ws/marketdata")
    async def ws_marketdata(ws: WebSocket):
        await ws.accept()
        await engine.ws.register_marketdata(ws)
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        finally:
            await engine.ws.unregister_marketdata(ws)

    @app.websocket("/ws/trades")
    async def ws_trades(ws: WebSocket):
        await ws.accept()
        await engine.ws.register_trades(ws)
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        finally:
            await engine.ws.unregister_trades(ws)

    app.include_router(router)
    return app
