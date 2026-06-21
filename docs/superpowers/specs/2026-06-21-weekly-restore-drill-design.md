# Weekly Restore Drill — verify #90 backups by restoring into a throwaway container

**Status:** design
**Date:** 2026-06-21
**Issue:** #386
**Depends on:** #90 (db-backup sidecar)

## Problem

The `db-backup` sidecar (issue #90) produces daily `pg_dump` artifacts, but the spec
explicitly deferred automated restore verification: "No automated test restores — those
are left as a follow-up." A backup that has never been restored is unverified by
definition. A corrupted or truncated dump sitting in `BACKUP_DIR` would only be
discovered at the worst possible time: an actual recovery event.

## Decision

Add a `db-restore-drill` sidecar service that runs weekly, restores the most recent
backup into an embedded throwaway postgres cluster, asserts data integrity, and emits a
structured Seq event. No human action required after initial deployment.

---

## Requirements

1. **Weekly schedule** — configurable via `RESTORE_DRILL_SCHEDULE` env var (default
   `0 4 * * 0`, Sundays at 4 AM UTC — one hour after the daily backup).
2. **Latest backup selection** — find the most recent `stockscanner_*.sql.gz` in
   `BACKUP_DIR`; if none exists (fresh deploy, pre-first-backup window), log a warning
   and exit 0 (not an error — live DB is healthy, backup just hasn't run yet).
3. **Throwaway postgres** — `initdb` a private cluster in a temp dir and run `postgres`
   on a UNIX socket (no TCP port, no network listener). The live `stockscanner-db` is
   never contacted; no live DB credentials are needed.
4. **Restore** — `gunzip | psql` into the throwaway cluster.
5. **Integrity assertions** (any failure → drill fails):
   - Row count > 0 for each critical table: `scanner_events`, `trades`,
     `signal_reviews`, `scanner_configs`, `stock_aggregates`.
   - `SELECT version_num FROM alembic_version` equals `EXPECTED_ALEMBIC_HEAD` (env var).
6. **Seq event** — always emitted on completion (CLEF, best-effort):
   - Event type: `backup.restore_drill`
   - Fields: `Verdict` (`passed`/`failed`), `BackupFile`, per-table row counts, `AlembicHead`
   - `@l` = `Information` on pass; `@l` = `Error` on failure (drives Seq alert rule).
7. **Unconditional teardown** — `trap` kills the postgres process and `rm -rf`s the temp
   data dir on any exit path (success, failure, signal).
8. **Manual one-shot** — `docker compose run --rm db-restore-drill /scripts/restore-drill.sh`
9. **Documentation** — `deployment-guide.md` section on the drill and how to read its
   Seq events; `ENV_VARIABLES.md` entries for `RESTORE_DRILL_SCHEDULE` and
   `EXPECTED_ALEMBIC_HEAD`.

---

## Architecture / Approach

### New files

| Path | Purpose |
|---|---|
| `docker/Dockerfile.restore-drill` | Alpine + postgresql15 (client + server) + supercronic |
| `scripts/restore-drill.sh` | Core drill logic: find backup, initdb, restore, assert, emit Seq |
| `scripts/restore-drill-entrypoint.sh` | Write supercronic crontab from `RESTORE_DRILL_SCHEDULE`, exec supercronic |

### New `db-restore-drill` service (`docker-compose.yml`)

```yaml
db-restore-drill:
  build:
    context: .
    dockerfile: docker/Dockerfile.restore-drill
  container_name: markethawk-db-restore-drill
  environment:
    BACKUP_DIR: ${BACKUP_DIR:-/backups}
    RESTORE_DRILL_SCHEDULE: ${RESTORE_DRILL_SCHEDULE:-0 4 * * 0}
    EXPECTED_ALEMBIC_HEAD: ${EXPECTED_ALEMBIC_HEAD:-}
    SEQ_URL: http://seq:5341
  volumes:
    - ${BACKUP_DIR:-/var/lib/markethawk/backups}:/backups:ro
  networks:
    - stockscanner-network
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: 256M
```

Key points:
- The backup volume is mounted **read-only** (`:ro`) — the drill can never corrupt or
  delete the backup artifacts.
- No `depends_on: [postgres]` — the drill never connects to the live DB.
- `EXPECTED_ALEMBIC_HEAD` defaults to empty string; the drill fails with a meaningful
  error if the env var is unset and the alembic check is reached (encourages operators
  to set it explicitly in `.env`).

### `docker/Dockerfile.restore-drill`

```dockerfile
FROM alpine:3.19

RUN apk add --no-cache postgresql15-client postgresql15 curl

ARG SUPERCRONIC_VERSION=0.2.29
RUN ARCH=$(uname -m); \
    case "${ARCH}" in \
        x86_64)  SC_ARCH="linux-amd64" ;; \
        aarch64) SC_ARCH="linux-arm64" ;; \
        armv7l)  SC_ARCH="linux-arm" ;; \
        *)       echo "Unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac; \
    wget -q "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-${SC_ARCH}" \
         -O /usr/local/bin/supercronic && \
    chmod +x /usr/local/bin/supercronic

COPY scripts/restore-drill.sh /scripts/restore-drill.sh
COPY scripts/restore-drill-entrypoint.sh /entrypoint.sh
RUN chmod +x /scripts/restore-drill.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

Mirrors `Dockerfile.backup` structure; adding `postgresql15` (server package) is the
only substantive difference. The `postgresql15-client` tools (`psql`) are a dependency
of `postgresql15` on Alpine so no double-install.

### `scripts/restore-drill.sh` (logic outline)

```sh
#!/bin/sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
SEQ_URL="${SEQ_URL:-}"
EXPECTED_ALEMBIC_HEAD="${EXPECTED_ALEMBIC_HEAD:-}"
PGDATA="/tmp/drill_pgdata_$$"
PGSOCKET="/tmp/drill_socket_$$"

BACKUP_FILE=$(ls -t "${BACKUP_DIR}"/stockscanner_*.sql.gz 2>/dev/null | head -1)

if [ -z "$BACKUP_FILE" ]; then
    echo "[restore-drill] No backup file found in ${BACKUP_DIR} — skipping (fresh deploy?)"
    exit 0
fi

EXIT_CODE=0
FAIL_REASON=""

cleanup() {
    kill "$PGPID" 2>/dev/null || true
    rm -rf "$PGDATA" "$PGSOCKET"
    emit_seq_event
    exit "$EXIT_CODE"
}
trap cleanup EXIT

# 1. initdb + start throwaway postgres on UNIX socket
initdb -D "$PGDATA" --no-locale --encoding=UTF8 -A trust
mkdir -p "$PGSOCKET"
postgres -D "$PGDATA" -k "$PGSOCKET" -h '' &
PGPID=$!
# Wait for socket to appear
until [ -S "${PGSOCKET}/.s.PGSQL.5432" ]; do sleep 0.2; done

# 2. Restore
gunzip -c "$BACKUP_FILE" | psql -h "$PGSOCKET" -U postgres postgres

# 3. Assert row counts
CRITICAL_TABLES="scanner_events trades signal_reviews scanner_configs stock_aggregates"
TABLE_COUNTS=""
for TABLE in $CRITICAL_TABLES; do
    COUNT=$(psql -h "$PGSOCKET" -U postgres postgres -At \
            -c "SELECT COUNT(*) FROM ${TABLE}" 2>/dev/null || echo "0")
    TABLE_COUNTS="${TABLE_COUNTS} ${TABLE}=${COUNT}"
    if [ "$COUNT" -eq 0 ]; then
        FAIL_REASON="table ${TABLE} has 0 rows"
        EXIT_CODE=1
    fi
done

# 4. Assert alembic_version
if [ -n "$EXPECTED_ALEMBIC_HEAD" ]; then
    ACTUAL_HEAD=$(psql -h "$PGSOCKET" -U postgres postgres -At \
                  -c "SELECT version_num FROM alembic_version" 2>/dev/null || echo "")
    if [ "$ACTUAL_HEAD" != "$EXPECTED_ALEMBIC_HEAD" ]; then
        FAIL_REASON="${FAIL_REASON:+${FAIL_REASON}; }alembic_version mismatch: got '${ACTUAL_HEAD}' expected '${EXPECTED_ALEMBIC_HEAD}'"
        EXIT_CODE=1
    fi
fi
# (cleanup trap fires, emits Seq event, kills postgres, removes temp dirs)
```

### Seq event emission

On both success and failure, the cleanup trap posts a CLEF event to `$SEQ_URL`. Example:
```json
{
  "@t": "2026-06-22T04:07:31Z",
  "@mt": "Restore drill {Verdict}",
  "@l": "Error",
  "BackupFile": "stockscanner_20260621_030012.sql.gz",
  "Verdict": "failed",
  "FailReason": "table trades has 0 rows",
  "scanner_events": 1842,
  "trades": 0,
  "signal_reviews": 120,
  "scanner_configs": 3,
  "stock_aggregates": 95201,
  "AlembicHead": "a7f3c2e1b8d9"
}
```
`@l` is `Information` on pass, `Error` on failure. An Seq alert rule on
`@l = 'Error' and backup.restore_drill = 'failed'` drives notifications.

---

## Alternatives Considered

### Alternative 1 — Docker socket (rejected)

Run `docker run --rm postgres:15-alpine` from inside the drill container. Rejected
because:
- Requires granting docker socket access to the drill container (security regression).
- The `db-backup` service has no socket access; the drill should match that posture.
- The "provably untouched" acceptance criterion is weaker — the container would be on
  `stockscanner-network` with the means to reach the live DB.

### Alternative 2 — Extend `Dockerfile.backup` (not chosen)

Add `postgresql15` server package to the existing backup image so both services share
one image. Simpler build graph, but:
- The backup service image grows ~40MB for functionality it never uses.
- Separate Dockerfiles make the build context explicit and image purpose obvious.
- `Dockerfile.restore-drill` mirrors `Dockerfile.backup` closely; maintenance overhead
  is low.

### Alternative 3 — Dynamic alembic head from live DB (rejected)

Query `SELECT version_num FROM alembic_version` against `stockscanner-db` before the
drill to get the expected head dynamically. Rejected because it re-introduces a live DB
connection, contradicting the hermetic design. `EXPECTED_ALEMBIC_HEAD` env var is the
right separation — the operator updates `.env` when migrations change, and
`deployment-guide.md` documents this maintenance step.

---

## Open Questions (non-blocking)

1. **Offsite backup** — issue #90 notes cloud storage as a future consideration. The
   restore drill assumes local `BACKUP_DIR`. If offsite storage is added later, the
   drill would need to pull the most recent artifact from the remote; that is out of
   scope here.
2. **Seq alert rule** — creating a Seq alert rule for `backup.restore_drill` failures
   is documented (how to set it up) but not automated. Requires a human to create the
   rule in the Seq UI.
3. **Memory limit** — 256M is estimated based on restoring a typical small MarketHawk
   DB. Very large databases (>1M stock_aggregates rows) may require tuning.

---

## Assumptions

- `EXPECTED_ALEMBIC_HEAD` will be set in `.env` before the first deploy; if unset the
  alembic check is skipped with a logged warning (not a failure), allowing the service
  to start on fresh installs before the operator knows the head.
- The `postgresql15` and `postgresql15-client` packages on Alpine 3.19 install
  compatible versions (both 15.x) — no version mismatch between dump and restore.
- `BACKUP_DIR` on the host contains only `stockscanner_*.sql.gz` files from the
  `db-backup` service; no manual files with the same naming pattern are present.
- The drill volume mount (`:ro`) is sufficient proof that the live DB volume
  (`markethawk_postgres_data`) is never touched; no additional isolation is needed.
