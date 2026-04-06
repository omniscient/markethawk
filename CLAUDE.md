# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This System Does

Full-stack stock scanning platform that identifies pre-market volume spikes and unusual trading patterns. The core scanner detects stocks with >4x average volume pre-market, price gaps >1%, and minimum liquidity thresholds.

## Tech Stack

**Backend**: FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Redis + Celery  
**Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + React Query  
**Market Data**: Polygon.io API (primary), Interactive Brokers (ib_insync)  
**Logging**: Seq (structured/centralized)

## Commands

### Docker (recommended for full stack)
```bash
docker-compose up -d                        # Start all services
docker-compose logs -f backend              # Stream backend logs
docker-compose exec backend bash            # Shell into backend
docker-compose restart backend              # Restart one service
```

### Backend (manual)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload               # Dev server
python -m pytest                            # All tests
python -m pytest tests/api -v              # API tests only
python -m pytest --cov                      # With coverage
python -m alembic upgrade head              # Apply migrations
python -m alembic revision --autogenerate -m "description"  # New migration
celery -A app.tasks worker --loglevel=info  # Run worker
celery -A app.tasks beat                    # Run scheduler
```

### Frontend (manual)
```bash
cd frontend
npm install
npm run dev       # Dev server at http://localhost:3000
npm run build     # Production build
npm run lint      # ESLint
```

## Service Ports

| Service      | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3000         |
| Backend API | http://localhost:8000         |
| API Docs    | http://localhost:8000/docs    |
| pgAdmin     | http://localhost:5050         |
| Flower      | http://localhost:5555         |
| Seq Logs    | http://localhost:5380         |

## Architecture

### Backend (`backend/app/`)

```
core/         — Config, DB session, Celery setup, error tracking
models/       — SQLAlchemy ORM models
routers/      — FastAPI route handlers (health, scanner, universe, stocks, news, live_data, journal, futures)
schemas/      — Pydantic request/response models
services/     — Business logic (scanner.py, stock_data.py, discovery_service.py, chart_indicators.py)
providers/    — External API integrations (Polygon, IBKR, base provider interface)
tasks.py      — Celery background/scheduled tasks
```

**Key models**: `ScannerEvent`, `ScannerRun`, `ScannerConfig`, `StockUniverse`, `StockUniverseTicker`, `MonitoredStock`, `StockAggregate`, `FuturesAggregate`, `NewsArticle`, `Trade`

**Scanner logic** is in `services/scanner.py` — `ScannerService.calculate_day_metrics()` handles pre-market (4:00–9:30 AM EST), regular, and post-market sessions.

**Providers** in `providers/` follow a base interface (`base.py`). `ibkr.py` wraps ib_insync; `massive.py` handles bulk data operations.

### Frontend (`frontend/src/`)

```
api/          — Axios HTTP client layer (client.ts, scanner.ts, stocks.ts, news.ts, system.ts)
components/   — Reusable UI components (UniverseFormModal, UniverseDetailsModal, ScannerResults, etc.)
pages/        — Route-level views (Dashboard, Scanner, Universes, Journal, Alerts, Settings, etc.)
hooks/        — Custom React hooks
```

- **State**: React Query for all server state; local `useState` for UI state
- **API base URL**: configured via `VITE_API_TARGET` env variable
- **Charts**: Recharts for analytics, Lightweight Charts (TradingView-style) for price charts

## Database Migrations

After changing any SQLAlchemy model, create and apply a migration:
```bash
python -m alembic revision --autogenerate -m "describe_the_change"
python -m alembic upgrade head
```

The `alembic/versions/` directory contains all migration files. New migration `39cb3da5ccb4_add_asset_class_to_universe_models.py` is pending.

## Environment Variables

Requires a `.env` file in the project root (Docker Compose reads it automatically).

| Variable          | Purpose                              |
|-------------------|--------------------------------------|
| `POLYGON_API_KEY` | **Required** — Polygon.io market data |
| `DATABASE_URL`    | PostgreSQL connection string          |
| `REDIS_URL`       | Redis connection string               |
| `IBKR_HOST/PORT/CLIENT_ID` | Interactive Brokers connection |
| `SEQ_SERVER_URL`  | Seq logging endpoint                  |

## Current Uncommitted Work

The working tree has changes across multiple files covering:
- `models/monitored_stock.py`, `models/stock_universe_ticker.py` — model changes
- `providers/__init__.py`, `providers/base.py`, `providers/ibkr.py`, `providers/massive.py` — IBKR + generic data management additions (untested per recent commit)
- `routers/futures.py`, `routers/universe.py` — router updates
- `schemas/stock.py` — schema changes
- `services/discovery_service.py` — discovery service updates
- `frontend/src/api/scanner.ts`, `components/UniverseDetailsModal.tsx`, `components/UniverseFormModal.tsx` — frontend changes
- Pending migration: `39cb3da5ccb4_add_asset_class_to_universe_models.py`
