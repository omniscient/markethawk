# Automated Database Backups with Retention — Implementation Plan

**Date**: 2026-05-28  
**Issue**: #90  
**Spec**: `Docs/superpowers/specs/2026-05-27-automated-database-backups-design.md`  
**Status**: Draft (Cycle 2 — architect fixes applied)

---

## Goal

Add a Docker-native `db-backup` sidecar service that runs `pg_dump` daily at 3 AM UTC, gzip-compresses output to a timestamped file, rotates backups older than 30 days, posts structured failure events to Seq via HTTP, and documents the restore procedure in `deployment-guide.md`. No host crontab required.

---

## Architecture

```
docker-compose.yml
└── db-backup (new service)
    ├── image: alpine:3.19 + postgresql15-client + curl + supercronic
    ├── depends_on: postgres (healthy)
    ├── environment: PGPASSWORD, POSTGRES_USER, POSTGRES_DB, BACKUP_DIR,
    │               BACKUP_RETENTION_DAYS, BACKUP_SCHEDULE, SEQ_URL
    ├── volumes: ${BACKUP_DIR:-/backups/markethawk}:/backups:rw   (host bind-mount)
    └── entrypoint: backup-entrypoint.sh → writes crontab → exec supercronic

scripts/backup.sh
├── Atomic dump: pg_dump -h postgres → gzip → TMPFILE → mv to OUTFILE
├── Retention: find /backups -mtime +BACKUP_RETENTION_DAYS -delete
├── Exit trap: writes {"BackupStatus":"failure"} JSON to stderr
│             + POSTs CLEF event to $SEQ_URL/api/events/raw?clef (best-effort)
└── Success: emits {"BackupStatus":"success"} JSON to stdout

Note: docker-compose.yml names the postgres service "postgres" (not "db" as in the
spec diagram). backup.sh uses -h postgres accordingly.

Seq integration: other services post to Seq via HTTP from application code (no
Docker logging driver). backup.sh follows the same pattern: curl POST to SEQ_URL
on failure. stderr output also remains for docker-compose logs visibility.
```

---

## Tech Stack

- Shell: `/usr/bin/env sh` + `set -euo pipefail` (busybox ash, Alpine 3.19+)
- Supercronic v0.2.29: container-safe cron daemon (logs to stdout, no PID 1 hacks)
- BATS 1.x: shell script test framework (installed via apt on WSL2 Ubuntu)
- Alpine Linux 3.19 + postgresql15-client + curl: matches postgres:15-alpine in compose

---

## File Structure

| File | Action | Description |
|------|--------|-------------|
| `scripts/backup.sh` | **New** | Atomic pg_dump + gzip + rotation + stderr JSON + Seq HTTP POST |
| `scripts/backup-entrypoint.sh` | **New** | Writes runtime crontab from `$BACKUP_SCHEDULE`, execs supercronic |
| `Dockerfile.backup` | **New** | Alpine image with postgresql15-client + curl + supercronic (arch-aware) |
| `tests/test_backup.bats` | **New** | BATS tests for backup.sh (exit codes, atomicity, rotation, stderr, Seq) |
| `docker-compose.yml` | **Modified** | Add `db-backup` service block with SEQ_URL |
| `.env.example` | **Modified** | Add `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_SCHEDULE` |
| `deployment-guide.md` | **Modified** | Rewrite Database Backup section with location, retention, restore |

---

## Tasks

### Task 1: Write failing BATS tests for `backup.sh`

**Files:** `tests/test_backup.bats`

#### Step 1.1 — Install BATS on the host

```bash
sudo apt-get install -y bats
bats --version
```

Expected output:
```
Bats 1.x.x
```

#### Step 1.2 — Write `tests/test_backup.bats`

```bash
#!/usr/bin/env bats
# tests/test_backup.bats

setup() {
  STUBS="$(mktemp -d)"
  export BACKUP_DIR="$(mktemp -d)"
  export BACKUP_RETENTION_DAYS=30
  export POSTGRES_USER=postgres
  export POSTGRES_DB=testdb
  export PGPASSWORD=testpass
  # SEQ_URL intentionally unset unless the test requires it
}

teardown() {
  rm -rf "$STUBS" "$BACKUP_DIR"
}

make_failing_pg_dump() {
  printf '#!/bin/sh\nexit 1\n' > "$STUBS/pg_dump"
  chmod +x "$STUBS/pg_dump"
  printf '#!/bin/sh\ncat\n' > "$STUBS/gzip"
  chmod +x "$STUBS/gzip"
  printf '#!/bin/sh\nexit 0\n' > "$STUBS/curl"
  chmod +x "$STUBS/curl"
  export PATH="$STUBS:$PATH"
}

make_passing_pg_dump() {
  printf '#!/bin/sh\necho "-- test dump"\n' > "$STUBS/pg_dump"
  chmod +x "$STUBS/pg_dump"
  printf '#!/bin/sh\ncat\n' > "$STUBS/gzip"
  chmod +x "$STUBS/gzip"
  printf '#!/bin/sh\nexit 0\n' > "$STUBS/curl"
  chmod +x "$STUBS/curl"
  export PATH="$STUBS:$PATH"
}

@test "exits non-zero when pg_dump fails" {
  make_failing_pg_dump
  run sh scripts/backup.sh
  [ "$status" -ne 0 ]
}

@test "does not leave .tmp file after pg_dump failure" {
  make_failing_pg_dump
  run sh scripts/backup.sh
  [ "$(find "$BACKUP_DIR" -name '*.tmp' | wc -l)" -eq 0 ]
}

@test "creates .sql.gz file on successful dump" {
  make_passing_pg_dump
  run sh scripts/backup.sh
  [ "$status" -eq 0 ]
  [ "$(find "$BACKUP_DIR" -name 'markethawk_*.sql.gz' | wc -l)" -eq 1 ]
}

@test "emits BackupStatus failure JSON to stderr on pg_dump failure" {
  make_failing_pg_dump
  run sh -c "sh scripts/backup.sh 2>&1"
  [[ "$output" == *'"BackupStatus":"failure"'* ]]
}

@test "deletes backup files older than BACKUP_RETENTION_DAYS" {
  make_passing_pg_dump
  touch -d "35 days ago" "$BACKUP_DIR/markethawk_20260423_030000.sql.gz"
  export BACKUP_RETENTION_DAYS=30
  run sh scripts/backup.sh
  [ ! -f "$BACKUP_DIR/markethawk_20260423_030000.sql.gz" ]
}

@test "posts CLEF event to Seq when SEQ_URL is set and backup fails" {
  make_failing_pg_dump
  # Override curl stub to record its invocation
  printf '#!/bin/sh\ntouch "%s/curl_invoked"\n' "$BACKUP_DIR" > "$STUBS/curl"
  chmod +x "$STUBS/curl"
  export SEQ_URL="http://test-seq:5341"
  run sh -c "sh scripts/backup.sh 2>&1"
  [ -f "$BACKUP_DIR/curl_invoked" ]
}
```

#### Step 1.3 — Verify all tests fail (script doesn't exist yet)

```bash
bats tests/test_backup.bats
```

Expected output:
```
1..6
not ok 1 exits non-zero when pg_dump fails
not ok 2 does not leave .tmp file after pg_dump failure
not ok 3 creates .sql.gz file on successful dump
not ok 4 emits BackupStatus failure JSON to stderr on pg_dump failure
not ok 5 deletes backup files older than BACKUP_RETENTION_DAYS
not ok 6 posts CLEF event to Seq when SEQ_URL is set and backup fails
```

#### Step 1.4 — Commit

```bash
git add tests/test_backup.bats
git commit -m "test(backup): add failing BATS tests for backup.sh

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

### Task 2: Implement `scripts/backup.sh`

**Files:** `scripts/backup.sh`

#### Step 2.1 — Create `scripts/backup.sh`

```sh
#!/usr/bin/env sh
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTFILE="${BACKUP_DIR}/markethawk_${TIMESTAMP}.sql.gz"
TMPFILE="${OUTFILE}.tmp"

on_exit() {
  EXIT_CODE=$1
  if [ "$EXIT_CODE" -ne 0 ]; then
    TIMESTAMP_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"@t":"%s","@l":"Error","@mt":"Backup failed","BackupStatus":"failure","ErrorReason":"pg_dump exit %s"}\n' \
      "$TIMESTAMP_ISO" "$EXIT_CODE" >&2
    if [ -n "${SEQ_URL:-}" ]; then
      curl -sf -X POST "${SEQ_URL}/api/events/raw?clef" \
        -H "Content-Type: application/vnd.serilog.clef" \
        --data-raw "{\"@t\":\"${TIMESTAMP_ISO}\",\"@l\":\"Error\",\"@mt\":\"Backup failed\",\"BackupStatus\":\"failure\",\"ErrorReason\":\"pg_dump exit ${EXIT_CODE}\"}" \
        >/dev/null 2>&1 || true
    fi
    rm -f "$TMPFILE"
  fi
}
trap 'on_exit $?' EXIT

pg_dump -h postgres -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$TMPFILE"
mv "$TMPFILE" "$OUTFILE"

find "$BACKUP_DIR" -name "markethawk_*.sql.gz" -mtime +"$BACKUP_RETENTION_DAYS" -delete

printf '{"@t":"%s","@l":"Information","@mt":"Backup complete","BackupStatus":"success","File":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$OUTFILE"
```

#### Step 2.2 — Make executable

```bash
chmod +x scripts/backup.sh
```

#### Step 2.3 — Run BATS tests

```bash
bats tests/test_backup.bats
```

Expected output:
```
1..6
ok 1 exits non-zero when pg_dump fails
ok 2 does not leave .tmp file after pg_dump failure
ok 3 creates .sql.gz file on successful dump
ok 4 emits BackupStatus failure JSON to stderr on pg_dump failure
ok 5 deletes backup files older than BACKUP_RETENTION_DAYS
ok 6 posts CLEF event to Seq when SEQ_URL is set and backup fails
```

#### Step 2.4 — Commit

```bash
git add scripts/backup.sh
git commit -m "feat(backup): implement backup.sh with atomic dump, retention rotation, stderr logging, and Seq HTTP POST

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

### Task 3: Create `scripts/backup-entrypoint.sh` and `Dockerfile.backup`

**Files:** `scripts/backup-entrypoint.sh`, `Dockerfile.backup`

#### Step 3.1 — Create `scripts/backup-entrypoint.sh`

Supercronic reads a literal crontab file — it does not expand shell variables inside it. This entrypoint writes the crontab at container start using the `BACKUP_SCHEDULE` env var.

```sh
#!/usr/bin/env sh
set -e
mkdir -p "$BACKUP_DIR"
echo "${BACKUP_SCHEDULE:-0 3 * * *} /scripts/backup.sh" > /etc/backup-cron
exec supercronic /etc/backup-cron
```

```bash
chmod +x scripts/backup-entrypoint.sh
```

#### Step 3.2 — Create `Dockerfile.backup`

Architecture detection at build time ensures the image builds correctly on both `amd64` (x86_64 / WSL2) and `arm64` (Apple Silicon) hosts.

```dockerfile
FROM alpine:3.19

RUN apk add --no-cache postgresql15-client curl

ARG SUPERCRONIC_VERSION=v0.2.29
RUN ARCH="$(uname -m)"; \
    [ "$ARCH" = "aarch64" ] && ARCH="arm64" || ARCH="amd64"; \
    wget -q \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" \
      -O /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic

COPY scripts/backup.sh /scripts/backup.sh
COPY scripts/backup-entrypoint.sh /scripts/backup-entrypoint.sh
RUN chmod +x /scripts/backup.sh /scripts/backup-entrypoint.sh

ENTRYPOINT ["/scripts/backup-entrypoint.sh"]
```

#### Step 3.3 — Build and verify

```bash
docker build -f Dockerfile.backup -t markethawk-db-backup:test .
```

Expected:
```
Successfully built <image-id>
Successfully tagged markethawk-db-backup:test
```

```bash
docker run --rm markethawk-db-backup:test supercronic --help 2>&1 | head -2
```

Expected:
```
supercronic is a drop-in replacement for cron, built specifically to run in containers.
```

```bash
docker run --rm markethawk-db-backup:test pg_dump --version
```

Expected:
```
pg_dump (PostgreSQL) 15.x
```

```bash
docker run --rm markethawk-db-backup:test curl --version | head -1
```

Expected:
```
curl x.x.x (x86_64-alpine-linux-musl) ...
```

#### Step 3.4 — Commit

```bash
git add Dockerfile.backup scripts/backup-entrypoint.sh
git commit -m "feat(backup): add arch-aware Dockerfile.backup and backup-entrypoint.sh

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

### Task 4: Add `db-backup` service to `docker-compose.yml`

**Files:** `docker-compose.yml`

#### Step 4.1 — Add service block

Insert the following block into `docker-compose.yml` between the `postgres` service and the `redis` service:

```yaml
  db-backup:
    build:
      context: .
      dockerfile: Dockerfile.backup
    container_name: markethawk-db-backup
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-stockscanner}
      PGPASSWORD: ${POSTGRES_PASSWORD}
      BACKUP_DIR: /backups
      BACKUP_RETENTION_DAYS: ${BACKUP_RETENTION_DAYS:-30}
      BACKUP_SCHEDULE: ${BACKUP_SCHEDULE:-0 3 * * *}
      SEQ_URL: http://seq:5341
    volumes:
      - ${BACKUP_DIR:-/backups/markethawk}:/backups:rw
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - stockscanner-network
    restart: unless-stopped
```

`PGPASSWORD` is set to `POSTGRES_PASSWORD` so `pg_dump` authenticates without an interactive prompt. The container-internal `BACKUP_DIR` is always `/backups`; the host path is configured via the volume bind-mount. `SEQ_URL` matches all other services in this compose file.

#### Step 4.2 — Validate compose syntax

```bash
docker-compose config --quiet
```

Expected: exits 0 with no output.

#### Step 4.3 — Build the service

```bash
docker-compose build db-backup
```

Expected:
```
[+] Building ... Successfully built
```

#### Step 4.4 — Commit

```bash
git add docker-compose.yml
git commit -m "feat(backup): add db-backup sidecar service to docker-compose.yml

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

### Task 5: Update `.env.example`

**Files:** `.env.example`

#### Step 5.1 — Append backup configuration section

Add the following block at the end of `.env.example`:

```
# =============================================================================
# OPTIONAL: Database Backup Configuration
# =============================================================================
# Host directory where compressed backup files are written.
# This path is bind-mounted into the db-backup container at /backups.
# Ensure the host directory exists and has sufficient disk space for 30+ dumps.
# Default: /backups/markethawk
# BACKUP_DIR=/backups/markethawk

# Number of days to retain backup files before automatic deletion.
# Default: 30
# BACKUP_RETENTION_DAYS=30

# Cron expression controlling when backups run (UTC).
# Default: 3 AM UTC daily
# BACKUP_SCHEDULE=0 3 * * *
```

#### Step 5.2 — Verify no active (uncommented) vars introduced

```bash
grep -E "^BACKUP_" .env.example
```

Expected: no output (all backup vars are commented out — they have safe defaults in compose).

#### Step 5.3 — Commit

```bash
git add .env.example
git commit -m "feat(backup): add BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_SCHEDULE to .env.example

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

### Task 6: Update `deployment-guide.md` — Backup Documentation

**Files:** `deployment-guide.md`

#### Step 6.1 — Replace the existing Database Backup section

Find the section that begins with `### Database Backup` and ends with the closing triple-backtick of the cron job example (just before `### SSL / TLS`). The current text of this section is:

```
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
```

Replace it entirely with:

```
### Database Backup

Backups are automated by the `db-backup` Docker Compose service. No host crontab required.

**Schedule:** Daily at 3 AM UTC (configurable via `BACKUP_SCHEDULE` in `.env`)  
**Format:** `markethawk_YYYYMMDD_HHMMSS.sql.gz` — gzip-compressed SQL dump  
**Location:** Host path from `BACKUP_DIR` (default: `/backups/markethawk`)  
**Retention:** Files older than `BACKUP_RETENTION_DAYS` days (default: 30) are auto-deleted on the next successful run

#### Verifying Backups

```bash
# List recent backup files on the host
ls -lh /backups/markethawk/

# Tail backup service logs (one JSON line per run)
docker-compose logs db-backup --tail=20
```

#### Manual On-Demand Backup

```bash
docker-compose run --rm db-backup /scripts/backup.sh
```

Expected output:
```json
{"@t":"2026-05-28T03:00:01Z","@l":"Information","@mt":"Backup complete","BackupStatus":"success","File":"/backups/markethawk_20260528_030001.sql.gz"}
```

#### Restore Procedure

1. Stop services that write to the database:
   ```bash
   docker-compose stop backend celery-worker celery-beat live-scanner
   ```

2. Drop and recreate the database:
   ```bash
   docker-compose exec postgres psql -U postgres -c "DROP DATABASE stockscanner;"
   docker-compose exec postgres psql -U postgres -c "CREATE DATABASE stockscanner;"
   ```

3. Restore from the backup file (replace the filename with your target dump):
   ```bash
   gunzip -c /backups/markethawk/markethawk_20260527_030000.sql.gz \
     | docker-compose exec -T postgres psql -U postgres stockscanner
   ```

4. Restart services:
   ```bash
   docker-compose start backend celery-worker celery-beat live-scanner
   ```

5. Verify the restore:
   ```bash
   curl -s http://localhost:8000/api/health | python -m json.tool
   ```

#### Failure Alerts

Failed backups emit a structured CLEF error event to stderr (visible in `docker-compose logs`) and POST it to Seq:
```json
{"@t":"2026-05-28T03:00:01Z","@l":"Error","@mt":"Backup failed","BackupStatus":"failure","ErrorReason":"pg_dump exit 1"}
```

Create a Seq alert rule on `BackupStatus = 'failure'` to route notifications to email, webhook, or Teams.
```

#### Step 6.2 — Verify section headings are intact

```bash
grep "^###" deployment-guide.md
```

Expected:
```
### Credentials
### Environment
### Network Exposure
### IB Gateway
### Database Backup
### SSL / TLS
```

#### Step 6.3 — Commit

```bash
git add deployment-guide.md
git commit -m "docs(backup): document automated backup location, retention, and restore procedure

Co-Authored-By: MarketHawk Factory <noreply@markethawk.dev>"
```

---

## Summary

| Task | Files | Commits |
|------|-------|---------|
| 1 | `tests/test_backup.bats` | 1 |
| 2 | `scripts/backup.sh` | 1 |
| 3 | `Dockerfile.backup`, `scripts/backup-entrypoint.sh` | 1 |
| 4 | `docker-compose.yml` | 1 |
| 5 | `.env.example` | 1 |
| 6 | `deployment-guide.md` | 1 |

**Total: 6 tasks, 6 commits**

## Spec Coverage Checklist

| Requirement | Task |
|-------------|------|
| Daily automated backup at 3 AM UTC via cron expression | Task 3, 4 |
| Gzip-compressed timestamped output | Task 2 |
| Retention rotation (30-day default) | Task 2 |
| Exit code validation; partial dumps not retained (`.tmp` pattern) | Task 2 |
| Failure observability: stderr JSON + Seq HTTP POST (CLEF) | Task 2, 4 |
| Docker-native, starts with `docker-compose up` | Task 3, 4 |
| Documented restore procedure in `deployment-guide.md` | Task 6 |
| `.env.example` updated with backup env vars | Task 5 |
