from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import asdict
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .models import (
    Order,
    Trade,
    Side,
    OrderType,
    OrderRequest,
)
from .orderbook import OrderBook
from .utils import next_id, now_ts, as_decimal, quantize_8, StructuredAdapter, setup_logging
from . import persistence
from .websocket_manager import WebsocketManager
import logging


class MatchingEngine:
    """Core matching engine managing multiple symbol order books."""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        maker_rebate_bps: Decimal = Decimal("-1.0"),  # negative = rebate
        taker_fee_bps: Decimal = Decimal("2.5"),
        recent_trades_limit: int = 1000,
        persist_path: str = "state",
    ) -> None:
        setup_logging()
        self.log = StructuredAdapter(logging.getLogger("engine"), {})
        self.books: Dict[str, OrderBook] = {}
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.recent_trades: Dict[str, deque[Trade]] = defaultdict(lambda: deque(maxlen=recent_trades_limit))
        self.order_symbol_index: Dict[str, str] = {}
        self.ws = WebsocketManager()
        self.maker_rebate_bps = maker_rebate_bps
        self.taker_fee_bps = taker_fee_bps
        self.persist_path = persist_path
        # Trigger order stores
        self.triggers: Dict[str, List[Order]] = defaultdict(list)  # symbol -> pending advanced orders

        if symbols:
            for s in symbols:
                self._ensure_book(s)

    def _ensure_book(self, symbol: str) -> None:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol)

    async def load_state(self) -> None:
        data = await persistence.load_state(self.persist_path)
        for sym, orders in data.get("open_orders", {}).items():
            self._ensure_book(sym)
            for od in orders:
                order = Order(
                    order_id=od["order_id"],
                    symbol=sym,
                    side=Side(od["side"]),
                    type=OrderType(od["type"]),
                    quantity=as_decimal(od["quantity"]),
                    remaining=as_decimal(od["remaining"]),
                    price=as_decimal(od["price"]) if od.get("price") else None,
                    timestamp=od.get("timestamp", now_ts()),
                    client_order_id=od.get("client_order_id"),
                    stop_price=as_decimal(od["stop_price"]) if od.get("stop_price") else None,
                    take_profit_price=as_decimal(od["take_profit_price"]) if od.get("take_profit_price") else None,
                    user_id=od.get("user_id"),
                )
                # Only limit orders can rest
                if order.type == OrderType.limit and order.remaining > 0 and order.price is not None:
                    self.books[sym].add_limit(order)
                    self.order_symbol_index[order.order_id] = sym
                else:
                    # Re-add to triggers if advanced
                    if order.type in (OrderType.stop, OrderType.stop_limit, OrderType.take_profit):
                        self.triggers[sym].append(order)
        for sym, trades in data.get("recent_trades", {}).items():
            for tr in trades:
                self.recent_trades[sym].append(
                    Trade(
                        trade_id=tr["trade_id"],
                        symbol=sym,
                        price=as_decimal(tr["price"]),
                        quantity=as_decimal(tr["quantity"]),
                        aggressor_side=Side(tr["aggressor_side"]),
                        maker_order_id=tr["maker_order_id"],
                        taker_order_id=tr["taker_order_id"],
                        timestamp=tr["timestamp"],
                        maker_fee=as_decimal(tr.get("maker_fee", "0")),
                        taker_fee=as_decimal(tr.get("taker_fee", "0")),
                    )
                )

    async def save_state_periodic(self, interval_sec: float = 5.0) -> None:
        while True:
            try:
                await self.save_state()
            except Exception as e:
                self.log.warning("persist_error", extra={"error": str(e)})
            await asyncio.sleep(interval_sec)

    async def save_state(self) -> None:
        open_orders: Dict[str, List[dict]] = {}
        for sym, book in self.books.items():
            open_orders[sym] = []
            # Iterate all price levels on both sides
            for sd in (book.bids, book.asks):
                for _, level in sd.items():
                    for o in level.queue:
                        open_orders[sym].append(
                            {
                                "order_id": o.order_id,
                                "side": o.side.value,
                                "type": o.type.value,
                                "quantity": str(o.quantity),
                                "remaining": str(o.remaining),
                                "price": str(o.price) if o.price is not None else None,
                                "timestamp": o.timestamp,
                                "client_order_id": o.client_order_id,
                                "stop_price": str(o.stop_price) if o.stop_price else None,
                                "take_profit_price": str(o.take_profit_price) if o.take_profit_price else None,
                                "user_id": o.user_id,
                            }
                        )
        recent_trades = {
            sym: [asdict(t) for t in list(trs)] for sym, trs in self.recent_trades.items()
        }
        await persistence.save_state(self.persist_path, {"open_orders": open_orders, "recent_trades": recent_trades})

    def _fees(self, price: Decimal, qty: Decimal) -> Tuple[Decimal, Decimal]:
        notional = price * qty
        maker_fee = (notional * self.maker_rebate_bps) / Decimal("10000")
        taker_fee = (notional * self.taker_fee_bps) / Decimal("10000")
        return quantize_8(maker_fee), quantize_8(taker_fee)

    def _precheck_fok(self, symbol: str, side: Side, price: Optional[Decimal], qty: Decimal) -> bool:
        book = self.books[symbol]
        need = qty
        if side == Side.buy:
            # consume asks up to price
            for p, level in book.asks.items():
                if price is not None and p > price:
                    break
                for o in level.queue:
                    need -= o.remaining
                    if need <= 0:
                        return True
        else:
            for p, level in reversed(book.bids.items()):
                if price is not None and p < price:
                    break
                for o in level.queue:
                    need -= o.remaining
                    if need <= 0:
                        return True
        return False

    def _record_trades_and_broadcast(self, symbol: str, raw_trades: List[Tuple[Order, Order, Decimal, Decimal]]) -> List[Trade]:
        trades: List[Trade] = []
        for maker, taker, price, qty in raw_trades:
            maker_fee, taker_fee = self._fees(price, qty)
            tr = Trade(
                trade_id=next_id("tr"),
                symbol=symbol,
                price=quantize_8(price),
                quantity=quantize_8(qty),
                aggressor_side=taker.side,
                maker_order_id=maker.order_id,
                taker_order_id=taker.order_id,
                timestamp=now_ts(),
                maker_fee=maker_fee,
                taker_fee=taker_fee,
            )
            self.recent_trades[symbol].append(tr)
            trades.append(tr)
        # Broadcast trades and market data
        if trades:
            asyncio.create_task(self.ws.broadcast_trades(symbol, trades))
            # Trigger checks on trade prints
            asyncio.create_task(self.process_triggers(symbol))
        asyncio.create_task(self.ws.broadcast_marketdata(symbol, self.books[symbol]))
        return trades

    async def submit_order(self, req: OrderRequest) -> Tuple[Order, List[Trade]]:
        symbol = req.symbol
        self._ensure_book(symbol)
        async with self.locks[symbol]:
            order = Order(
                order_id=next_id("ord"),
                symbol=symbol,
                side=req.side,
                type=req.type,
                quantity=req.quantity,
                remaining=req.quantity,
                price=req.price,
                client_order_id=req.client_order_id,
                stop_price=req.stop_price,
                take_profit_price=req.take_profit_price,
            )
            trades: List[Trade] = []
            book = self.books[symbol]

            # Advanced orders: store until triggered
            if order.type in (OrderType.stop, OrderType.stop_limit, OrderType.take_profit):
                self.triggers[symbol].append(order)
                self.order_symbol_index[order.order_id] = symbol
                self.log.info("order_accepted_trigger", extra={"order_id": order.order_id, "symbol": symbol})
                return order, trades

            # FOK precheck
            if order.type == OrderType.fok:
                price_limit = order.price
                if not self._precheck_fok(symbol, order.side, price_limit, order.quantity):
                    self.log.info("order_fok_reject", extra={"order_id": order.order_id, "reason": "insufficient liquidity"})
                    return order, trades

            # Match against the book
            raw_trades = book.match(order)
            trades = self._record_trades_and_broadcast(symbol, raw_trades)

            # Rest on book if applicable
            if order.remaining > 0:
                if order.type == OrderType.limit:
                    book.add_limit(order)
                    self.order_symbol_index[order.order_id] = symbol
                elif order.type in (OrderType.market, OrderType.ioc, OrderType.fok):
                    # do not rest
                    pass

            self.log.info(
                "order_processed",
                extra={
                    "order_id": order.order_id,
                    "symbol": symbol,
                    "type": order.type.value,
                    "side": order.side.value,
                    "filled": str(order.quantity - order.remaining),
                    "remaining": str(order.remaining),
                },
            )
            return order, trades

    async def cancel_order(self, order_id: str) -> Optional[Order]:
        symbol = self.order_symbol_index.get(order_id)
        if not symbol:
            # Could be a trigger order
            for sym, lst in self.triggers.items():
                for i, od in enumerate(lst):
                    if od.order_id == order_id:
                        lst.pop(i)
                        self.log.info("order_cancelled_trigger", extra={"order_id": order_id, "symbol": sym})
                        return od
            return None
        async with self.locks[symbol]:
            book = self.books[symbol]
            removed = book.remove_order(order_id)
            if removed:
                self.order_symbol_index.pop(order_id, None)
                asyncio.create_task(self.ws.broadcast_marketdata(symbol, book))
                self.log.info("order_cancelled", extra={"order_id": order_id, "symbol": symbol})
            return removed

    def get_bbo(self, symbol: str):
        self._ensure_book(symbol)
        return self.books[symbol].bbo()

    def get_l2(self, symbol: str, depth: int = 10):
        self._ensure_book(symbol)
        snapshot = self.books[symbol].snapshot_l2(depth)
        snapshot["symbol"] = symbol
        snapshot["timestamp"] = now_ts()
        return snapshot

    def get_trades(self, symbol: str) -> List[Trade]:
        return list(self.recent_trades.get(symbol, []))

    def get_trades_since(self, symbol: str, last_trade_id: Optional[str]) -> Tuple[List[Trade], Optional[str]]:
        trades = self.get_trades(symbol)
        latest_id = trades[-1].trade_id if trades else None
        if not last_trade_id:
            return trades, latest_id
        filtered: List[Trade] = []
        seen = False
        for tr in trades:
            if seen:
                filtered.append(tr)
            elif tr.trade_id == last_trade_id:
                seen = True
        return (filtered if seen else trades, latest_id)

    async def process_triggers(self, symbol: str) -> None:
        """Check and activate advanced orders based on last trade price or BBO."""
        book = self.books[symbol]
        last = book.last_trade_price
        bid, ask = book.best_prices()
        to_activate: List[Order] = []
        for od in list(self.triggers[symbol]):
            if od.type == OrderType.stop:
                if od.side == Side.buy and ((last is not None and last >= od.stop_price) or (ask is not None and ask >= od.stop_price)):
                    to_activate.append(od)
                if od.side == Side.sell and ((last is not None and last <= od.stop_price) or (bid is not None and bid <= od.stop_price)):
                    to_activate.append(od)
            elif od.type == OrderType.stop_limit:
                if od.stop_price is None or od.price is None:
                    continue
                if od.side == Side.buy and ((last is not None and last >= od.stop_price) or (ask is not None and ask >= od.stop_price)):
                    # convert to limit
                    od.type = OrderType.limit
                    to_activate.append(od)
                if od.side == Side.sell and ((last is not None and last <= od.stop_price) or (bid is not None and bid <= od.stop_price)):
                    od.type = OrderType.limit
                    to_activate.append(od)
            elif od.type == OrderType.take_profit:
                if od.take_profit_price is None:
                    continue
                if od.side == Side.sell and ((last is not None and last >= od.take_profit_price) or (ask is not None and ask >= od.take_profit_price)):
                    to_activate.append(od)
                if od.side == Side.buy and ((last is not None and last <= od.take_profit_price) or (bid is not None and bid <= od.take_profit_price)):
                    to_activate.append(od)
        # Activate
        for od in to_activate:
            try:
                self.triggers[symbol].remove(od)
            except ValueError:
                pass
            # Submit activated order as market if stop without limit price
            if od.type == OrderType.stop and od.price is None:
                od.type = OrderType.market
            await self._submit_activated(symbol, od)

    async def _submit_activated(self, symbol: str, od: Order) -> None:
        # Internal submission without creating a new id
        async with self.locks[symbol]:
            book = self.books[symbol]
            raw_trades = book.match(od)
            trades = self._record_trades_and_broadcast(symbol, raw_trades)
            if od.remaining > 0 and od.type == OrderType.limit and od.price is not None:
                book.add_limit(od)
                self.order_symbol_index[od.order_id] = symbol
            self.log.info("order_triggered", extra={"order_id": od.order_id, "symbol": symbol, "type": od.type.value})

