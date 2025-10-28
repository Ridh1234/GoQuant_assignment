import asyncio
import random
import time
from decimal import Decimal

from app.engine import MatchingEngine
from app.models import OrderRequest, Side, OrderType


async def run_benchmark(n_orders: int = 10000) -> None:
    eng = MatchingEngine()

    # Seed book with liquidity
    for i in range(100):
        price = Decimal("30000") + Decimal(i)
        await eng.submit_order(OrderRequest(symbol="BTC-USD", side=Side.sell, type=OrderType.limit, quantity=Decimal("5"), price=price))
        bid_price = Decimal("29900") - Decimal(i)
        await eng.submit_order(OrderRequest(symbol="BTC-USD", side=Side.buy, type=OrderType.limit, quantity=Decimal("5"), price=bid_price))

    t0 = time.perf_counter()
    for i in range(n_orders):
        if i % 2 == 0:
            # Aggressive side
            await eng.submit_order(OrderRequest(symbol="BTC-USD", side=Side.buy, type=OrderType.market, quantity=Decimal("0.01")))
        else:
            # Passive
            p = Decimal("29950") + Decimal(random.randint(-50, 50))
            await eng.submit_order(OrderRequest(symbol="BTC-USD", side=Side.sell, type=OrderType.limit, quantity=Decimal("0.01"), price=p))
    dt = time.perf_counter() - t0
    print(f"Processed {n_orders} orders in {dt:.3f}s -> {n_orders/dt:.1f} orders/sec")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
