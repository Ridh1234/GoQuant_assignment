from decimal import Decimal

from app.orderbook import OrderBook
from app.models import Order, Side, OrderType


def test_orderbook_bbo_and_match():
    ob = OrderBook("BTC-USD")
    # Add two ask levels
    a1 = Order(order_id="a1", symbol="BTC-USD", side=Side.sell, type=OrderType.limit, price=Decimal("100"), quantity=Decimal("2"), remaining=Decimal("2"))
    a2 = Order(order_id="a2", symbol="BTC-USD", side=Side.sell, type=OrderType.limit, price=Decimal("101"), quantity=Decimal("3"), remaining=Decimal("3"))
    ob.add_limit(a1)
    ob.add_limit(a2)

    bbo = ob.bbo()
    assert bbo.ask is not None and bbo.ask.price == Decimal("100")

    # Incoming buy market 2.5 -> should fill 2 at 100 and 0.5 at 101
    buy = Order(order_id="b1", symbol="BTC-USD", side=Side.buy, type=OrderType.market, price=None, quantity=Decimal("2.5"), remaining=Decimal("2.5"))
    trades = ob.match(buy)
    assert len(trades) == 2
    assert trades[0][2] == Decimal("100") and trades[0][3] == Decimal("2")
    assert trades[1][2] == Decimal("101") and trades[1][3] == Decimal("0.5")
    assert buy.remaining == Decimal("0")
