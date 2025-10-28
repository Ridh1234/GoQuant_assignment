# Eraser.io Architecture Diagram Prompt

## Prompt for GoQuant Matching Engine Architecture Flow Chart

Please create a comprehensive architecture flow chart diagram for a high-performance cryptocurrency matching engine with the following specifications:

### System Overview
Create a flow chart showing the complete architecture of a Python-based cryptocurrency matching engine called "GoQuant" that processes 2,800+ orders per second with the following key components:

### Main Components to Include:

#### 1. **API Layer** (Top Level)
- FastAPI Web Server (HTTP/WebSocket endpoint)
- REST API endpoints: POST /orders, DELETE /orders/{id}, GET /orderbook/{symbol}, GET /trades/{symbol}, GET /poll/{symbol}
- WebSocket endpoints: /ws/marketdata, /ws/trades
- SSE endpoints: /stream/marketdata, /stream/trades
- Static file serving for frontend
- CORS middleware

#### 2. **Core Engine** (Central Hub)
- MatchingEngine class (main orchestrator)
- Per-symbol asyncio.Lock for concurrency control
- Order routing and validation
- Fee calculation (maker rebate -1 bps, taker fee +2.5 bps)
- Trade recording and broadcasting
- Trigger order management (Stop, Stop-Limit, Take-Profit)

#### 3. **Order Book Layer** (Per Symbol)
- OrderBook instances (one per trading symbol like BTC-USD)
- SortedDict for bid/ask price levels
- PriceLevel with FIFO deques for time priority
- Order index for O(1) cancellation lookup
- Best bid/offer (BBO) tracking
- L2 snapshot generation

#### 4. **Data Structures** (Detail Box)
- Order objects with Decimal precision
- Trade objects with maker/taker attribution
- PriceLevel with FIFO queues
- Symbol-to-OrderBook mapping
- Order ID indexing system

#### 5. **Real-time Streaming** (Right Side)
- WebSocketManager for fan-out broadcasting
- Multiple protocol support (WebSocket, SSE, Polling)
- Connection management and heartbeat
- Message queuing for disconnected clients
- Auto-reconnection logic

#### 6. **Persistence Layer** (Bottom)
- JSON-based state snapshots
- Periodic background saves (5-second intervals)
- Automatic recovery on startup
- Order book reconstruction
- Trade history preservation

#### 7. **Frontend Interface** (Left Side)
- Self-contained HTML/CSS/JavaScript trading UI
- Real-time order book display
- Order entry forms (all order types)
- Live trade feed
- Connection status indicators

### Data Flow Arrows:
1. **Incoming Order Flow**: Client → API → Engine → OrderBook → Matching → Trade Generation
2. **Market Data Flow**: OrderBook → Engine → WebSocketManager → Multiple Clients
3. **Persistence Flow**: Engine → Persistence Layer (bidirectional for save/load)
4. **Real-time Updates**: Trades → WebSocketManager → WebSocket/SSE/Polling clients
5. **Trigger Processing**: Trade Events → Engine → Trigger Evaluation → Order Activation

### Order Types to Show:
- Market Orders (immediate execution)
- Limit Orders (price-time priority queue)
- IOC (Immediate-or-Cancel)
- FOK (Fill-or-Kill with pre-validation)
- Stop Orders (trigger-based)
- Stop-Limit Orders (dual-phase)
- Take-Profit Orders (profit target)

### Performance Characteristics to Highlight:
- 2,812 orders/second throughput
- Sub-millisecond latency
- O(log n) price level operations
- O(1) best bid/offer lookup
- Per-symbol concurrency isolation

### Technical Implementation Details:
- Python 3.11 with asyncio
- SortedContainers library for price levels
- FastAPI for REST/WebSocket APIs
- Decimal arithmetic for precision
- Structured logging throughout
- Pydantic for data validation

### Visual Style Preferences:
- Use different colors for each major component layer
- Show data flow with directional arrows
- Include timing annotations (e.g., "5s intervals" for persistence)
- Use box groupings for related components
- Show both synchronous and asynchronous operations
- Highlight the critical path for order processing
- Use icons or symbols for different order types

### Specific Flows to Illustrate:
1. **New Order Submission**: API → Validation → Engine → OrderBook → Matching → Response
2. **Real-time Market Data**: OrderBook Changes → Engine → Broadcast → Multiple Clients
3. **Advanced Order Trigger**: Trade Event → Trigger Check → Order Activation → Matching
4. **System Recovery**: Startup → Load State → Reconstruct OrderBooks → Resume Operations
5. **WebSocket Connection**: Client Connect → Register → Receive Updates → Heartbeat Management

### Labels and Annotations:
- Show key performance metrics (2,812 ops/sec, <1ms latency)
- Include technology stack labels (FastAPI, SortedDict, asyncio)
- Mark critical sections (matching algorithm, price-time priority)
- Show concurrency boundaries (per-symbol locks)
- Indicate data persistence points

Please create a professional, detailed flow chart that clearly shows how orders flow through the system, how market data is distributed in real-time, and how all components interact to create a high-performance trading system. The diagram should be suitable for both technical documentation and presentation to stakeholders.