# OKComputer — Custom Stock Scanner System

A full-stack stock scanning platform that identifies pre-market volume spikes and unusual trading patterns. Built for active traders who need fast, configurable scans with a professional UI.

## Features

- **Pre-Market Volume Spike Detection** — Flags stocks with volume >4x the 20-day average between 4:00–9:30 AM ET
- **Price Gap Analysis** — Detects gaps >1% from previous close with volume confirmation
- **Low Volume Preceding Days** — Finds stocks with compressed volume before a spike
- **Stock Universes** — Create and manage named groups of tickers for targeted scanning
- **Futures Monitoring** — Track ES, NQ, and other futures contracts with rollover awareness
- **News Catalyst Parsing** — Batch-analyzes recent headlines to surface catalysts alongside scan results
- **Trade Journal** — Log and review trades with structured entry/exit data
- **Edge Explorer** — Analyze historical scanner hit rates and outcome distributions
- **WebSocket Live Data** — Real-time price and volume streaming
- **Scheduled Scans** — Celery Beat runs scans automatically on market open

## Scanner Criteria

| Criterion | Threshold |
|---|---|
| Pre-market volume spike | > 4× 20-day average |
| Price gap | > 1% from prior close |
| Minimum pre-market volume | 100,000 shares |
| Minimum average daily volume | 500,000 shares |
| Low-volume preceding days | < 0.5× average (last 3 days) |

Session boundaries are computed in `America/New_York` and mapped to UTC for storage.

## Tech Stack

**Backend**: FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 15 · Redis 7 · Celery  
**Frontend**: React 18 · TypeScript · Vite · Tailwind CSS · React Query · Recharts · Lightweight Charts  
**Market Data**: Polygon.io (primary) · Interactive Brokers via IB Gateway (secondary)  
**Logging**: Seq (structured, centralized)

## Architecture

```
┌──────────────────────┐       ┌──────────────────────┐       ┌────────────────────┐
│  React 18 Frontend   │◄─────►│  FastAPI Backend      │◄─────►│  PostgreSQL 15     │
│  Vite · TypeScript   │  HTTP │  Python · Async       │       │  Redis 7           │
└──────────────────────┘       └──────────────────────┘       └────────────────────┘
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                   ┌────────────┐  ┌────────────┐  ┌────────────┐
                   │ Polygon.io │  │ IB Gateway │  │  Celery /  │
                   │ Market Data│  │  (Docker)  │  │  Beat      │
                   └────────────┘  └────────────┘  └────────────┘
```

### Backend (`backend/app/`)

```
core/           — Config, DB session, Celery setup, error tracking
models/         — SQLAlchemy ORM models (ScannerEvent, ScannerRun, ScannerConfig,
                  StockUniverse, MonitoredStock, StockAggregate, FuturesAggregate,
                  NewsArticle, Trade, TickerReference, UniverseQualityReport …)
routers/        — FastAPI route handlers (scanner, universe, stocks, news,
                  live_data, futures, journal, health, system)
schemas/        — Pydantic request/response models
services/       — Business logic (scanner, stock_data, discovery_service,
                  futures_data, chart_indicators, catalyst_parser,
                  journal_service, websocket_manager, data_quality …)
providers/      — External data integrations (Polygon, IBKR, base interface, bulk ops)
tasks.py        — Celery background/scheduled tasks
```

### Frontend (`frontend/src/`)

```
api/            — Axios HTTP client layer
components/     — Reusable UI (UniverseFormModal, ScannerResults, …)
pages/          — Dashboard, Scanner, Universes, PreMarketMovers,
                  EdgeExplorer, Journal, Alerts, Settings, StockDetailPage
hooks/          — Custom React hooks
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A [Polygon.io](https://polygon.io) API key
- (Optional) Interactive Brokers credentials for live broker data

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in POLYGON_API_KEY, POSTGRES_PASSWORD, SECRET_KEY,
# PGADMIN_DEFAULT_EMAIL/PASSWORD, and SEQ_ADMIN_PASSWORD_HASH at minimum.
```

Generate the Seq password hash:
```bash
echo 'YourPassword' | docker run --rm -i datalust/seq config hash
```

### 2. Start all services

```bash
docker-compose up -d
```

IB Gateway takes ~60 seconds on first startup while IBC authenticates. The backend waits for it automatically.

### 3. Access the application

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| pgAdmin | http://localhost:5050 |
| Flower (Celery) | http://localhost:5555 |
| Seq (Logs) | http://localhost:5380 |

### Manual Setup (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

> See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed local setup, service connection instructions, and troubleshooting.

## Database Migrations

After changing any SQLAlchemy model:

```bash
cd backend
python -m alembic revision --autogenerate -m "describe_the_change"
python -m alembic upgrade head
```

## Running Tests

```bash
cd backend
python -m pytest                   # all tests
python -m pytest tests/api -v      # API tests only
python -m pytest --cov             # with coverage report
```

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `POLYGON_API_KEY` | Yes | Polygon.io market data |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `POSTGRES_DB/USER/PASSWORD` | Yes | Used by the postgres container |
| `SECRET_KEY` | Yes | JWT tokens and sessions |
| `PGADMIN_DEFAULT_EMAIL/PASSWORD` | Yes | pgAdmin login |
| `SEQ_ADMIN_PASSWORD_HASH` | Yes | Seq log viewer login |
| `REDIS_URL` | No | Defaults to `redis://redis:6379/0` |
| `ENVIRONMENT` | No | `development` / `production` (default: `development`) |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / … (default: `INFO`) |
| `IB_USERNAME/PASSWORD` | No | IB Gateway auto-login credentials |
| `IB_TRADING_MODE` | No | `paper` or `live` (default: `paper`) |
| `IBKR_HOST/PORT/CLIENT_ID` | No | Backend connection to IB Gateway |

## Useful Docker Commands

```bash
docker-compose logs -f backend        # stream backend logs
docker-compose exec backend bash      # shell into backend container
docker-compose restart backend        # restart one service
docker-compose down                   # stop everything (data volumes preserved)
docker-compose down -v                # stop and delete all volumes
```

## Documentation

| Document | Contents |
|----------|---------|
| [DEVELOPMENT.md](DEVELOPMENT.md) | Full local setup, Docker commands, service access, debugging, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Service topology, scan execution flow, module map, database models, error tracking |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | Annotated file tree of the entire repository |
| [ENV_VARIABLES.md](ENV_VARIABLES.md) | Complete environment variable reference with defaults and usage |
| [POLYGON_RATE_LIMITS.md](POLYGON_RATE_LIMITS.md) | Polygon.io plan tiers, rate limits, key endpoints, and sync strategy |
| [deployment-guide.md](deployment-guide.md) | Production hardening checklist, backup, and upgrade procedure |

---

**Disclaimer**: This tool is for research and personal use only. Not financial advice. Trading involves substantial risk of loss.
