# ADR-007: Live Scanner as a Separate Container

**Date**: 2026-05-28  
**Status**: Accepted

## Context

The live scanner streams real-time 5-second IBKR bars for watchlist symbols and fires intraday alerts. It depends on `ib_insync`, which runs its own asyncio event loop via `IB.run()`. Two options were considered for where this code lives:

**A. Inside the backend FastAPI process** — Reuse the existing container. Share the database session and Celery client directly. Downside: `ib_insync` runs a blocking event loop that conflicts with the FastAPI/uvicorn event loop. Threading workarounds are fragile; IBKR disconnects or reconnects can block the ASGI server.

**B. Separate container (`live-scanner`)** — Runs as `python -m live_scanner.main`, fully isolated from the ASGI process. Has its own asyncio loop, dedicated IBKR `clientId` (5), and connects to the same PostgreSQL and Redis instances as the backend. Communicates outbound via Redis pub/sub channels.

The IBKR API assigns work to `clientId` values. Sharing a `clientId` between two processes causes conflicts and dropped subscriptions. A dedicated clientId for the live scanner is required regardless of process topology; extracting it to a separate container makes this a natural boundary.

## Decision

**Option B**: `live-scanner` runs as a separate container with its own process and dedicated IBKR `clientId: 5`.

Inbound data path: IBKR bars → `IBKRLiveAdapter` → `BarAggregator` (accumulates 5 s bars into 1 min bars) → `LivePublisher`.

Outbound communication: `LivePublisher` writes to Redis pub/sub channels (`stock_updates:{symbol}:second`, `stock_updates:{symbol}:minute`, `watchlist:live_data`, `watchlist:alerts`). The FastAPI backend consumes these channels via its WebSocket endpoints. `LivePublisher` also writes `ScannerEvent` rows directly to PostgreSQL using the same `SessionLocal` as the backend (via `asyncio.to_thread`).

Alert evaluation (notification rules, auto-trade rules) is handed off to Celery by queuing `evaluate_scanner_alerts` via `celery_app.send_task()` — same path as the historical scanner.

## Consequences

- `live-scanner` container must be running for real-time data to flow to the frontend. If it stops, the WebSocket endpoints return stale data until it reconnects.
- `clientId: 5` is reserved by convention. Adding a third IBKR-connected service requires allocating a new clientId and documenting it.
- DB writes from the live scanner go through `asyncio.to_thread` (sync SQLAlchemy in a thread pool) rather than async SQLAlchemy. This is consistent with ADR-004's short-term sync decision and inherits the same migration path.
- Redis pub/sub is fire-and-forget; if the backend WebSocket consumer is not running, messages are lost. This is acceptable for real-time price data where staleness is the natural recovery.
