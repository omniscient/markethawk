# Deployment Guide

This project is deployed via Docker Compose. There is no cloud infrastructure configuration included. The full stack runs as a set of containers defined in `docker-compose.yml`.

For local development setup and Docker commands, see [DEVELOPMENT.md](DEVELOPMENT.md).

---

## Production Hardening Checklist

Before exposing this stack outside your local machine, address the following:

### Credentials

- [ ] Replace all default passwords in `.env` (PostgreSQL, pgAdmin, Seq, SECRET_KEY).
- [ ] Rotate `POLYGON_API_KEY` if it was ever committed or shared.
- [ ] Generate a strong `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`

### Environment

- [ ] Set `ENVIRONMENT=production` in `.env`. This hides stack traces from API error responses.
- [ ] Set `LOG_LEVEL=WARNING` or `ERROR` to reduce log noise in production.

### Network Exposure

- [x] Bind management service ports to `127.0.0.1` in `docker-compose.yml` to prevent external access:
  ```yaml
  ports:
    - "127.0.0.1:5050:80"    # pgAdmin — localhost only
    - "127.0.0.1:5555:5555"  # Flower — localhost only
    - "127.0.0.1:5380:80"    # Seq — localhost only
  ```
- [ ] Only expose port 3333 (frontend) and 8000 (backend API) to the network or a reverse proxy.
- [x] Add authentication to Flower: set `FLOWER_BASIC_AUTH=user:password` in `.env` — Flower reads it automatically from the environment.

### IB Gateway

- [ ] Confirm `IB_READ_ONLY=yes` unless order submission is intentionally enabled.
- [ ] Set `IB_TRADING_MODE=live` only when connected to a live IBKR account.

### Database Backup

Automated backups run via the `db-backup` sidecar service, which starts automatically with `docker-compose up -d`.

**Schedule and format**

- Runs daily at 3 AM UTC by default (configurable via `BACKUP_SCHEDULE`).
- Each backup is a gzip-compressed `pg_dump` file named `stockscanner_YYYYMMDD_HHMMSS.sql.gz`.
- Files older than `BACKUP_RETENTION_DAYS` (default: 30) are deleted automatically after each run.
- Dumps are written atomically — a `.tmp` file is used during the dump; only renamed to the final filename on success. A failed dump leaves no file behind.

**Backup location**

Backups are written to the directory specified by `BACKUP_DIR` (default: `/var/lib/markethawk/backups`) on the Docker host. This directory is bind-mounted into the container at `/backups`.

```bash
# Verify the backup directory and latest file
ls -lh ${BACKUP_DIR:-/var/lib/markethawk/backups}/
```

**Configuration (`.env`)**

| Variable | Default | Description |
|---|---|---|
| `BACKUP_DIR` | `/var/lib/markethawk/backups` | Host path for backup files |
| `BACKUP_RETENTION_DAYS` | `30` | Days to keep backup files |
| `BACKUP_SCHEDULE` | `0 3 * * *` | Cron schedule (UTC, supercronic syntax) |

**Trigger a manual backup**

```bash
docker compose run --rm db-backup /scripts/backup.sh
```

**Failure alerting**

On failure, the script POSTs a structured CLEF event to Seq (`BackupStatus=failed`, `ErrorReason`). Set up a Seq alert rule on `@l = 'Error' and BackupStatus = 'failed'` to route notifications to your preferred channel (email, Slack, etc.).

**Restore procedure**

```bash
# 1. Stop the backend and worker to prevent writes during restore
docker compose stop backend celery-worker celery-beat

# 2. Restore from a backup file
gunzip -c ${BACKUP_DIR:-/var/lib/markethawk/backups}/stockscanner_YYYYMMDD_HHMMSS.sql.gz \
  | docker exec -i stockscanner-db psql -U ${POSTGRES_USER:-postgres} ${POSTGRES_DB:-stockscanner}

# 3. Restart services
docker compose start backend celery-worker celery-beat
```

### Weekly Restore Drill

The `db-restore-drill` sidecar runs weekly to verify that the latest backup can actually be restored. It starts automatically with `docker-compose up -d` alongside the other services.

**What it does**

1. Locates the most recent `stockscanner_*.sql.gz` file in `BACKUP_DIR`; if none exists (fresh deploy), logs a warning and exits cleanly (not a failure).
2. Starts a throwaway postgres cluster inside the container via `initdb` + UNIX socket (no TCP, no external container, no live DB contact).
3. Restores the dump into the throwaway cluster via `gunzip | psql`.
4. Asserts that five critical tables (`scanner_events`, `trades`, `signal_reviews`, `scanner_configs`, `stock_aggregates`) each have at least one row.
5. Asserts that `alembic_version` has a non-empty value (schema migration was restored).
6. Emits a structured Seq event and unconditionally kills the throwaway postgres process and removes temp directories.

The live `stockscanner-db` is never contacted — the drill embeds an isolated postgres cluster with no network listener and no live DB credentials.

**Schedule**

Runs every Sunday at 4 AM UTC by default (one hour after the daily backup window).

**Configuration (`.env`)**

| Variable | Default | Description |
|---|---|---|
| `RESTORE_DRILL_SCHEDULE` | `0 4 * * 0` | Cron schedule (UTC, supercronic syntax) |
| `EXPECTED_ALEMBIC_HEAD` | _(empty)_ | Optional: exact alembic revision to assert after restore. Set to the output of `python -m alembic current` in your `.env`. When empty, the drill asserts only that `alembic_version` is non-empty. |

**Trigger a manual one-shot drill**

```bash
docker compose run --rm db-restore-drill /scripts/restore-drill.sh
```

**Reading drill results in Seq**

Every drill emits a `backup.restore_drill` CLEF event. Filter in Seq:

```
EventType = 'backup.restore_drill'
```

Successful drill: `@l = 'Information'`, `Verdict = 'passed'`, per-table counts in `TableCounts`.  
Failed drill: `@l = 'Error'`, `Verdict = 'failed'`, `FailReason` explains why it failed.

Set up a Seq alert on `@l = 'Error' and EventType = 'backup.restore_drill'` to be notified immediately when a drill fails.

**Simulating a corrupted backup**

To verify the drill catches bad backups, truncate a copy of the latest dump and run the drill against it:

```bash
# Truncate a copy of the latest backup to simulate corruption
LATEST=$(ls -t ${BACKUP_DIR:-/var/lib/markethawk/backups}/stockscanner_*.sql.gz | head -1)
cp "${LATEST}" "${LATEST%.sql.gz}_corrupt.sql.gz"
truncate -s 512 "${LATEST%.sql.gz}_corrupt.sql.gz"

# Rename to make it the "latest" file temporarily (alphabetically last by timestamp)
mv "${LATEST}" "${LATEST}.bak"
mv "${LATEST%.sql.gz}_corrupt.sql.gz" "${LATEST}"

# Run the drill — it should fail loudly
docker compose run --rm db-restore-drill /scripts/restore-drill.sh

# Restore the original
mv "${LATEST}" "${LATEST%.sql.gz}_corrupt.sql.gz"
mv "${LATEST}.bak" "${LATEST}"
rm "${LATEST%.sql.gz}_corrupt.sql.gz"
```

### SSL / TLS

A Caddy reverse proxy service is included in `docker-compose.yml`, gated behind `profiles: ["tls"]`. Caddy auto-provisions and renews Let's Encrypt certificates from a single `DOMAIN` environment variable — no pre-provisioned secrets required.

**Prerequisites**

- A public domain name (e.g. `markethawk.example.com`) pointed at the server's IP address.
- Ports 80 and 443 reachable from the internet (Let's Encrypt HTTP-01 challenge).

**Enable TLS**

1. Add `DOMAIN=markethawk.example.com` to `.env`.
2. Start (or restart) the Caddy service:
   ```bash
   docker compose --profile tls up -d caddy
   ```
   Caddy obtains a certificate on first startup and stores it in the `caddy_data` volume for automatic renewal.
3. All traffic to `https://<DOMAIN>/api/*` is proxied to `backend:8000`; all other paths go to `frontend:3333`.
4. WebSocket connections (`/api/v1/live/ws/*`) are proxied transparently — Caddy handles the HTTP→WS upgrade.

**Cookie security**

> **Warning:** `COOKIE_SECURE` defaults to `true`. Any networked deployment that does not enable the `tls` profile will have session cookies silently dropped by browsers over plain HTTP — users will be unable to log in. Enable the Caddy `tls` profile (steps above) for all deployments reachable over a network. Local dev is exempt because `docker-compose.override.yml` automatically sets `COOKIE_SECURE=false`.

`COOKIE_SECURE` defaults to `true`. Local dev overrides this automatically via `docker-compose.override.yml` so cookies work over plain HTTP. In production the cookies require HTTPS; enabling the Caddy profile satisfies this.

**API docs in production**

`DOCS_ENABLED` defaults to `false` — Swagger UI, ReDoc, and `/openapi.json` are not served in production and return 401/404. This prevents the full API schema from being used as a reconnaissance map by unauthenticated callers.

Local dev overrides this automatically via `docker-compose.override.yml` (`DOCS_ENABLED: "true"`), so developers have full access to `/docs` and `/openapi.json` without any manual steps.

> **Note:** If you need docs access on a staging environment, add `DOCS_ENABLED=true` to that environment's `.env`. Never set this in production.

**Prometheus `/metrics` isolation**

`/metrics` is accessible on the internal Docker network only (Prometheus scrapes `backend:8000/metrics` directly). The Caddyfile blocks external requests to `/metrics` with a `404` response before they reach the backend — backend port 8000 must **not** be published to the host in production (`ports:` mapping removed or bound to `127.0.0.1`). If port 8000 is externally reachable, the Caddyfile deny is insufficient and the port mapping must be removed.

**HTTP→HTTPS and HSTS**

The Caddyfile redirects all HTTP (`:80`) requests to HTTPS and sets `Strict-Transport-Security` so browsers enforce HTTPS for all subsequent visits. Port 80 remains published only for Let's Encrypt HTTP-01 challenges and the redirect — no content is served over plain HTTP.

**Routing table**

| Path pattern | Upstream |
|---|---|
| `/metrics` | 404 (Caddy deny — internal Docker network only) |
| `/api/*` | `backend:8000` |
| `/*` | `frontend:3333` |

---

## Deploying from GHCR

Images are published to GitHub Container Registry on every merge to `main`.  
Three images are maintained: `markethawk-backend`, `markethawk-frontend`, `markethawk-dark-factory`.

Each push produces two tags:
- `sha-{SHORT_SHA}` — permanent, points to that exact commit
- `latest` — moves forward with every merge

All `docker-compose.yml` services honour the `IMAGE_TAG` env var (default: `latest`).
To deploy a specific tag, set `IMAGE_TAG` before running Compose commands:

```bash
# Deploy a specific SHA tag
export IMAGE_TAG=sha-abc1234
docker compose pull backend celery-worker celery-beat live-scanner flower frontend backlog-scheduler
docker compose up -d backend celery-worker celery-beat live-scanner flower frontend backlog-scheduler

# Run migrations after deploying
docker compose exec -T backend python -m alembic upgrade head
```

The `deploy.yml` GitHub Actions workflow automates this via **Actions → Deploy → Run workflow**.

---

## Rollback Procedure

To roll back to a prior release, pin `IMAGE_TAG` to any previous SHA tag before re-deploying:

```bash
# 1. Find the SHA tag to roll back to
#    Browse: https://github.com/omniscient/markethawk/pkgs/container/markethawk-backend
#    Or: gh api /orgs/omniscient/packages/container/markethawk-backend/versions --jq '.[].metadata.container.tags[]' | grep sha-

# 2. Pin IMAGE_TAG and restart services
export IMAGE_TAG=sha-abc1234
docker compose pull backend celery-worker celery-beat live-scanner flower frontend backlog-scheduler
docker compose up -d backend celery-worker celery-beat live-scanner flower frontend backlog-scheduler
```

If the rollback target is behind a database migration, roll back the schema first:

```bash
# Find the revision to revert to from alembic/versions/ history
docker compose exec -T backend python -m alembic downgrade <revision>
```

---

## Upgrading

```bash
# Pull latest images and rebuild
docker-compose pull
docker-compose up -d --build

# Apply any new database migrations
docker-compose exec backend python -m alembic upgrade head
```

After upgrading, always check `docker-compose logs backend` for startup errors and verify the migration ran cleanly.

---

## Logs and Monitoring

| Tool | URL | What to watch |
|------|-----|---------------|
| Seq | http://localhost:5380 | Backend errors — search by `ErrorId` or filter by log level |
| Flower | http://localhost:5555 | Celery task failures, queue depth, worker health |
| Docker | `docker-compose logs -f` | Raw container stdout for all services |

See [DEVELOPMENT.md — Monitoring Services](DEVELOPMENT.md#monitoring-services) for query examples.

---

## IBKR Feed Loss Runbook

### What Operators See During a Feed Loss

**Seq** (filter by `live_scanner.ibkr_adapter`):
- `WARNING`: `"IB Gateway disconnected"` fires immediately on container stop.
- For network partition: `WARNING` from watchdog: `"no bars for Xs during market hours — forcing disconnect"` fires after ~30–40 s.
- Subsequent reconnect attempts: logged with backoff delays (5 s, 10 s, 20 s, … capped at 60 s).
- On recovery: `"live-scanner: reconnect succeeded"` followed by per-symbol resubscription logs.

**Grafana** (`ibkr_connection_status` gauge, sourced from `app/core/metrics.py`):
- Drops to `0` on disconnect; returns to `1` on recovery.
- Alert rule `ibkr_disconnect_2min` fires if the outage exceeds 2 minutes.

**Frontend (`/watchlist`)**:
- Amber banner: `"Feed stale — IBKR gateway disconnected"` appears next to the Live/Connecting badge.
- Per-symbol prices grey out after 15 s of no ticks (pre-existing per-symbol staleness — complementary, not replaced).
- Banner clears automatically when `feed_recovered` event arrives on `watchlist:alerts`.

**`/api/ready`** — HTTP 200 even during an outage; only DB/Redis gate the HTTP status:
```json
{
  "status": "ready",
  "db": {"ok": true, "latency_ms": 2},
  "redis": {"ok": true, "latency_ms": 1},
  "live_data": {"ok": false, "latency_ms": 3001, "error": "Connection refused"}
}
```

### Recovery

In-process reconnect fires automatically with exponential backoff. No manual intervention needed unless:
- All 10 retries are exhausted (see Seq for `"exhausted reconnect retries"`) — restart the live-scanner container.
- The IB Gateway container itself is in a bad state — restart `stockscanner-ibgateway`.

### Chaos Test

Reproduce and verify both failure modes locally:

```bash
# Mock mode (no IBKR credentials)
bash scripts/chaos/ibkr_kill_test.sh --mock

# Live mode (paper IBKR credentials)
IB_USERNAME=mypaper IB_PASSWORD=... bash scripts/chaos/ibkr_kill_test.sh
```

See `scripts/chaos/README.md` for full invocation details.
