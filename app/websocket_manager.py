from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, List, Set

from starlette.websockets import WebSocket

from .orderbook import OrderBook
from .utils import quantize_8, now_ts


def _encode_decimal(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(quantize_8(obj))
    if isinstance(obj, (list, tuple)):
        return [_encode_decimal(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _encode_decimal(v) for k, v in obj.items()}
    return obj


class WebsocketManager:
    def __init__(self) -> None:
        self.marketdata_clients: Set[WebSocket] = set()
        self.trade_clients: Set[WebSocket] = set()
        self.marketdata_streams: List[asyncio.Queue[str]] = []
        self.trade_streams: List[asyncio.Queue[str]] = []
        self._lock = asyncio.Lock()

    async def register_marketdata_stream(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self.marketdata_streams.append(queue)
        return queue

    async def unregister_marketdata_stream(self, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            try:
                self.marketdata_streams.remove(queue)
            except ValueError:
                pass

    async def register_trade_stream(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        async with self._lock:
            self.trade_streams.append(queue)
        return queue

    async def unregister_trade_stream(self, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            try:
                self.trade_streams.remove(queue)
            except ValueError:
                pass

    async def _fanout_streams(self, pools: List[asyncio.Queue[str]], message: str) -> None:
        async with self._lock:
            queues = list(pools)
        stale: List[asyncio.Queue[str]] = []
        for queue in queues:
            try:
                queue.put_nowait(message)
            except Exception:
                stale.append(queue)
        if stale:
            async with self._lock:
                for queue in stale:
                    try:
                        pools.remove(queue)
                    except ValueError:
                        continue

    async def register_marketdata(self, ws: WebSocket) -> None:
        async with self._lock:
            self.marketdata_clients.add(ws)

    async def unregister_marketdata(self, ws: WebSocket) -> None:
        async with self._lock:
            self.marketdata_clients.discard(ws)

    async def register_trades(self, ws: WebSocket) -> None:
        async with self._lock:
            self.trade_clients.add(ws)

    async def unregister_trades(self, ws: WebSocket) -> None:
        async with self._lock:
            self.trade_clients.discard(ws)

    async def broadcast_marketdata(self, symbol: str, book: OrderBook, depth: int = 10) -> None:
        snap = book.snapshot_l2(depth)
        snap["symbol"] = symbol
        msg = json.dumps(_encode_decimal(snap))
        if self.marketdata_clients:
            dead: List[WebSocket] = []
            for ws in list(self.marketdata_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                await self.unregister_marketdata(ws)
        await self._fanout_streams(self.marketdata_streams, msg)
        

    async def broadcast_trades(self, symbol: str, trades: List[Any]) -> None:
        if not trades:
            return
        payload = {
            "symbol": symbol,
            "trades": [
                {
                    "trade_id": tr.trade_id,
                    "price": str(quantize_8(tr.price)),
                    "quantity": str(quantize_8(tr.quantity)),
                    "aggressor_side": tr.aggressor_side.value,
                    "maker_order_id": tr.maker_order_id,
                    "taker_order_id": tr.taker_order_id,
                    "timestamp": tr.timestamp,
                    "maker_fee": str(tr.maker_fee),
                    "taker_fee": str(tr.taker_fee),
                }
                for tr in trades
            ],
        }
        msg = json.dumps(payload)
        if self.trade_clients:
            dead: List[WebSocket] = []
            for ws in list(self.trade_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                await self.unregister_trades(ws)
        await self._fanout_streams(self.trade_streams, msg)

    async def heartbeat(self, interval: float = 10.0) -> None:
        """Periodic keepalive to help intermediaries keep WS connections open."""
        while True:
            await asyncio.sleep(interval)
            if not self.marketdata_clients and not self.trade_clients:
                continue
            msg = {
                "type": "heartbeat",
                "ts": now_ts(),
            }
            dead_md: List[WebSocket] = []
            for ws in list(self.marketdata_clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead_md.append(ws)
            for ws in dead_md:
                await self.unregister_marketdata(ws)
            dead_tr: List[WebSocket] = []
            for ws in list(self.trade_clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead_tr.append(ws)
            for ws in dead_tr:
                await self.unregister_trades(ws)
            await self._fanout_streams(self.marketdata_streams, json.dumps(msg))
            await self._fanout_streams(self.trade_streams, json.dumps(msg))
