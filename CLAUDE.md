# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This System Does

Full-stack stock scanning platform that identifies pre-market volume spikes and unusual trading patterns. The core scanner detects stocks with >4x average volume pre-market, price gaps >1%, and minimum liquidity thresholds.

## Tech Stack

**Backend**: FastAPI + SQLAlchemy 2.0 (sync) + PostgreSQL + Redis + Celery  
**Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + React Query  
**Market Data**: Polygon.io API (primary), Interactive Brokers (ib_insync)  
**Logging**: Seq (structured/centralized)

## Commands

```bash
docker-compose up -d                        # Start all services
docker-compose logs -f backend              # Stream backend logs
docker-compose exec backend bash            # Shell into backend
docker-compose restart backend              # Restart one service
```

> **Dev vs. live stack isolation:** `docker-compose up -d` auto-applies `docker-compose.override.yml` when present (local dev checkout), restoring bind-mounts and hot-reload. To run the baked-image stack without the override: `docker-compose -f docker-compose.yml up -d`. Full per-service breakdown, manual (non-Docker) setup, ports, tests, and pre-commit hooks: [DEVELOPMENT.md](DEVELOPMENT.md).

**Ports** (full table in [DEVELOPMENT.md](DEVELOPMENT.md#service-urls)): Frontend `:3333`, Backend `:8000`, API docs `:8000/docs`.

## Architecture

### Backend (`backend/app/`)

```
core/         — Config, DB session, Celery setup, error tracking
models/       — SQLAlchemy ORM models
routers/      — FastAPI route handlers (health, scanner, universe, stocks, news, live_data, journal, futures)
schemas/      — Pydantic request/response models
services/     — Business logic (scanner.py, stock_data.py, discovery_service.py, chart_indicators.py)
providers/    — External API integrations (Polygon, IBKR, base provider interface)
tasks/        — Celery background/scheduled tasks (sync.py, scanning.py, trading.py, quality.py)
```

**Key models**: `ScannerEvent`, `ScannerRun`, `ScannerConfig`, `StockUniverse`, `StockUniverseTicker`, `MonitoredStock`, `StockAggregate`, `FuturesAggregate`, `NewsArticle`, `Trade`

**Scanner logic** is in `services/scanner.py` — `ScannerService.calculate_day_metrics()` handles pre-market (4:00–9:30 AM EST), regular, and post-market sessions.

**Providers** in `providers/` follow a base interface (`base.py`). `ibkr.py` wraps ib_insync; `massive.py` handles bulk data operations.

### Frontend (`frontend/src/`)

```
api/          — Axios HTTP client layer (client.ts, scanner/ (facade + sub-modules), universe.ts, stocks.ts, news.ts, system.ts)
components/   — Reusable UI components (UniverseFormModal, UniverseDetailsModal, ScannerResults, etc.)
pages/        — Route-level views (Dashboard, Scanner, Universes, Journal, Alerts, Settings, etc.)
hooks/        — Custom React hooks
```

- **State**: React Query for all server state; local `useState` for UI state
- **API base URL**: configured via `VITE_API_TARGET` env variable
- **Charts**: Recharts for analytics, Lightweight Charts (TradingView-style) for price charts

## AI-Assisted Development

Three systems, all pre-configured. See [docs/ai-development.md](docs/ai-development.md) for setup and full detail.

- **Superpowers** (interactive, in-session) — brainstorming, planning, implementation, and review via the `Skill` tool (`superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:verification-before-completion`, etc.).
- **Archon** (autonomous, isolated worktrees) — fire-and-forget workflows that produce PRs: `archon workflow run <name> "description"` or *"Use archon to fix issue #3"*. Run `archon workflow list` for the catalog.
- **Dark Factory** (autonomous Docker) — sandboxed container that builds features from GitHub issues with per-issue preview stacks. **Extracted to [omniscient/dark-factory](https://github.com/omniscient/dark-factory)**: the scheduler/harness code, bench suite, and its CI live there; this repo carries only the target-side adapter (`.factory/adapter.yaml` + `.factory/hooks/`) and agent memory (`.archon/memory/`). The production scheduler runs from that repo's `deploy/docker-compose.yml`.

Work is tracked as [GitHub Issues](https://github.com/omniscient/markethawk/issues) with `priority:` (`must-have`/`should-have`) and `size:` (`S/M/L`) labels. Factory harness changes (prompts, DAG nodes, gate thresholds) are gated by the replay bench suite in the dark-factory repo (`bench/run_suite.sh` there — set `BENCH_TARGET_DIR` at this repo's checkout).

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

## Codeindex

Symbol index `symbolindex.json` + dependency graph `codeindex.json` are **generated artifacts,
gitignored and regenerated on demand** — they are not committed (they rebuild from source in
~6s in the factory, ~25s locally). Regenerate with `scripts/codeindex.sh`, or let the factory's
`update-codeindex` startup pass do it before `implement`. Only `docs/codeindex-hotspots.md` (the
human-readable hotspot list) is committed. When the codeindex MCP server is available, prefer
`lookup_symbol` over grepping for a function/class and `get_impact` before touching a high-blast
file (see `docs/codeindex-hotspots.md`); otherwise fall back to grep/Read.
Local interactive visualization: see [DEVELOPMENT.md](DEVELOPMENT.md#codeindex-local-visualization).

## Repowise (code-health + git signals)

Adopted alongside codeindex (see `docs/repowise-pilot-eval.md`). Use for health scoring and hotspot queries that codeindex doesn't cover.

```bash
bash scripts/repowise.sh          # rebuild index + open dashboard
~/.venvs/repowise/bin/repowise health              # top worst files by biomarker score
~/.venvs/repowise/bin/repowise health --file PATH  # per-file deep-dive
~/.venvs/repowise/bin/repowise risk main..HEAD     # change risk score for a branch
```

Wire the MCP server in `.claude/settings.local.json` (see eval doc) to use `get_health`, `get_overview`, and `get_risk` tools in-session. Index lives in `.repowise/` (gitignored except `config.yaml`).

## Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — service topology, scan execution flow, module map, Celery tasks
- [docs/database-schema.md](docs/database-schema.md) — auto-generated database schema ERD and indices
- [DEVELOPMENT.md](DEVELOPMENT.md) — full local setup, Docker commands, ports, Seq/Flower/pgAdmin usage, troubleshooting
- [docs/ai-development.md](docs/ai-development.md) — superpowers, Archon, Dark Factory: setup and usage
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — annotated file tree
- [ENV_VARIABLES.md](ENV_VARIABLES.md) — all env vars with defaults and descriptions
- [POLYGON_RATE_LIMITS.md](POLYGON_RATE_LIMITS.md) — API plan tiers, rate limits, key endpoints
- [deployment-guide.md](deployment-guide.md) — production hardening, backup, upgrade
- [docs/codeindex-hotspots.md](docs/codeindex-hotspots.md) — high-blast hotspots (auto-updated by the factory)

## Agent Skills

- **Issue tracker** — GitHub Issues on `omniscient/markethawk`. Epics group their tickets as native GitHub sub-issues (not just body checklists). See `docs/agents/issue-tracker.md`.
- **Triage labels** — five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.
- **Domain docs** — single-context layout: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
- **Architecture review** — `/architecture-review` regenerates the comparable Architecture & Quality report series in `docs/architecture-reviews/` (frozen 16-dimension rubric + DORA + code-health sections). See `.claude/skills/architecture-review/SKILL.md`.
- **Memory contract** — stable schema, lifecycle rules, and scoping matrix for `.archon/memory/*.md`. See `docs/agents/dark-factory-memory-contract.md`.
- **Memory v2 operator guide** — rollout/fallback/maintenance runbook for the flat-file memory system. See `docs/agents/dark-factory-memory-v2.md`.
