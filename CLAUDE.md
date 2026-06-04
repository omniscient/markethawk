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

> **Dev vs. live stack isolation:** `docker-compose up -d` auto-applies `docker-compose.override.yml` when present (local dev checkout), restoring bind-mounts and hot-reload. To run the baked-image stack without the override: `docker-compose -f docker-compose.yml up -d`.

> For manual (non-Docker) backend and frontend setup, migration commands, test commands, and pre-commit hook setup, see [DEVELOPMENT.md](DEVELOPMENT.md).

## Service Ports

| Service      | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3333         |
| Backend API | http://localhost:8000         |
| API Docs    | http://localhost:8000/docs    |
| Metrics     | http://localhost:8000/metrics |
| pgAdmin     | http://localhost:5050         |
| Flower      | http://localhost:5555         |
| Seq Logs    | http://localhost:5380         |
| Seq GELF    | udp://localhost:12201         |
| Prometheus  | http://localhost:9090         |
| Grafana     | http://localhost:3001         |
| Jaeger UI   | http://localhost:16686        |

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
api/          — Axios HTTP client layer (client.ts, scanner.ts, stocks.ts, news.ts, system.ts)
components/   — Reusable UI components (UniverseFormModal, UniverseDetailsModal, ScannerResults, etc.)
pages/        — Route-level views (Dashboard, Scanner, Universes, Journal, Alerts, Settings, etc.)
hooks/        — Custom React hooks
```

- **State**: React Query for all server state; local `useState` for UI state
- **API base URL**: configured via `VITE_API_TARGET` env variable
- **Charts**: Recharts for analytics, Lightweight Charts (TradingView-style) for price charts

## AI-Assisted Development

This repo uses two complementary systems for structured, agent-driven development. Both are pre-configured — see [Setup for AI Development](#setup-for-ai-development) to get ready.

### Superpowers (interactive, in-session)

The [superpowers plugin](https://github.com/claude-plugins-official/superpowers) drives brainstorming, planning, implementation, and review **inside your Claude Code session**. Use it when you want collaborative control over each phase.

Key skills (invoke with the `Skill` tool):
- `superpowers:brainstorming` — explore requirements before building anything
- `superpowers:writing-plans` — create step-by-step implementation plans
- `superpowers:executing-plans` / `superpowers:subagent-driven-development` — implement from a plan
- `superpowers:verification-before-completion` — verify before claiming done
- `superpowers:requesting-code-review` — review completed work

### Archon (autonomous, isolated)

[Archon](https://github.com/coleam00/Archon) runs workflows in isolated git worktrees — fire-and-forget pipelines that produce PRs. Use it for well-scoped work you trust to run autonomously.

Run workflows with: `archon workflow run <name> "description"` or ask Claude Code: *"Use archon to fix issue #3"*

Key workflows:
- `archon-fix-github-issue` — investigate + fix + PR + review
- `archon-idea-to-pr` — feature idea to reviewed PR
- `archon-smart-pr-review` — adaptive complexity PR review
- `archon-piv-loop` — guided plan-implement-validate with human-in-the-loop

Run `archon workflow list` for the full catalog.

### When to Use Which

| Scenario | Tool |
|----------|------|
| You want to shape the design interactively | Superpowers |
| Well-defined issue or feature, hands-off | Archon |
| Bug investigation needing your input | Superpowers |
| PR review | Archon (`archon-smart-pr-review`) |
| Multi-step feature with checkpoints | Superpowers or Archon PIV loop |

### Backlog

Work items are tracked as [GitHub Issues](https://github.com/omniscient/markethawk/issues) with priority labels (`priority: must-have`, `priority: should-have`) and size labels (`size: S/M/L`).

## Setup for AI Development

These steps get a fresh clone ready for both human and AI-driven development. Claude Code agents can follow these instructions directly — if someone says "set everything up", run through this list.

### Prerequisites

Verify these are installed (the system won't work without them):

```bash
docker --version          # Docker Desktop (includes Compose)
git --version             # Git
gh --version              # GitHub CLI — required for Archon issue/PR automation
bun --version             # Bun runtime — required for Archon CLI
claude --version          # Claude Code CLI
pre-commit --version      # Pre-commit hook framework
```

**Install anything missing:**
- Docker Desktop: https://www.docker.com/products/docker-desktop
- GitHub CLI: `winget install GitHub.cli` (Windows) / `brew install gh` (macOS)
- Bun: `irm bun.sh/install.ps1 | iex` (Windows) / `curl -fsSL https://bun.sh/install | bash` (macOS/Linux)
- Claude Code: `npm install -g @anthropic-ai/claude-code`
- pre-commit: `pip install pre-commit` (macOS/Linux/Windows)

### Step 1 — Authenticate GitHub CLI

```bash
gh auth login              # Follow the prompts — needs repo scope at minimum
gh auth status             # Confirm: "Logged in to github.com"
```

### Step 2 — Environment and services

```bash
cp .env.example .env       # Then fill in API keys — see ENV_VARIABLES.md
docker-compose up -d       # Start all services
docker-compose exec backend python -m alembic upgrade head  # Apply migrations
```

### Step 2.5 — Install pre-commit hooks

```bash
pre-commit install    # registers hooks in .git/hooks/pre-commit
```

### Step 3 — Verify Archon

Archon is pre-configured in this repo (`.archon/config.yaml` + `.claude/skills/archon/`).

```bash
archon version             # Should show version + database type
archon workflow list       # Should list 20+ workflows
```

If `archon` is not found, install and link from the Archon source repo:
```bash
cd <archon-repo> && bun install && cd packages/cli && bun link
```

### Step 4 — Verify Claude Code plugins

Open Claude Code in this repo. The project settings (`.claude/settings.json`) enable the superpowers and frontend-design plugins automatically. Verify skills are available:
- The skill list in the system prompt should include `superpowers:brainstorming`, `superpowers:writing-plans`, etc.
- The `archon` skill should appear for workflow delegation

### Step 5 — Validate the stack

```bash
curl -s http://localhost:8000/api/health | python -m json.tool   # Backend healthy
docker-compose ps                                                 # All containers Up
```

You're ready. Pick an issue from the [backlog](https://github.com/omniscient/markethawk/issues) and start building.

## Dark Factory (Autonomous Docker Development)

An isolated Docker container that autonomously develops features from GitHub issues. Runs Claude Code inside a sandboxed environment with no host access. Preview stacks and the dark-factory container deliberately omit `docker-compose.override.yml` and always run baked images — do not rely on bind-mount behavior in autonomous workflows.

### Quick Start

```bash
# Build the dark factory image (first time only)
docker compose --profile factory build dark-factory

# Start a new feature from a GitHub issue
docker compose --profile factory run --rm dark-factory "Fix issue #3"

# Iterate after reviewing the preview and leaving feedback
docker compose --profile factory run --rm dark-factory "Continue issue #3"

# Tear down preview and merge when satisfied
docker compose --profile factory run --rm dark-factory "Close issue #3"
```

### Prerequisites

Add to `.archon/.env` (not `.env` — keep AI credentials separate):
```
# Option A: Use your Claude Max subscription (recommended — no per-token cost)
# Generate with: claude setup-token
CLAUDE_CODE_OAUTH_TOKEN=<token-from-setup-token>

# Option B: Use Anthropic API key (pay-per-token)
# ANTHROPIC_API_KEY=sk-ant-...

GH_TOKEN=ghp_...
```

The `GH_TOKEN` should be a fine-grained PAT scoped to `omniscient/markethawk` with `repo` permissions.

### Preview Environments

Each issue gets its own preview stack on deterministic ports:
- Frontend: `http://localhost:1{NN}33` (e.g. `:10333` for issue #3)
- Backend: `http://localhost:1{NN}80` (e.g. `:10380` for issue #3)

Preview URLs are included in the PR body. The preview persists after the factory exits so you can browse and test.

### Architecture

See [dark factory design spec](docs/superpowers/specs/2026-05-02-dark-factory-design.md) for the full architecture, security model, and container topology.

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

Symbol index `symbolindex.json` + dependency graph `codeindex.json` are maintained in-repo (committed artifacts).
Use the `lookup_symbol` MCP tool before grepping for any function or class.
Use `get_impact` before modifying a high-blast file (see `docs/codeindex-hotspots.md` for the current list).

### Local visualization

```bash
# One-time install (developer machines only — never add to backend/requirements.txt)
pip install "git+https://github.com/scheidydude/codeindex.git"

# Launch interactive viz on http://localhost:8080
bash scripts/codeindex.sh
```

## Further Reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — service topology, scan execution flow, module map, Celery tasks
- [docs/database-schema.md](docs/database-schema.md) — auto-generated database schema ERD and indices
- [DEVELOPMENT.md](DEVELOPMENT.md) — full local setup, Docker commands, Seq/Flower/pgAdmin usage, troubleshooting
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — annotated file tree
- [ENV_VARIABLES.md](ENV_VARIABLES.md) — all env vars with defaults and descriptions
- [POLYGON_RATE_LIMITS.md](POLYGON_RATE_LIMITS.md) — API plan tiers, rate limits, key endpoints
- [deployment-guide.md](deployment-guide.md) — production hardening, backup, upgrade
- [docs/codeindex-hotspots.md](docs/codeindex-hotspots.md) — high-blast hotspots (auto-updated by the factory)

## Agent Skills

### Issue tracker

GitHub Issues on `omniscient/markethawk`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
