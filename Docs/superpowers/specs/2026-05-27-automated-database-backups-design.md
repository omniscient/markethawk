# Automated Database Backups with Retention

**Date**: 2026-05-27
**Status**: Pending Review
**Issue**: #90

## Problem

All application data — scanner events, trade journals, signal reviews, alert rules, stock aggregates, and system configuration — lives in a single PostgreSQL instance (`markethawk_postgres_data` Docker volume) with no automated backup. A Docker volume corruption, accidental `docker volume rm`, or host disk failure causes total, unrecoverable data loss. The `deployment-guide.md` shows a manual `pg_dump` command but no automation exists.

## Requirements

1. **Daily automated backup** — `pg_dump` runs at 3 AM UTC every day (configurable via cron expression).
2. **Compressed output** — each dump is gzip-compressed to a timestamped file (`markethawk_YYYYMMDD_HHMMSS.sql.gz`).
3. **Retention rotation** — backups older than 30 days (configurable) are automatically deleted.
4. **Exit code validation** — the backup script must fail loudly on `pg_dump` error; partial dumps must not be retained.
5. **Failure observability** — failures are written to Docker logs (stderr) and to Seq as structured error events with `BackupStatus`, `ErrorReason`, and `Timestamp` properties.
6. **Docker-native** — the backup service is added to `docker-compose.yml` and starts with `docker-compose up`; no host crontab required.
7. **Documented restore** — `deployment-guide.md` is updated with backup location, retention policy, and step-by-step restore procedure.
8. **Out of scope**: cloud/offsite sync, automated test restores (follow-up issue).

## Architecture

### Docker Sidecar Service (`db-backup`)

A new `db-backup` service is added to `docker-compose.yml` alongside the existing `db` service. It uses a minimal Alpine-based image with `postgresql-client` and `supercronic` (drop-in cron that logs to stdout, no PID 1 hacks needed).

```
docker-compose.yml
└── db-backup (new)
    ├── image: alpine + pg_client + supercronic
    ├── depends_on: db
    ├── environment: BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_SCHEDULE, SEQ_URL
    │   + inherits POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
    ├── volumes:
    │   └── ${BACKUP_DIR}:/backups:rw   (host bind-mount)
    └── entrypoint: supercronic /etc/cron.d/backup
```

The service does **not** mount `markethawk_postgres_data` directly. It connects via `pg_dump` over the internal Docker network to the running `db` container — the same approach documented in `deployment-guide.md` (`docker exec … pg_dump`), but from a container rather than the host.

### Backup Script (`scripts/backup.sh`)

```bash
#!/usr/bin/env sh
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="/backups/markethawk_${TIMESTAMP}.sql.gz"
TMPFILE="${OUTFILE}.tmp"

# Dump and compress; write to temp first, rename on success
pg_dump -h db -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$TMPFILE"
mv "$TMPFILE" "$OUTFILE"

# Retention: delete files older than BACKUP_RETENTION_DAYS
find /backups -name "markethawk_*.sql.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete

# Log success to stdout (captured by Docker + Seq)
echo "{\"level\":\"Information\",\"message\":\"Backup complete\",\"BackupStatus\":\"success\",\"File\":\"${OUTFILE}\"}"
```

On any failure (`set -e` triggers), the script exits non-zero, leaving the `.tmp` file behind (not moved to final name) so the failed partial dump is never mistaken for a good backup. The sidecar container restarts unless it's a cron-scheduled exit — supercronic handles this correctly.

### Failure Logging to Seq

`scripts/backup.sh` traps `EXIT` and emits a structured JSON line to stderr on failure:

```bash
trap 'on_exit $?' EXIT
on_exit() {
  if [ "$1" -ne 0 ]; then
    printf '{"@t":"%s","@l":"Error","@mt":"Backup failed","BackupStatus":"failure","ErrorReason":"pg_dump exit %s"}\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >&2
  fi
}
```

The Docker logging driver forwards this to Seq (all services already point to `SEQ_URL: http://seq:5341`). Operators can create a Seq alert rule on `BackupStatus = 'failure'` to route to email, webhook, or Teams.

### Configuration

Three new env vars added to `.env.example` under a `# Backup Configuration` section:

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `/backups/markethawk` | Host path where backup files are written |
| `BACKUP_RETENTION_DAYS` | `30` | Delete backups older than this many days |
| `BACKUP_SCHEDULE` | `0 3 * * *` | Cron expression for backup timing (UTC) |

Postgres credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) and `SEQ_URL` are already defined in `.env.example` and are inherited by the sidecar — not duplicated.

## Deliverables

1. `scripts/backup.sh` — backup + rotation + Seq-formatted structured log lines
2. `Dockerfile.backup` (or inline `db-backup` service build in compose) — Alpine + postgresql-client + supercronic
3. `docker-compose.yml` — new `db-backup` service block
4. `.env.example` — `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_SCHEDULE` entries
5. `deployment-guide.md` — updated Backup section with location, retention, and restore procedure

## Alternatives Considered

### Host crontab + shell script
Run `scripts/backup.sh` on the host with `docker exec` calling into the `db` container. Simpler in isolation, but breaks the "Docker-first" design: operators must configure the host, cron behavior varies per OS, and the backup job is invisible to `docker-compose ps`/`logs`. Rejected.

### Local + optional S3 (boto3)
Add optional S3 upload if `BACKUP_S3_BUCKET` is set. The issue explicitly separates cloud storage as "Consider" (aspirational). Adds boto3 dependency and multi-path logic. Rejected as scope creep for size: M.

### pg_basebackup (filesystem-level backup)
Full cluster backup including WAL. More complete than `pg_dump` but requires replication slots or WAL archiving configuration — significantly more complex. For a self-hosted single-instance deployment, `pg_dump` is the conventional choice and produces portable SQL that can be restored to a different Postgres version. Rejected for this issue; WAL archiving can be a future enhancement.

## Open Questions (non-blocking)

- Should `BACKUP_DIR` default to a Docker-managed named volume (`markethawk_backups`) instead of a host bind-mount? A named volume is self-contained in Docker but harder to inspect and copy off-host. A bind-mount is more operator-friendly for disaster recovery (files are on the host filesystem immediately).
- Supercronic vs. `dcron` vs. Alpine's built-in `crond`: supercronic is the modern choice (no PID 1 issues, logs to stdout, handles signals gracefully), but adds an extra binary to the image. Either works; the spec assumes supercronic.

## Assumptions

- **[Assumed]** The Docker host has sufficient disk space for 30 days of compressed dumps. Operators are responsible for monitoring host disk usage.
- **[Assumed]** The `db` service hostname inside the Docker network is `db` (matches `docker-compose.yml` service name).
- **[Assumed]** Seq is running and accessible from the `db-backup` container. If Seq is down, backup still runs; the Seq log line is best-effort.
- **[Assumed]** `PGPASSWORD` environment variable is used for passwordless `pg_dump` authentication (standard Postgres practice for scripted access).
