# Environment Variables

All variables are read from a `.env` file in the project root. Copy `.env.example` to get started:

```bash
cp .env.example .env
```

Docker Compose reads this file automatically at startup. Changing `.env` requires a container restart (`docker-compose down && docker-compose up -d`) to take effect.

---

## Required Variables

These must be set before starting the stack. The application will start without them but core features will be broken or insecure.

| Variable | Purpose | Example |
|----------|---------|---------|
| `POLYGON_API_KEY` | Polygon.io market data API key | `abc123...` |
| `POSTGRES_PASSWORD` | PostgreSQL superuser password | `change_me` |
| `DATABASE_URL` | Full PostgreSQL connection string (must match `POSTGRES_*` vars) | `postgresql://postgres:change_me@postgres:5432/stockscanner` |
| `SECRET_KEY` | JWT and session signing key. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` | `a3f8d2...` |
| `PGADMIN_DEFAULT_EMAIL` | Login email for pgAdmin web UI | `admin@example.com` |
| `PGADMIN_DEFAULT_PASSWORD` | Login password for pgAdmin web UI | `change_me` |
| `SEQ_ADMIN_PASSWORD_HASH` | Bcrypt hash of the Seq admin password. Generate with: `echo 'YourPassword' \| docker run --rm -i datalust/seq config hash` | `$2a$11$...` |
| `FLOWER_BASIC_AUTH` | Basic auth credentials for the Flower Celery UI (http://localhost:5555). Flower reads this automatically. Format: `user:password` | `admin:change_me_flower_password` |

---

## Optional Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_DB` | `stockscanner` | PostgreSQL database name |
| `POSTGRES_USER` | `postgres` | PostgreSQL superuser name |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string. Overriding is only needed for external Redis. |
| `ENVIRONMENT` | `production` | Set to `development` to include stack traces in API error responses. Defaults to `production` so unset envs never leak internals. |
| `LOG_LEVEL` | `INFO` | Backend and Celery log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `SEQ_URL` | `http://seq:5341` | Seq ingestion endpoint. Set to `disabled` or leave empty to fall back to stdout-only logging. |
| `POLYGON_DELAYED` | `true` | When `true`, treats Polygon data as potentially delayed. Set to `false` if your plan provides real-time data. |
| `DB_POOL_SIZE` | `20` | SQLAlchemy connection pool size per process. Increase if you add more Celery workers. |
| `DB_POOL_MAX_OVERFLOW` | `10` | Extra connections allowed above `DB_POOL_SIZE` during bursts. |
| `DB_POOL_PRE_PING` | `true` | When `true`, tests each connection before use to automatically recover after PostgreSQL restarts. |
| `DB_POOL_RECYCLE` | `3600` | Seconds before a pooled connection is replaced. Prevents stale connections after long idle periods. |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a connection from the pool before raising an error. |

---

## Interactive Brokers (IB Gateway)

These control the `ib-gateway` container and the backend's connection to it. All are optional if you do not use IBKR as a data provider.

| Variable | Default | Purpose |
|----------|---------|---------|
| `IB_USERNAME` | — | IBKR account username for IBC auto-login |
| `IB_PASSWORD` | — | IBKR account password for IBC auto-login |
| `IB_TRADING_MODE` | `paper` | `paper` or `live` — controls which internal Gateway port IBC uses |
| `IB_READ_ONLY` | `yes` | Set to `no` to allow order submission via the API socket. Leave as `yes` for data-only use. |
| `IBKR_HOST` | `ib-gateway` (Docker) / `127.0.0.1` (local) | Hostname the backend and live-scanner use to connect to the Gateway |
| `IBKR_PORT` | `4004` (Docker) | **Use port 4004** — the Gateway API binds to localhost-only inside the container; `socat` proxies it externally on 4004 (paper) / 4003 (live). Direct ports 4002/4001 are unreachable from other containers. |
| `IBKR_CLIENT_ID` | `10` | Base client ID for the backend and Celery workers. Each worker adds `pid % 50` to avoid collisions. **The live-scanner uses clientId 5 (hardcoded) and is not affected by this variable.** |

---

## Tweet Monitor Variables

Read by the `tweet-monitor` container (`services/tweet-monitor/app/config.py`). Cookies must be
rotated manually approximately every 30 days.

| Variable | Default | Purpose |
|----------|---------|---------|
| `X_AUTH_TOKEN` | — | `auth_token` cookie value from a logged-in x.com session. Required for authenticated scraping. |
| `X_CSRF_TOKEN` | — | `ct0` cookie value (CSRF token) from x.com. Required alongside `X_AUTH_TOKEN`. |
| `PROMOTION_THRESHOLD` | `0.7` | Minimum classifier confidence for a CALLOUT tweet to be promoted to a `ScannerEvent`. |
| `BROWSER_MAX_AGE_MINUTES` | `30` | Force-restart Playwright browser after this many minutes. |
| `BROWSER_MAX_MEMORY_MB` | `512` | Force-restart browser if process memory exceeds this limit. |
| `POLL_TIMEOUT_SECONDS` | `25` | Maximum wall-clock time for a single `/poll` cycle. |

---

## Frontend Variables

Set in the `frontend` service's environment block in `docker-compose.yml`, or in `frontend/.env.local` for manual setup.

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_TARGET` | `http://backend:8000` | Backend base URL used by the Vite dev server proxy |
| `VITE_SEQ_UI_URL` | `http://localhost:5380` | Seq UI base URL used by the "Trace in Seq" error toast button |

---

## Verification

```bash
# Check that a variable is set inside a running container
docker exec stockscanner-api printenv POLYGON_API_KEY

# List all environment variables in the backend container
docker exec stockscanner-api printenv

# Test API connectivity (health check)
curl http://localhost:8000/health
```

---

## Adding a New Variable

1. Add it to `.env.example` with a placeholder value and a comment.
2. Add it to the relevant service's `environment:` block in `docker-compose.yml`.
3. Read it in `backend/app/core/config.py` via `os.getenv("VAR_NAME", "default")`.
4. Restart containers: `docker-compose down && docker-compose up -d`.
5. Document it in this file.
