from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from .models import Order, Side, Level, BBO
from .utils import now_ts, as_decimal, quantize_8


@dataclass
class PriceLevel:
    price: Decimal
    queue: Deque[Order]

    def total_quantity(self) -> Decimal:
        qty = Decimal("0")
        for o in self.queue:
            qty += o.remaining
        return qty


class OrderBook:
    """Order book with price-time priority for a single symbol."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: SortedDict[Decimal, PriceLevel] = SortedDict()
        self.asks: SortedDict[Decimal, PriceLevel] = SortedDict()
        self.order_index: Dict[str, Tuple[Side, Decimal]] = {}
        self.last_trade_price: Optional[Decimal] = None

    # Basic operations
    def _get_side_book(self, side: Side) -> SortedDict:
        return self.bids if side == Side.buy else self.asks

    def _best_bid(self) -> Optional[PriceLevel]:
        if not self.bids:
            return None
        price = self.bids.peekitem(-1)[0]
        return self.bids[price]

    def _best_ask(self) -> Optional[PriceLevel]:
        if not self.asks:
            return None
        price = self.asks.peekitem(0)[0]
        return self.asks[price]

    def best_prices(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        bid = self.bids.peekitem(-1)[0] if self.bids else None
        ask = self.asks.peekitem(0)[0] if self.asks else None
        return bid, ask

    def add_limit(self, order: Order) -> None:
        book = self._get_side_book(order.side)
        assert order.price is not None, "Limit order must have price"
        level = book.get(order.price)
        if level is None:
            level = PriceLevel(order.price, deque())
            book[order.price] = level
        level.queue.append(order)
        self.order_index[order.order_id] = (order.side, order.price)

    def remove_order(self, order_id: str) -> Optional[Order]:
        idx = self.order_index.get(order_id)
        if not idx:
            return None
        side, price = idx
        book = self._get_side_book(side)
        level = book.get(price)
        if not level:
            self.order_index.pop(order_id, None)
            return None
        removed: Optional[Order] = None
        new_queue: Deque[Order] = deque()
        while level.queue:
            o = level.queue.popleft()
            if o.order_id == order_id:
                removed = o
                continue
            new_queue.append(o)
        level.queue = new_queue
        if not level.queue:
            del book[price]
        self.order_index.pop(order_id, None)
        return removed

    def bbo(self) -> BBO:
        bid_level = self._best_bid()
        ask_level = self._best_ask()
        bid = None if not bid_level else Level(bid_level.price, bid_level.total_quantity())
        ask = None if not ask_level else Level(ask_level.price, ask_level.total_quantity())
        return BBO(symbol=self.symbol, bid=bid, ask=ask, timestamp=now_ts())

    def snapshot_l2(self, depth: int = 10) -> Dict[str, List[Dict[str, str]]]:
        bids: List[Dict[str, str]] = []
        asks: List[Dict[str, str]] = []

        # Bids: highest to lowest
        for price, level in reversed(self.bids.items()):
            qty = level.total_quantity()
            if qty > 0:
                bids.append({"price": str(price), "quantity": str(quantize_8(qty))})
            if len(bids) >= depth:
                break
        # Asks: lowest to highest
        for price, level in self.asks.items():
            qty = level.total_quantity()
            if qty > 0:
                asks.append({"price": str(price), "quantity": str(quantize_8(qty))})
            if len(asks) >= depth:
                break
        return {"bids": bids, "asks": asks}

    # Matching helpers
    def _crossable(self, incoming: Order) -> bool:
        bid, ask = self.best_prices()
        if incoming.type == incoming.type.market:
            # any liquidity on opposite side
            if incoming.side == Side.buy:
                return ask is not None
            else:
                return bid is not None
        # for limit-like orders
        if incoming.price is None:
            return False
        if incoming.side == Side.buy:
            return ask is not None and incoming.price >= ask
        else:
            return bid is not None and incoming.price <= bid

    def match(self, incoming: Order) -> List[Tuple[Order, Order, Decimal, Decimal]]:
        """Match the incoming order against the book.

        Returns list of tuples: (maker_order, taker_order, price, quantity)
        """
        trades: List[Tuple[Order, Order, Decimal, Decimal]] = []
        while incoming.remaining > 0 and self._crossable(incoming):
            if incoming.side == Side.buy:
                best = self._best_ask()
            else:
                best = self._best_bid()
            if best is None:
                break
            # Price is execution price at best level
            price = best.price
            # FIFO
            if not best.queue:
                # should not happen but clean up empty level
                book = self._get_side_book(Side.sell if incoming.side == Side.buy else Side.buy)
                del book[best.price]
                continue
            maker = best.queue[0]
            qty = min(incoming.remaining, maker.remaining)
            incoming.remaining -= qty
            maker.remaining -= qty
            trades.append((maker, incoming, price, qty))
            self.last_trade_price = price
            if maker.remaining <= 0:
                # remove maker from queue
                best.queue.popleft()
                self.order_index.pop(maker.order_id, None)
                if not best.queue:
                    # remove price level entirely
                    opp_book = self._get_side_book(Side.sell if incoming.side == Side.buy else Side.buy)
                    opp_book.pop(price, None)
        return trades
