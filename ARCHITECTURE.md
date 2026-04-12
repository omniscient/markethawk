# Architecture

## Service Topology

All services run as Docker containers on the `stockscanner-network` bridge network. Inter-service communication uses container names as hostnames.

```
                         ┌─────────────────────────────────────────┐
                         │          stockscanner-network            │
                         │                                          │
  Browser ──HTTP:3000──> │ frontend ──HTTP──> backend:8000          │
                         │                       │                  │
                         │                  asyncpg ──> postgres:5432
                         │                  aioredis ──> redis:6379  │
                         │                  ib_insync ──> ib-gateway:4002
                         │                  HTTPS ──> api.polygon.io │
                         │                  HTTP ──> seq:5341        │
                         │                                          │
                         │ celery-worker ──> (same: DB, Redis, IBKR, Polygon)
                         │ celery-beat ──> redis:6379 (broker only) │
                         │ flower:5555 ──> redis:6379               │
                         │ pgadmin:5050 ──> postgres:5432           │
                         │ seq:5380/5341 ──> seq_data volume        │
                         └─────────────────────────────────────────┘
```

## Scan Execution Flow

A full pre-market scan proceeds as follows:

1. **Trigger** — Celery Beat fires `run_scanner` at a scheduled time, or a user POSTs to `/api/scanner/run`.
2. **Session classification** — `ScannerService.calculate_day_metrics()` (`services/scanner.py`) determines the active market session (pre-market 04:00–09:30, regular, post-market) using `ZoneInfo("America/New_York")`, then maps session boundaries to UTC for database queries.
3. **Ticker list** — The service resolves the universe's ticker list from `StockUniverseTicker` records.
4. **Parallel data fetch** — Tickers are fetched from Polygon in batches. An `asyncio.Semaphore(10)` bounds concurrency to 10 in-flight requests; `asyncio.gather()` parallelises within that bound.
5. **Batch enrichment** — `_get_batch_enrichment_data()` fetches all `TickerReference` metadata for the full batch in a single DB round-trip (eliminates per-ticker N+1 queries).
6. **News catalyst analysis** — `CatalystParser.analyze_batch()` (`services/catalyst_parser.py`) queries the `NewsArticle` table once for a 72-hour window covering all tickers, then matches articles to tickers in memory.
7. **Criteria evaluation** — Each ticker is evaluated against the five scanner criteria (see README). Passing tickers produce `ScannerEvent` records.
8. **Persistence** — A `ScannerRun` row is written with metadata; `ScannerEvent` rows are written for each hit.
9. **Delivery** — The frontend polls `/api/scanner/results` via React Query. Live pushes are broadcast through `services/websocket_manager.py`.

## Backend Module Map

### Core (`app/core/`)

| File | Responsibility |
|------|---------------|
| `config.py` | `Settings` class; reads all env vars with typed defaults. Accessed via `get_settings()` (cached). |
| `database.py` | Async SQLAlchemy engine and session factory (`AsyncSession`). `get_db()` dependency. |
| `celery_app.py` | Celery instance; beat schedule definitions (scan times, sync intervals). |
| `error_tracking.py` | `ErrorTracker` protocol; `SeqErrorTracker` and `StdoutErrorTracker` implementations; MD5-based `ErrorId` generation. |

### Services (`app/services/`)

| File | Responsibility |
|------|---------------|
| `scanner.py` | Core scan orchestration: `ScannerService`, `calculate_day_metrics()`, semaphore-bounded async fetch. |
| `stock_data.py` | Historical OHLCV fetch, gap percentage calculation, per-ticker session flag logic. |
| `discovery_service.py` | Bulk ticker sync from Polygon: paginated reference data, rate-limit-aware batching. |
| `catalyst_parser.py` | Batch 72-hour news analysis for catalyst detection. Joins articles to tickers in memory. |
| `futures_data.py` | Futures contract data (ES, NQ, etc.), rollover date tracking. |
| `chart_indicators.py` | Technical indicator computation (e.g., VWAP, moving averages) for chart endpoints. |
| `journal_service.py` | Trade journal CRUD operations. |
| `websocket_manager.py` | WebSocket connection pool; `broadcast()` to all connected clients. |
| `normalization.py` | Data normalization helpers (price/volume units, split adjustments). |
| `data_quality.py` | Quality checks and `UniverseQualityReport` generation. |
| `stats.py` | Aggregate statistics helpers for dashboard metrics. |
| `event_helpers.py` | Utility functions for `ScannerEvent` construction and querying. |

### Providers (`app/providers/`)

| File | Responsibility |
|------|---------------|
| `base.py` | `MarketDataProvider` abstract interface (fetch bars, tickers, news). |
| `massive.py` | Polygon.io bulk operations: large-batch ticker sync, aggregate backfill. |
| `ibkr.py` | `ib_insync`-based Interactive Brokers provider. Connects to the `ib-gateway` container on port 4002. |

### Routers (`app/routers/`)

| File | Endpoints |
|------|-----------|
| `scanner.py` | `/api/scanner/run`, `/api/scanner/results`, `/api/scanner/history` |
| `universe.py` | `/api/universe/*` — CRUD for stock universes and memberships |
| `stocks.py` | `/api/stocks/*` — historical data, ticker search, stock details |
| `news.py` | `/api/news/*` — news articles and preferences |
| `live_data.py` | `/api/live/*` — WebSocket and real-time quote endpoints |
| `futures.py` | `/api/futures/*` — futures contracts, aggregates, rollovers |
| `journal.py` | `/api/journal/*` — trade journal entries |
| `health.py` | `GET /health` — liveness probe |
| `system.py` | `/api/system/*` — configuration, status |

### Database Models (`app/models/`)

| Model | Table | Purpose |
|-------|-------|---------|
| `ScannerRun` | `scanner_runs` | One row per scan execution; stores timing, config snapshot, hit count |
| `ScannerEvent` | `scanner_events` | One row per ticker that passed all criteria in a run |
| `ScannerConfig` | `scanner_configs` | Saved scanner parameter sets |
| `StockUniverse` | `stock_universes` | Named groups of tickers (e.g., "Russell 2000 Small Caps") |
| `StockUniverseTicker` | `stock_universe_tickers` | Universe membership records |
| `MonitoredStock` | `monitored_stocks` | Per-ticker tracking state and metadata |
| `StockAggregate` | `stock_aggregates` | Cached historical OHLCV bars from Polygon |
| `TickerReference` | `ticker_reference` | Polygon metadata cache (market cap, sector, CIK, FIGI, etc.) |
| `NewsArticle` | `news_articles` | Cached news from Polygon used by `CatalystParser` |
| `NewsPreference` | `news_preferences` | User news source/topic preferences |
| `StockMetric` | `stock_metrics` | Computed daily metrics (relative volume, gap %, etc.) |
| `StockSplit` | `stock_splits` | Split history for volume normalization |
| `FuturesContract` | `futures_contracts` | Contract specifications (symbol, multiplier, exchange) |
| `FuturesAggregate` | `futures_aggregates` | Futures OHLCV bars |
| `FuturesRollover` | `futures_rollovers` | Roll dates and front-month mapping |
| `MarketHoliday` | `market_holidays` | NYSE/NASDAQ holiday calendar |
| `Trade` | `trades` | Trade journal entries |
| `UniverseQualityReport` | `universe_quality_reports` | Data quality audit results per universe |

## Frontend Architecture

### State Management

- **Server state**: React Query (`@tanstack/react-query`). All API calls go through the `api/` layer.
- **UI state**: local `useState`. No global client-side state store.
- **WebSocket**: managed in `hooks/` with reconnect logic.

### Pages

| Page | Route | Purpose |
|------|-------|---------|
| `Dashboard` | `/` | System metrics, recent alerts, market status |
| `Scanner` | `/scanner` | Run scans, view results, configure criteria |
| `PreMarketMovers` | `/pre-market` | Real-time pre-market volume leaders |
| `Universes` | `/universes` | Create and manage stock universes |
| `EdgeExplorer` | `/edge` | Historical scanner hit rates and outcome distributions |
| `Journal` | `/journal` | Trade journal entry and review |
| `Alerts` | `/alerts` | Alert configuration and history |
| `StockDetailPage` | `/stocks/:ticker` | Per-ticker chart, metrics, and news |
| `Settings` | `/settings` | System configuration |

### Charting Libraries

- **Recharts** — analytics charts (bar, line, area) on Dashboard and EdgeExplorer.
- **Lightweight Charts** (TradingView) — price and volume OHLCV charts on StockDetailPage.

## Error Tracking System

All unhandled FastAPI exceptions flow through a global handler (`app/main.py`) that:

1. MD5-hashes the Python stack trace to produce a deterministic `ErrorId` (format: `ERR-xxxxxxxx`). The same code path always produces the same ID.
2. Ships a structured CLEF log event to Seq at `http://seq:5341` via HTTP.
3. Mirrors output to Python's stdlib logger (stdout) as an always-on fallback.
4. Returns to the client:
   - `ENVIRONMENT=development` → `{message, error_id, detail, stack_trace}`
   - `ENVIRONMENT=production` → `{message, error_id}` (internals hidden)

The frontend `GlobalErrorToast` component listens for `server-error` window events (fired by the shared Axios client on any HTTP 5xx). The "Trace in Seq" button navigates to `http://localhost:5380` pre-filtered to that `ErrorId`.

To add a new error tracking backend (Sentry, Datadog, Loki):
1. Implement the `ErrorTracker` protocol in `app/core/error_tracking.py`.
2. Register it in `ErrorTrackerFactory._build()` keyed to an env var.
3. The `error_id` API contract is unchanged — no frontend changes needed.

## IB Gateway Integration

The `ib-gateway` container (`ghcr.io/gnzsnz/ib-gateway:stable`) uses IBC for headless IBKR authentication. It exposes:

- **4002** — paper trading socket API (default, `IB_TRADING_MODE=paper`)
- **4001** — live trading socket (opt-in, `IB_TRADING_MODE=live`)

`READ_ONLY_API=yes` by default — order submission via the API is intentionally disabled.

The backend connects via `ib_insync` through `app/providers/ibkr.py`. The `ib-gateway` container has a health check that allows up to 3 minutes (18 retries × 10 seconds) for initial IBC authentication. First startup typically takes 45–60 seconds.

## Celery Task Architecture

Defined in `app/tasks.py`, scheduled via `app/core/celery_app.py`:

| Task | Trigger | Purpose |
|------|---------|---------|
| `run_scanner` | Beat schedule / on-demand | Main scan execution |
| `refresh_universe_stocks` | Beat schedule | Refresh stock data for active universes |
| `sync_fundamental_data` | Beat schedule (weekly) | Bulk ticker reference sync from Polygon |
| `update_daily_metrics` | Beat schedule (daily, after close) | Compute and store daily metric snapshots |

Redis is used as both the Celery broker and result backend. Worker and beat run as separate containers so the scheduler doesn't compete with task execution.
