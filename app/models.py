from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


class Side(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"
    ioc = "ioc"
    fok = "fok"
    stop = "stop"
    stop_limit = "stop_limit"
    take_profit = "take_profit"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal
    remaining: Decimal
    price: Optional[Decimal] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    client_order_id: Optional[str] = None
    # Advanced order triggers
    stop_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    # Internal fields
    user_id: Optional[str] = None

    def is_active(self) -> bool:
        return self.remaining > 0


@dataclass
class Trade:
    trade_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    aggressor_side: Side
    maker_order_id: str
    taker_order_id: str
    timestamp: str
    maker_fee: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0")


@dataclass
class Level:
    price: Decimal
    quantity: Decimal


@dataclass
class BBO:
    symbol: str
    bid: Optional[Level]
    ask: Optional[Level]
    timestamp: str


class OrderRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "symbol": "BTC-USD",
        "side": "buy",
        "type": "limit",
        "quantity": "0.5",
        "price": "35000",
        "client_order_id": "abc-123",
    }})
    symbol: str = Field(..., examples=["BTC-USD"])
    side: Side
    type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    client_order_id: Optional[str] = None
    stop_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None


class OrderResponse(BaseModel):
    order_id: str
    status: str
    filled_quantity: Decimal
    remaining_quantity: Decimal
    trades: List[Dict[str, Any]] = []


class CancelResponse(BaseModel):
    order_id: str
    status: str


class TradeSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    trade_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    aggressor_side: Side
    maker_order_id: str
    taker_order_id: str
    timestamp: str
    maker_fee: Decimal = Decimal("0")
    taker_fee: Decimal = Decimal("0")


class OrderBookView(BaseModel):
    symbol: str
    bids: List[Level]
    asks: List[Level]
    timestamp: str


class BboView(BaseModel):
    symbol: str
    bid: Optional[Level] = None
    ask: Optional[Level] = None
    timestamp: str


class RecentTradesView(BaseModel):
    symbol: str
    trades: List[TradeSchema]
