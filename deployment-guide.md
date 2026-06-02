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

There is no automated backup configured. For production use, schedule regular PostgreSQL dumps:

```bash
# Dump to a file
docker exec stockscanner-db pg_dump -U postgres stockscanner > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from a dump
docker exec -i stockscanner-db psql -U postgres stockscanner < backup_20260101_040000.sql
```

A cron job example (runs at 3 AM daily):
```
0 3 * * * docker exec stockscanner-db pg_dump -U postgres stockscanner > /backups/stockscanner_$(date +\%Y\%m\%d).sql
```

### SSL / TLS

Docker Compose does not include a TLS termination layer. For HTTPS, place a reverse proxy (nginx, Caddy, Traefik) in front of the frontend and backend containers and let Docker Compose handle internal traffic over HTTP.

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
