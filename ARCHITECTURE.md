# GoQuant Matching Engine - System Architecture Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Design](#architecture-design)
3. [Data Structures](#data-structures)
4. [Matching Algorithm](#matching-algorithm)
5. [API Specifications](#api-specifications)
6. [Design Trade-offs](#design-trade-offs)
7. [Performance Analysis](#performance-analysis)

## System Overview

The GoQuant Matching Engine is a high-performance, Python-based cryptocurrency trading system inspired by Regulation NMS principles. It implements strict price-time priority matching, prevents trade-throughs, and provides both REST APIs and real-time market data streaming capabilities.

### Key Features

- **Core Order Types**: Market, Limit, IOC (Immediate-or-Cancel), FOK (Fill-or-Kill)
- **Advanced Order Types**: Stop, Stop-Limit, Take-Profit with trigger mechanisms
- **Price-Time Priority**: Strict FIFO ordering within price levels
- **No Trade-Through**: Prevents execution at worse prices when better liquidity exists
- **Maker/Taker Economics**: Configurable fee structure with negative maker rebates
- **Real-time Data**: WebSocket, SSE, and polling-based market data distribution
- **Persistence**: JSON-based state management with automatic recovery
- **High Performance**: 2,800+ orders/second single-threaded throughput

## Architecture Design

### Component Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   FastAPI Web  │    │  MatchingEngine │    │   OrderBook     │
│   Server        │◄──►│  Core           │◄──►│   (Per Symbol)  │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ WebSocket/SSE   │    │   Persistence   │    │  Price Levels   │
│ Manager         │    │   Layer         │    │  (SortedDict)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Core Components

#### 1. FastAPI Web Server (`app/api.py`)
- **Responsibility**: HTTP API endpoints, WebSocket management, static file serving
- **Design Pattern**: Factory pattern with dependency injection
- **Key Features**:
  - RESTful order management endpoints
  - Real-time WebSocket connections for market data
  - Server-Sent Events (SSE) for streaming data
  - CORS-enabled for frontend integration
  - Built-in frontend serving

#### 2. MatchingEngine (`app/engine.py`)
- **Responsibility**: Central coordination of all trading operations
- **Design Pattern**: Singleton per symbol with async coordination
- **Key Features**:
  - Per-symbol order book management
  - Advanced order trigger processing
  - Fee calculation and trade recording
  - Concurrent access control via asyncio.Lock
  - Automatic state persistence

#### 3. OrderBook (`app/orderbook.py`)
- **Responsibility**: Single-symbol order matching and book management
- **Design Pattern**: Price-level aggregation with FIFO queues
- **Key Features**:
  - SortedDict-based price levels for O(log n) operations
  - FIFO queues at each price level
  - Efficient best bid/offer (BBO) tracking
  - L2 market data snapshot generation

#### 4. Data Models (`app/models.py`)
- **Responsibility**: Type-safe data structures and API schemas
- **Design Pattern**: Dataclasses for internal models, Pydantic for API validation
- **Key Features**:
  - Comprehensive order and trade representations
  - Decimal precision for financial calculations
  - Enum-based type safety for sides and order types

## Data Structures

### Order Book Implementation

The order book uses a sophisticated two-level data structure optimized for both space and time complexity:

```python
# Top level: Symbol -> OrderBook mapping
books: Dict[str, OrderBook]

# Within each OrderBook:
class OrderBook:
    bids: SortedDict[Decimal, PriceLevel]  # Price -> Level mapping
    asks: SortedDict[Decimal, PriceLevel]  # Price -> Level mapping
    order_index: Dict[str, Tuple[Side, Decimal]]  # Order ID -> (Side, Price)
```

#### PriceLevel Structure
```python
@dataclass
class PriceLevel:
    price: Decimal
    queue: Deque[Order]  # FIFO queue of orders at this price
```

### Design Rationale

1. **SortedDict for Price Levels**:
   - **Advantages**: O(log n) insertion, deletion, and best price lookup
   - **Trade-off**: Higher memory overhead vs. simple dict, but critical for price-time priority
   - **Alternative Considered**: Heap-based priority queue (rejected due to complexity of updates)

2. **Deque for FIFO Queues**:
   - **Advantages**: O(1) append/popleft operations for strict time priority
   - **Trade-off**: O(n) deletion for arbitrary order removal
   - **Alternative Considered**: Linked list (rejected due to implementation complexity)

3. **Order Index**:
   - **Purpose**: Fast O(1) order lookup for cancellations
   - **Storage**: Maps order_id to (side, price) for efficient removal
   - **Memory Cost**: ~100 bytes per order (acceptable for target order volumes)

### Memory Efficiency Analysis

For a typical order book with 1000 price levels and 10 orders per level:
- SortedDict overhead: ~8KB per side
- Orders: ~10KB per side (1KB per order × 10)
- Index: ~2KB
- **Total per symbol**: ~38KB
- **For 100 symbols**: ~3.8MB (well within reasonable limits)

## Matching Algorithm

### Core Matching Logic

The matching algorithm implements strict price-time priority with no trade-through protection:

```python
def match(self, incoming: Order) -> List[Tuple[Order, Order, Decimal, Decimal]]:
    trades = []
    while incoming.remaining > 0 and self._crossable(incoming):
        # Get best contra-side level
        best_level = self._best_ask() if incoming.side == Side.buy else self._best_bid()
        
        # Execute at maker's price (prevents trade-through)
        execution_price = best_level.price
        
        # FIFO matching within price level
        maker = best_level.queue[0]
        quantity = min(incoming.remaining, maker.remaining)
        
        # Record trade and update quantities
        trades.append((maker, incoming, execution_price, quantity))
        # ... quantity updates and cleanup
    
    return trades
```

### Algorithm Steps

1. **Cross Check**: Verify incoming order crosses the spread
2. **Price-Time Priority**: Always match against earliest order at best price
3. **Execution Price**: Use maker's price to prevent trade-through
4. **Quantity Matching**: Fill minimum of available quantities
5. **Cleanup**: Remove filled orders and empty price levels
6. **Iteration**: Continue until no more crosses possible

### Advanced Order Processing

#### Stop Orders
- **Trigger Condition**: Last trade price or BBO crosses stop price
- **Activation**: Convert to market order (or limit if stop-limit)
- **Monitoring**: Continuous trigger evaluation after each trade

#### FOK (Fill-or-Kill) Pre-validation
```python
def _precheck_fok(self, side: Side, price: Optional[Decimal], qty: Decimal) -> bool:
    needed = qty
    # Walk the book to verify sufficient liquidity
    for price_level in opposite_side_levels:
        if price_limit and price_level.price > price_limit:
            break
        for order in price_level.queue:
            needed -= order.remaining
            if needed <= 0:
                return True  # Sufficient liquidity exists
    return False  # Insufficient liquidity
```

### Trade-Through Prevention

The system prevents trade-through by:
1. Always executing at the maker's posted price
2. Requiring incoming orders to fill at best available price before going deeper
3. Rejecting limit orders that would execute worse than their limit price

## API Specifications

### Core REST Endpoints

#### Order Submission
```http
POST /orders
Content-Type: application/json

{
    "symbol": "BTC-USD",
    "side": "buy|sell",
    "type": "market|limit|ioc|fok|stop|stop_limit|take_profit",
    "quantity": "1.5",
    "price": "35000",  // Optional for market orders
    "stop_price": "34500",  // For stop orders
    "take_profit_price": "36000",  // For take-profit orders
    "client_order_id": "user-123"  // Optional
}
```

**Response:**
```json
{
    "order_id": "ord_12345",
    "status": "accepted",
    "filled_quantity": "1.0",
    "remaining_quantity": "0.5",
    "trades": [
        {
            "trade_id": "tr_67890",
            "price": "35000",
            "quantity": "1.0",
            "aggressor_side": "buy",
            "maker_order_id": "ord_11111",
            "taker_order_id": "ord_12345",
            "timestamp": "2025-10-28T12:15:51Z",
            "maker_fee": "-0.035",  // Negative = rebate
            "taker_fee": "0.875"
        }
    ]
}
```

#### Market Data Endpoints

1. **Level 2 Order Book**
```http
GET /orderbook/{symbol}?depth=10
```

2. **Best Bid/Offer**
```http
GET /bbo/{symbol}
```

3. **Trade History**
```http
GET /trades/{symbol}
```

4. **Polling Endpoint** (Optimized for frontends)
```http
GET /poll/{symbol}?depth=10&since=tr_67890
```

### Real-time Data Streams

#### WebSocket Market Data
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/marketdata');
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Handle L2 updates
};
```

#### Server-Sent Events
```javascript
const source = new EventSource('/stream/trades');
source.onmessage = (event) => {
    const trade = JSON.parse(event.data);
    // Handle real-time trades
};
```

## Design Trade-offs

### 1. Programming Language Choice: Python

**Advantages:**
- Rapid development and extensive financial libraries
- Excellent asyncio support for concurrent operations
- Rich ecosystem (FastAPI, Pydantic, SortedContainers)
- Easy debugging and maintenance

**Trade-offs:**
- Lower raw performance vs. C++/Rust/Go
- GIL limitations (mitigated by asyncio design)
- Higher memory usage per operation

**Justification:** For the target throughput (1000+ orders/sec), Python provides the best development velocity while meeting performance requirements.

### 2. Data Structure Choices

#### SortedDict vs. Alternatives

**SortedDict (Chosen):**
- O(log n) operations for price-level management
- Clean API for range queries and best price lookup
- Well-tested library implementation

**Alternatives Considered:**
- **Heap**: O(log n) insert, but O(n) arbitrary delete
- **Skip List**: Similar performance, higher implementation complexity
- **B-Tree**: Better for very large books, overkill for typical crypto volumes

#### In-Memory vs. Database Storage

**In-Memory (Chosen):**
- Microsecond-level latency for order operations
- Simple state management and recovery
- Sufficient durability for target use case

**Trade-offs:**
- State loss on unclean shutdown (mitigated by periodic persistence)
- Memory consumption grows with order volume
- Single-node limitation (acceptable for demo/medium scale)

### 3. Concurrency Model

#### Asyncio vs. Threading

**Asyncio (Chosen):**
- Single-threaded execution eliminates race conditions
- Excellent I/O concurrency for API handling
- Simpler reasoning about state consistency

**Trade-offs:**
- CPU-bound operations can block event loop
- Single-core utilization limits scaling
- More complex debugging for async code

**Mitigation Strategy:**
- Per-symbol locks enable future multi-threaded scaling
- CPU-intensive operations (fee calculations) are optimized
- Async context managers ensure proper resource cleanup

### 4. Persistence Strategy

#### JSON Snapshots vs. Event Sourcing

**JSON Snapshots (Chosen):**
- Simple implementation and debugging
- Fast startup/shutdown cycles
- Human-readable state inspection

**Event Sourcing (Alternative):**
- Complete audit trail and replay capability
- Better for regulatory compliance
- More complex implementation

**Hybrid Approach:** The system logs all trades (partial event sourcing) while using snapshots for order book state.

### 5. API Design Philosophy

#### REST + Polling vs. Full WebSocket

**REST + Polling (Chosen):**
- Better compatibility with firewalls/proxies
- Simpler client implementation
- Graceful degradation and reconnection

**Full WebSocket (Alternative):**
- Lower latency for real-time updates
- Reduced bandwidth for frequent updates
- More complex connection management

**Implementation:** System provides both approaches, with polling as the primary method and WebSocket as enhancement.

## Performance Analysis

### Benchmark Results

Based on the performance benchmark (`benchmarks/benchmark_performance.py`):

- **Throughput**: 2,812 orders/second (10,000 orders in 3.56 seconds)
- **Order Mix**: 50% market orders (aggressive), 50% limit orders (passive)
- **Hardware**: Single-threaded execution on modern CPU
- **Memory Usage**: <50MB for full benchmark including logging

### Performance Characteristics

#### Time Complexity Analysis

| Operation | Complexity | Notes |
|-----------|------------|-------|
| Order Insertion | O(log n) | SortedDict price level lookup + O(1) deque append |
| Order Cancellation | O(log n) | Index lookup + O(n) deque scan + cleanup |
| Matching | O(m × log n) | m = fill quantity, n = price levels |
| BBO Retrieval | O(1) | SortedDict peek operations |
| L2 Snapshot | O(k) | k = requested depth |

#### Space Complexity

- **Per Order**: ~100 bytes (Order object + index entry)
- **Per Price Level**: ~200 bytes + orders
- **Total Memory**: Linear in number of active orders

#### Bottleneck Analysis

1. **Order Cancellation**: O(n) scan of deque is the primary bottleneck
   - **Mitigation**: Could use OrderedDict within price levels for O(1) removal
   - **Trade-off**: Increased memory overhead and insertion cost

2. **JSON Serialization**: Persistence operations can be expensive
   - **Current**: Asynchronous with 5-second intervals
   - **Optimization**: Could use binary formats (pickle, msgpack)

3. **Logging Overhead**: Structured logging adds ~10% overhead
   - **Production**: Could use async logging or sampling

### Scaling Considerations

#### Horizontal Scaling
- **Symbol Sharding**: Each symbol can run on separate processes/nodes
- **Read Replicas**: Market data can be distributed from read-only copies
- **Load Balancing**: Orders can be routed by symbol to appropriate nodes

#### Vertical Scaling
- **Multi-threading**: Per-symbol locks enable thread-pool execution
- **Native Extensions**: Critical paths could use Cython/Rust extensions
- **Memory Optimization**: Custom data structures for higher density

#### Network Performance
- **WebSocket Compression**: Can reduce bandwidth by 60-80%
- **Binary Protocols**: Protocol Buffers/MessagePack for lower latency
- **CDN Integration**: Static market data can be cached globally

### Production Readiness Gaps

1. **Risk Management**: No position limits, order size validation, or circuit breakers
2. **Monitoring**: Basic logging present, needs metrics and alerting
3. **High Availability**: Single-point-of-failure, needs clustering
4. **Security**: No authentication, authorization, or rate limiting
5. **Compliance**: No regulatory reporting or audit trail persistence

Each gap represents a focused development effort that could extend the current foundation without architectural changes.

## Conclusion

The GoQuant Matching Engine demonstrates a well-architected, high-performance trading system that balances simplicity with functionality. The design choices prioritize development velocity and maintainability while achieving strong performance characteristics suitable for cryptocurrency trading applications.

The modular architecture and comprehensive test coverage provide a solid foundation for extending functionality, optimizing performance, or adapting to different market structures. The system successfully implements industry-standard matching logic while remaining accessible for educational and development purposes.