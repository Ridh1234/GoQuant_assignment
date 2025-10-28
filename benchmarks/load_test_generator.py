import asyncio
import random
from decimal import Decimal

from app.engine import MatchingEngine
from app.models import OrderRequest, Side, OrderType


async def generate_load(eng: MatchingEngine, symbol: str, n: int = 10000):
    sides = [Side.buy, Side.sell]
    types = [OrderType.limit, OrderType.market, OrderType.ioc, OrderType.fok]
    for _ in range(n):
        side = random.choice(sides)
        typ = random.choice(types)
        qty = Decimal("0.01")
        price = None
        if typ != OrderType.market:
            base = Decimal("30000")
            delta = Decimal(random.randint(-100, 100))
            price = base + delta
        await eng.submit_order(OrderRequest(symbol=symbol, side=side, type=typ, quantity=qty, price=price))


async def main():
    eng = MatchingEngine()
    await generate_load(eng, "BTC-USD", 10000)


if __name__ == "__main__":
    asyncio.run(main())
