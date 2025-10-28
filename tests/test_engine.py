import asyncio
from decimal import Decimal

import pytest

from app.engine import MatchingEngine
from app.models import OrderRequest, Side, OrderType


@pytest.mark.asyncio
async def test_engine_basic_match():
    eng = MatchingEngine()
    # Add resting ask
    o1, _ = await eng.submit_order(OrderRequest(symbol="ETH-USD", side=Side.sell, type=OrderType.limit, quantity=Decimal("5"), price=Decimal("2000")))
    # Aggressive buy
    o2, trades = await eng.submit_order(OrderRequest(symbol="ETH-USD", side=Side.buy, type=OrderType.market, quantity=Decimal("2")))
    assert len(trades) == 1
    assert trades[0].price == Decimal("2000")
    assert trades[0].quantity == Decimal("2")

    # Remaining on book is 3
    l2 = eng.get_l2("ETH-USD")
    assert l2["asks"][0]["price"] == "2000"
    assert l2["asks"][0]["quantity"] == "3.00000000"
