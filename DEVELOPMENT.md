# Development Guide

## Prerequisites

- Docker Desktop (includes Docker Compose)
- Git Bash or WSL for shell commands
- A [Polygon.io](https://polygon.io) API key
- [GitHub CLI](https://cli.github.com/) (`gh`) — required for Archon workflows to create issues, PRs, and post reviews
- [Bun](https://bun.sh/) — required for Archon CLI
- (Optional) Interactive Brokers credentials for live broker data

> **AI-assisted development:** This repo uses superpowers (Claude Code plugin) and Archon (autonomous workflow engine) for structured development, plus the Dark Factory autonomous pipeline. See [docs/ai-development.md](docs/ai-development.md) for full setup instructions.

## First-Time Setup

### 1. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:
- `POLYGON_API_KEY` — your Polygon.io key
- `POSTGRES_PASSWORD` — choose a strong password
- `DATABASE_URL` — update to match `POSTGRES_PASSWORD`
- `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` — your pgAdmin login
- `SEQ_ADMIN_PASSWORD_HASH` — generate with the command below

```bash
# Generate Seq password hash (replace 'YourPassword')
echo 'YourPassword' | docker run --rm -i datalust/seq config hash
```

Paste the output (starting with `$2a$`) as `SEQ_ADMIN_PASSWORD_HASH` in `.env`.

For IB Gateway (optional):
```bash
IB_USERNAME=your_ibkr_username
IB_PASSWORD=your_ibkr_password
IB_TRADING_MODE=paper   # paper or live
```

### 2. Start all services

```bash
docker-compose up -d
```

On first run, IB Gateway takes 45–60 seconds to authenticate with IBKR servers. The backend waits for it automatically. Watch progress with:

```bash
docker-compose logs -f ib-gateway
```

### 3. Apply database migrations

The backend container applies pending migrations at startup. To run manually:

```bash
docker-compose exec backend python -m alembic upgrade head
```

## Service URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3333 | — |
| Backend API | http://localhost:8000 | — |
| Swagger / API Docs | http://localhost:8000/docs | — |
| Metrics | http://localhost:8000/metrics | — |
| pgAdmin | http://localhost:5050 | Values from `PGADMIN_DEFAULT_EMAIL/PASSWORD` in `.env` |
| Flower | http://localhost:5555 | None (dev only) |
| Seq Logs | http://localhost:5380 | Admin password used to generate `SEQ_ADMIN_PASSWORD_HASH` |
| Seq GELF ingest | udp://localhost:12201 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3001 | — |
| Jaeger UI | http://localhost:16686 | — |

## Docker Commands

```bash
# Start all services
docker-compose up -d

# Stop all services (data volumes preserved)
docker-compose down

# Stop and delete all volumes (wipes database and log data)
docker-compose down -v

# Rebuild images after Dockerfile or dependency changes
docker-compose up -d --build

# Stream logs
docker-compose logs -f backend
docker-compose logs -f celery-worker
docker-compose logs -f ib-gateway

# Restart a single service
docker-compose restart backend

# Check container health and port status
docker-compose ps

# Open a shell in a container
docker-compose exec backend bash
docker-compose exec postgres psql -U postgres -d stockscanner
docker-compose exec redis redis-cli
```

## Dev vs. live stack isolation

The base `docker-compose.yml` runs **baked images** — source bind-mounts are absent so that editing files on the host or switching git branches cannot change the behavior of a running stack. This is the mode used by CI, preview environments, and the live trading stack.

`docker-compose.override.yml` is committed to the repo and is **automatically merged** by Docker Compose whenever both files are present (the standard Docker Compose behavior). In a local dev checkout this means `docker-compose up -d` restores bind-mounts and hot-reload commands as if the split never happened.

**Services covered by the override (the six that lose their bind-mount in the base file):**
- `backend` — restores `./backend:/app:ro` and adds `--reload` to uvicorn
- `celery-worker` — restores `./backend:/app:ro` and the watchfiles hot-reload command
- `celery-beat` — restores `./backend:/app:ro`
- `live-scanner` — restores `./backend:/app:ro`
- `frontend` — restores `./frontend:/app` and `/app/node_modules`, switches command back to `npm run dev`
- `backlog-scheduler` — restores `.:/workspace/project:ro`

Services with no source bind-mount (`flower`, `forecast-worker`, and all infrastructure services) are unchanged in both files.

**Run the stable baked-image stack without the override (live/CI mode):**
```bash
docker-compose -f docker-compose.yml up -d
```

**Force a full rebuild before starting (e.g. after dependency changes):**
```bash
docker-compose -f docker-compose.yml up -d --build
```

## Manual Setup (without Docker)

Use this if you need to run backend or frontend outside Docker, for example to attach a debugger.

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Point to a running PostgreSQL instance (must match POSTGRES_* vars in .env)
export DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/stockscanner"
export POLYGON_API_KEY="your-key"

python -m alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # Dev server at http://localhost:3333
npm run build      # Production build
npm run lint       # ESLint check
```

The frontend reads `VITE_API_TARGET` to locate the backend. When running manually it defaults to `http://localhost:8000`.

## Code Quality (Pre-commit Hooks)

[pre-commit](https://pre-commit.com/) enforces ruff lint, ruff format, and ESLint before every
commit. It is a **host-side** tool — install it once per machine, not inside Docker.

```bash
pip install pre-commit   # one-time host install
pre-commit install       # register hooks in .git/hooks/pre-commit (run once per clone)
```

After `pre-commit install`, every `git commit` automatically:
1. Runs **ruff lint** on staged Python files in `backend/` — auto-fixes fixable violations and re-stages the file
2. Runs **ruff format** on staged Python files in `backend/` — applies consistent formatting
3. Runs **ESLint** (`npm run lint`) when any `.ts/.tsx/.js/.jsx` file is staged

Note: the ESLint hook scans the entire `frontend/` tree, so Python-only commits will still
trigger it. This is intentional — it catches lint regressions before they accumulate.

If a hook modifies a file (ruff auto-fix), the commit is aborted so you can review the change.
Re-run `git commit` to proceed.

To run hooks manually against all files:

```bash
pre-commit run --all-files
```

## Database Migrations

Migrations are managed with Alembic. Migration files live in `backend/alembic/versions/`.

```bash
# Check current migration state
docker-compose exec backend python -m alembic current

# After modifying any SQLAlchemy model, generate a migration
docker-compose exec backend python -m alembic revision --autogenerate -m "describe_the_change"

# Review the generated file in backend/alembic/versions/ before applying
docker-compose exec backend python -m alembic upgrade head

# Roll back one step
docker-compose exec backend python -m alembic downgrade -1
```

When running Alembic from the host (not inside Docker), the `DATABASE_URL` must point to `localhost` instead of the `postgres` container name:

```bash
DATABASE_URL="postgresql://postgres:yourpassword@localhost:5432/stockscanner" python -m alembic current
```

## Running Tests

```bash
# All tests
docker-compose exec backend python -m pytest

# Specific directory
docker-compose exec backend python -m pytest tests/api -v

# With coverage
docker-compose exec backend python -m pytest --cov

# Stop on first failure
docker-compose exec backend python -m pytest -x
```

Or from the host (with venv activated and `DATABASE_URL` pointing to localhost):

```bash
cd backend
python -m pytest
```

## Monitoring Services

### Seq (Structured Log Viewer)

Seq at http://localhost:5380 receives all structured log events from the backend, including full stack traces for every unhandled exception.

Each backend error is tagged with a deterministic `ErrorId` (format: `ERR-xxxxxxxx`). To find a specific error:

```
# In the Seq search bar
ErrorId = 'ERR-xxxxxxxx'
```

Or query the REST API directly:

```bash
curl -s "http://localhost:5380/api/events?filter=ErrorId%3D%27ERR-xxxxxxxx%27&count=5" \
  | python -m json.tool
```

If the Seq container is offline, backend logs fall back to stdout:

```bash
docker-compose logs backend | grep "ERR-"
```

### Flower (Celery Task Monitor)

Flower at http://localhost:5555 shows:
- Active, scheduled, and completed tasks
- Worker status and throughput
- Task execution time and retry history

Useful when debugging scheduled scans or slow background jobs.

### pgAdmin (PostgreSQL GUI)

pgAdmin at http://localhost:5050.

To add the database server:
1. Right-click **Servers** → **Register** → **Server**
2. **General** tab — Name: `stockscanner` (any label)
3. **Connection** tab:
   - Host: `postgres` (the Docker service name, not `localhost`)
   - Port: `5432`
   - Database: `stockscanner`
   - Username: value of `POSTGRES_USER` in `.env` (default: `postgres`)
   - Password: value of `POSTGRES_PASSWORD` in `.env`

Useful SQL queries for debugging:

```sql
-- Recent scanner runs and hit counts
SELECT id, created_at, scanner_type, tickers_scanned, hits
FROM scanner_runs
ORDER BY created_at DESC
LIMIT 20;

-- Scanner events in the last 24 hours
SELECT ticker, event_type, pre_market_volume, relative_volume, price_change_pct, created_at
FROM scanner_events
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY relative_volume DESC;

-- Universe memberships
SELECT su.name, count(sut.id) as ticker_count
FROM stock_universes su
LEFT JOIN stock_universe_tickers sut ON sut.universe_id = su.id
GROUP BY su.name
ORDER BY su.name;

-- Database size
SELECT pg_size_pretty(pg_database_size('stockscanner'));

-- Active connections
SELECT pid, state, query_start, query FROM pg_stat_activity WHERE datname = 'stockscanner';
```

## Troubleshooting

### IB Gateway not starting

- It takes up to 3 minutes on first boot for IBC to authenticate.
- Verify `IB_USERNAME`, `IB_PASSWORD`, and `IB_TRADING_MODE` are set correctly in `.env`.
- Check `docker-compose logs ib-gateway` for authentication errors.
- The backend starts even if IB Gateway is unhealthy; IBKR-dependent features will be unavailable but the rest of the system works normally.

### Port conflicts

```bash
# Check which process holds a port (Windows)
netstat -ano | findstr :5432   # PostgreSQL
netstat -ano | findstr :6379   # Redis
netstat -ano | findstr :8000   # Backend
netstat -ano | findstr :3333   # Frontend
```

### Containers failing to start

```bash
# View full logs for all services
docker-compose logs

# Rebuild images (if Dockerfile or requirements changed)
docker-compose up -d --build
```

### Celery tasks not running

```bash
# Check worker is alive
docker-compose exec celery-worker celery -A app.core.celery_app:celery_app inspect active

# Check beat scheduler log
docker-compose logs celery-beat

# Trigger a task manually via the API
curl -X POST http://localhost:8000/api/scanner/run
```

### Database migrations out of sync

```bash
# Check what revision the DB is on vs. what Alembic expects
docker-compose exec backend python -m alembic current
docker-compose exec backend python -m alembic heads

# If behind, apply pending migrations
docker-compose exec backend python -m alembic upgrade head
```

### ENV changes not reflected

Docker Compose reads `.env` only at container start time. After changing `.env`:

```bash
docker-compose down
docker-compose up -d
```

### Tweet-Monitor: X.com Cookie Rotation

`X_AUTH_TOKEN` and `X_CSRF_TOKEN` are X.com session cookies that expire roughly every 30 days. When they expire, the tweet-monitor detects the `/i/flow/login` redirect and raises `AuthExpiredError`, setting `tweet_monitor_auth_ok = 0`.

**Alert signature:**
- Grafana alert `Tweet-Monitor Auth Expired` fires in the `MarketHawk / Infrastructure` panel
- Seq error log: `@<handle>: auth expired — X.com redirected to login for @<handle>`
- `/health` endpoint returns `"auth_expired": true, "healthy": false`

**To rotate cookies:**

1. Log in to X.com in Chrome (use the account the scraper monitors)
2. Open DevTools → Application → Cookies → `https://x.com`
3. Copy the value of `auth_token` → this is `X_AUTH_TOKEN`
4. Copy the value of `ct0` → this is `X_CSRF_TOKEN`
5. Update `.env`:
   ```
   X_AUTH_TOKEN=<new_auth_token>
   X_CSRF_TOKEN=<new_ct0_value>
   ```
6. Restart the tweet-monitor container:
   ```bash
   docker-compose restart tweet-monitor
   ```
7. Verify recovery: `curl http://localhost:8001/health` should return `"auth_expired": false, "healthy": true`

The `tweet_monitor_auth_ok` gauge returns to `1` on the next poll cycle (within 45 seconds) after a successful restart.

## Codeindex (local visualization)

The symbol index (`symbolindex.json`) and dependency graph (`codeindex.json`) are committed
artifacts, regenerated by the factory and may lag HEAD. When the codeindex MCP server is wired
up, the `lookup_symbol` and `get_impact` tools query them (see [CLAUDE.md](CLAUDE.md#codeindex));
without it, grep/Read are the fallback. To explore the graph interactively on a dev machine:

```bash
# One-time install (developer machines only — never add to backend/requirements.txt)
pip install "git+https://github.com/scheidydude/codeindex.git"

# Launch interactive viz on http://localhost:8080
bash scripts/codeindex.sh
```

## Dark Factory Eval Flywheel

When the factory circuit-breaker trips (after `MAX_RETRIES` failed runs), it:
1. Moves the issue to **Blocked** and labels it `needs-discussion`
2. Applies the `factory-regression` label — marks this failure for the replay benchmark suite
3. Generates a post-mortem comment (`<!-- df-post-mortem -->`) via a haiku agent explaining the probable root cause
4. Appends one line to `dark-factory/evals/factory-failures.jsonl` and commits it to the feature branch

### Querying the failure corpus

```bash
# List all promoted failures
cat dark-factory/evals/factory-failures.jsonl | jq .

# Failures by phase
cat dark-factory/evals/factory-failures.jsonl | jq 'select(.phase == "fix")'

# GitHub label query (requires gh CLI)
gh issue list --repo omniscient/markethawk --label factory-regression
```

### Reading post-mortems

Post-mortem comments are posted directly on the issue and are included automatically in the next dispatch (via the existing `gh issue view --json comments` fetch). No retry-context changes are needed.

### Replay harness (C3 — future work)

The `dark-factory/evals/factory-failures.jsonl` corpus is designed for a future replay harness (architecture review candidate C3) that will re-run failed issues against new factory versions to measure regression rates. The JSONL schema is:
```json
{"issue": 123, "title": "...", "phase": "fix", "exit_code": 1, "postmortem": "...", "promoted_at": "2026-06-12T09:00:00Z"}
```

## Security Notes

- Credentials in `.env` are for local development. Never commit `.env` to version control (it is in `.gitignore`).
- `ENVIRONMENT=development` returns full stack traces in API error responses. Set to `production` to hide internals.
- Flower has no authentication in development. Do not expose port 5555 publicly.
- `READ_ONLY_API=yes` on the IB Gateway container prevents order submission via the API socket.
