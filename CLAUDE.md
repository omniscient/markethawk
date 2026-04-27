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
celery -A app.core.celery_app:celery_app worker --loglevel=info  # Run worker
celery -A app.core.celery_app:celery_app beat                    # Run scheduler
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
| Frontend    | http://localhost:3333         |
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

## Development Rules

### Validating Changes Before Committing

**Backend changes** must be validated live before committing:
1. Confirm the backend reloaded: `docker-compose logs backend --tail=10`
2. Hit new/changed endpoints with `curl` to verify correct responses
3. For migrations: confirm `alembic upgrade head` ran without errors
4. Only then commit

```bash
# Example validation for a new endpoint
curl -s http://localhost:8000/api/system/config | python -m json.tool
curl -s -X PATCH http://localhost:8000/api/system/config \
  -H "Content-Type: application/json" -d '{"key": "value"}' | python -m json.tool
```

**Frontend changes**: `npx tsc --noEmit` must pass before committing. For UI behaviour changes, verify in the browser as well.

### New Models

When adding a SQLAlchemy model:
1. Create the file in `backend/app/models/`
2. Import and add it to `backend/app/models/__init__.py`
3. Generate and apply the migration (see below)

## Database Migrations

After changing any SQLAlchemy model, create and apply a migration:
```bash
python -m alembic revision --autogenerate -m "describe_the_change"
python -m alembic upgrade head
```

The `alembic/versions/` directory contains all migration files.

## Environment Variables

Requires a `.env` file in the project root (Docker Compose reads it automatically). See [ENV_VARIABLES.md](ENV_VARIABLES.md) for the complete reference.

Key variables: `POLYGON_API_KEY`, `DATABASE_URL`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `SEQ_ADMIN_PASSWORD_HASH`, `PGADMIN_DEFAULT_EMAIL/PASSWORD`, `REDIS_URL`, `IBKR_HOST/PORT/CLIENT_ID`.

## Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — service topology, scan execution flow, module map, Celery tasks
- [DEVELOPMENT.md](DEVELOPMENT.md) — full local setup, Docker commands, Seq/Flower/pgAdmin usage, troubleshooting
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — annotated file tree
- [ENV_VARIABLES.md](ENV_VARIABLES.md) — all env vars with defaults and descriptions
- [POLYGON_RATE_LIMITS.md](POLYGON_RATE_LIMITS.md) — API plan tiers, rate limits, key endpoints
- [deployment-guide.md](deployment-guide.md) — production hardening, backup, upgrade
