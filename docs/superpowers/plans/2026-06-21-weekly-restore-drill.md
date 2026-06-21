# Implementation Plan: Weekly Restore Drill (`db-restore-drill` sidecar)

**Goal:** Add a `db-restore-drill` Docker sidecar that runs weekly, restores the most recent
`pg_dump` artifact into an ephemeral postgres cluster (UNIX socket only, never the live DB),
asserts data integrity, emits a structured Seq CLEF event, and tears down unconditionally.

**Issue:** #386  
**Spec:** `docs/superpowers/specs/2026-06-21-weekly-restore-drill-design.md`  
**Date:** 2026-06-21

---

## Architecture

No changes to existing services. Pure additions:

- **New Docker service**: `db-restore-drill` in `docker-compose.yml`
- **New Dockerfile**: `docker/Dockerfile.restore-drill` (mirrors `Dockerfile.backup`, adds postgresql15 server)
- **New scripts**: `scripts/restore-drill.sh`, `scripts/restore-drill-entrypoint.sh`
- **Docs**: `deployment-guide.md` (new "Weekly Restore Drill" subsection under Database Backup), `ENV_VARIABLES.md` (new `db-restore-drill` table)

The drill uses `initdb` + `postgres` on a UNIX socket inside the container — no TCP listener, no
network exposure, no live DB credentials needed. The backup volume is mounted `:ro`.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `docker/Dockerfile.restore-drill` | Create | Alpine 3.19 + postgresql15 (server + client) + supercronic |
| `scripts/restore-drill-entrypoint.sh` | Create | Write supercronic crontab from env, exec supercronic |
| `scripts/restore-drill.sh` | Create | Core drill: find backup, initdb, restore, assert, emit Seq, teardown |
| `docker-compose.yml` | Edit | Add `db-restore-drill` service block |
| `deployment-guide.md` | Edit | Add "Weekly Restore Drill" subsection |
| `ENV_VARIABLES.md` | Edit | Add `db-restore-drill` env var table |

---

## Tasks

### Task 1 — `docker/Dockerfile.restore-drill`

**Files:** `docker/Dockerfile.restore-drill`

#### TDD Steps

**1a. Write failing test (check file is absent):**
```bash
ls docker/Dockerfile.restore-drill
# Expected: ls: cannot access 'docker/Dockerfile.restore-drill': No such file or directory
```

**1b. Implement:**

Create `docker/Dockerfile.restore-drill`:
```dockerfile
FROM alpine:3.19@sha256:6baf43584bcb78f2e5847d1de515f23499913ac9f12bdf834811a3145eb11ca1

# postgresql15 (server) provides initdb, postgres, pg_ctl; postgresql15-client provides psql.
# On Alpine both packages install binaries under /usr/bin via symlinks to /usr/lib/postgresql15/bin.
RUN apk add --no-cache postgresql15-client postgresql15 curl

# Install supercronic (arch-aware) — same version as Dockerfile.backup
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

**Note (memory pattern baked in):** Scripts are copied to `/entrypoint.sh` (outside `/app`) per the
`dark-factory-ops.md` [PATTERN] for standalone sidecars — the `docker-compose.override.yml`
bind-mount targets `/app`, so files outside it remain visible at runtime.

**1c. Verify — syntax check:**
```bash
# Dockerfile has no separate syntax check; verify the file exists and is non-empty
wc -l docker/Dockerfile.restore-drill
# Expected: 28 docker/Dockerfile.restore-drill
```

**1d. Commit:**
```bash
git add docker/Dockerfile.restore-drill
git commit -m "chore(restore-drill): add Dockerfile.restore-drill (Alpine + postgresql15 + supercronic) (#386)"
```
Expected output: `[refine/issue-386-... <sha>] chore(restore-drill): add Dockerfile...`

---

### Task 2 — `scripts/restore-drill-entrypoint.sh`

**Files:** `scripts/restore-drill-entrypoint.sh`

#### TDD Steps

**2a. Write failing test (file is absent):**
```bash
ls scripts/restore-drill-entrypoint.sh
# Expected: No such file
```

**2b. Implement:**

Create `scripts/restore-drill-entrypoint.sh`:
```sh
#!/bin/sh
# Entrypoint for db-restore-drill container: writes crontab from env, then runs supercronic.
# Mirrors scripts/backup-entrypoint.sh structure.
set -eu

RESTORE_DRILL_SCHEDULE="${RESTORE_DRILL_SCHEDULE:-0 4 * * 0}"

CRONTAB_FILE="/tmp/restore-drill-crontab"
printf '%s /scripts/restore-drill.sh >> /proc/1/fd/1 2>&1\n' "${RESTORE_DRILL_SCHEDULE}" > "${CRONTAB_FILE}"

echo "db-restore-drill: schedule='${RESTORE_DRILL_SCHEDULE}'"

exec /usr/local/bin/supercronic "${CRONTAB_FILE}"
```

**2c. Verify — syntax check:**
```bash
bash -n scripts/restore-drill-entrypoint.sh
# Expected: (no output — clean parse)
```

**2d. Commit:**
```bash
git add scripts/restore-drill-entrypoint.sh
git commit -m "chore(restore-drill): add restore-drill-entrypoint.sh (supercronic crontab writer) (#386)"
```

---

### Task 3 — `scripts/restore-drill.sh` (core drill logic)

**Files:** `scripts/restore-drill.sh`

This is the main implementation. The drill:
1. Finds the most recent `stockscanner_*.sql.gz` in `BACKUP_DIR`
2. Runs `initdb` on a temp dir, starts postgres on a UNIX socket (no TCP, no live DB contact)
3. Restores via `gunzip | psql`
4. Asserts row counts > 0 for five critical tables
5. Asserts `alembic_version` matches `EXPECTED_ALEMBIC_HEAD` (skips with warning if env var unset)
6. Always emits a CLEF event to Seq (best-effort) — `@l=Information` on pass, `@l=Error` on fail
7. Always kills postgres and removes temp dirs (unconditional `trap`)

**Memory pattern (architecture.md):** Use embedded `initdb` + `postgres` on UNIX socket — no docker socket access, no TCP listener. The live `stockscanner-db` is provably untouched because no credentials or network connection to it are established.

#### TDD Steps

**3a. Write a smoke test script:**

Create `scripts/test-restore-drill-noop.sh` (temporary test helper, not committed in final plan):
```sh
#!/bin/sh
# Smoke test: no-backup-file path exits 0 with the right log message.
set -e
TMPDIR_TEST=$(mktemp -d)
export BACKUP_DIR="${TMPDIR_TEST}/empty"
mkdir -p "$BACKUP_DIR"
export SEQ_URL=""
export EXPECTED_ALEMBIC_HEAD=""

OUTPUT=$(sh scripts/restore-drill.sh 2>&1) || EXIT=$?
if ! echo "$OUTPUT" | grep -q "No backup file found"; then
    echo "FAIL: expected 'No backup file found' in output"
    echo "Got: $OUTPUT"
    rm -rf "$TMPDIR_TEST"
    exit 1
fi
echo "PASS: no-backup exit 0 path works"
rm -rf "$TMPDIR_TEST"
```

**3b. Run failing test (script doesn't exist yet):**
```bash
bash scripts/test-restore-drill-noop.sh
# Expected: sh: scripts/restore-drill.sh: No such file or directory
```

**3c. Implement:**

Create `scripts/restore-drill.sh`:
```sh
#!/bin/sh
# Weekly restore drill — restores the latest pg_dump into a throwaway postgres cluster,
# asserts data integrity, emits a Seq CLEF event, and tears down unconditionally.
# Never connects to the live stockscanner-db; the backup volume is mounted :ro.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
SEQ_URL="${SEQ_URL:-}"
EXPECTED_ALEMBIC_HEAD="${EXPECTED_ALEMBIC_HEAD:-}"

# Unique per-run temp paths prevent collisions on overlapping runs
PGDATA="/tmp/drill_pgdata_$$"
PGSOCKET="/tmp/drill_socket_$$"

PGPID=""
EXIT_CODE=0
FAIL_REASON=""
BACKUP_FILE=""
ACTUAL_HEAD=""

# Per-table counts (populated after restore)
COUNT_scanner_events=0
COUNT_trades=0
COUNT_signal_reviews=0
COUNT_scanner_configs=0
COUNT_stock_aggregates=0

# Emit a CLEF event to Seq — always called from the cleanup trap (best-effort).
emit_seq_event() {
    [ -z "${SEQ_URL}" ] && return 0
    VERDICT="passed"
    SEQ_LEVEL="Information"
    if [ "${EXIT_CODE}" -ne 0 ]; then
        VERDICT="failed"
        SEQ_LEVEL="Error"
    fi
    PAYLOAD="{\"@t\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"@mt\":\"Restore drill {Verdict}\",\"@l\":\"${SEQ_LEVEL}\",\"Verdict\":\"${VERDICT}\",\"BackupFile\":\"$(basename "${BACKUP_FILE:-none}")\",\"FailReason\":\"${FAIL_REASON}\",\"AlembicHead\":\"${ACTUAL_HEAD}\",\"scanner_events\":${COUNT_scanner_events},\"trades\":${COUNT_trades},\"signal_reviews\":${COUNT_signal_reviews},\"scanner_configs\":${COUNT_scanner_configs},\"stock_aggregates\":${COUNT_stock_aggregates}}"
    curl -sf -X POST \
        "${SEQ_URL}/api/events/raw?clef" \
        -H "Content-Type: application/vnd.serilog.clef" \
        -d "${PAYLOAD}" \
        || true
}

cleanup() {
    if [ -n "${PGPID}" ]; then
        kill "${PGPID}" 2>/dev/null || true
        # Wait briefly so postgres releases locks before we rm the data dir
        sleep 0.5
    fi
    rm -rf "${PGDATA}" "${PGSOCKET}"
    emit_seq_event
    exit "${EXIT_CODE}"
}
trap cleanup EXIT

# ── 1. Find most recent backup ─────────────────────────────────────────────────
BACKUP_FILE=$(ls -t "${BACKUP_DIR}"/stockscanner_*.sql.gz 2>/dev/null | head -1 || true)

if [ -z "${BACKUP_FILE}" ]; then
    echo "[restore-drill] No backup file found in ${BACKUP_DIR} — skipping (fresh deploy or pre-first-backup window)"
    exit 0
fi

echo "[restore-drill] Using backup: ${BACKUP_FILE}"

# ── 2. Bootstrap throwaway postgres on UNIX socket (no TCP, no live DB contact) ─
mkdir -p "${PGDATA}" "${PGSOCKET}"
initdb -D "${PGDATA}" --no-locale --encoding=UTF8 -A trust -U postgres >/dev/null 2>&1

postgres -D "${PGDATA}" -k "${PGSOCKET}" -h '' >/dev/null 2>&1 &
PGPID=$!

# Wait up to 10 s for the socket to appear
WAIT=0
until [ -S "${PGSOCKET}/.s.PGSQL.5432" ]; do
    sleep 0.2
    WAIT=$((WAIT + 1))
    if [ "${WAIT}" -ge 50 ]; then
        FAIL_REASON="throwaway postgres did not start within 10s"
        EXIT_CODE=1
        exit 1
    fi
done

echo "[restore-drill] Throwaway postgres started (PID ${PGPID})"

# ── 3. Restore ────────────────────────────────────────────────────────────────
if ! gunzip -c "${BACKUP_FILE}" | psql -h "${PGSOCKET}" -U postgres postgres >/dev/null 2>/tmp/restore_stderr; then
    FAIL_REASON="restore failed: $(head -1 /tmp/restore_stderr 2>/dev/null)"
    EXIT_CODE=1
    exit 1
fi

echo "[restore-drill] Restore complete"

# ── 4. Assert row counts > 0 for critical tables ──────────────────────────────
_count() {
    psql -h "${PGSOCKET}" -U postgres postgres -At \
         -c "SELECT COUNT(*) FROM $1" 2>/dev/null || echo "0"
}

COUNT_scanner_events=$(_count scanner_events)
COUNT_trades=$(_count trades)
COUNT_signal_reviews=$(_count signal_reviews)
COUNT_scanner_configs=$(_count scanner_configs)
COUNT_stock_aggregates=$(_count stock_aggregates)

for TABLE in scanner_events trades signal_reviews scanner_configs stock_aggregates; do
    eval "CNT=\${COUNT_${TABLE}}"
    echo "[restore-drill] ${TABLE}: ${CNT} rows"
    if [ "${CNT}" -eq 0 ]; then
        FAIL_REASON="${FAIL_REASON:+${FAIL_REASON}; }table ${TABLE} has 0 rows"
        EXIT_CODE=1
    fi
done

# ── 5. Assert alembic_version (skipped with warning if EXPECTED_ALEMBIC_HEAD unset) ─
if [ -n "${EXPECTED_ALEMBIC_HEAD}" ]; then
    ACTUAL_HEAD=$(psql -h "${PGSOCKET}" -U postgres postgres -At \
                  -c "SELECT version_num FROM alembic_version LIMIT 1" 2>/dev/null || echo "")
    if [ "${ACTUAL_HEAD}" != "${EXPECTED_ALEMBIC_HEAD}" ]; then
        FAIL_REASON="${FAIL_REASON:+${FAIL_REASON}; }alembic_version mismatch: got '${ACTUAL_HEAD}' expected '${EXPECTED_ALEMBIC_HEAD}'"
        EXIT_CODE=1
    else
        echo "[restore-drill] alembic_version: ${ACTUAL_HEAD} (matches expected)"
    fi
else
    echo "[restore-drill] WARNING: EXPECTED_ALEMBIC_HEAD not set — alembic version check skipped"
fi

# cleanup trap fires here: kills postgres, rm -rf temp dirs, emits Seq event, exits EXIT_CODE
```

**3d. Run smoke test (verify pass):**
```bash
bash -n scripts/restore-drill.sh
# Expected: (no output — clean syntax)

bash scripts/test-restore-drill-noop.sh
# Expected: PASS: no-backup exit 0 path works
```

**3e. Commit:**
```bash
git add scripts/restore-drill.sh
git commit -m "feat(restore-drill): add restore-drill.sh — initdb/socket restore, assertions, Seq emit (#386)"
```

---

### Task 4 — `docker-compose.yml`: add `db-restore-drill` service

**Files:** `docker-compose.yml`

#### TDD Steps

**4a. Verify service is absent:**
```bash
grep "db-restore-drill" docker-compose.yml
# Expected: (no output — service not yet defined)
```

**4b. Implement:**

Locate the `db-backup:` block in `docker-compose.yml`. Add the `db-restore-drill` service
immediately after the `db-backup` block (before the `# Redis for caching...` comment):

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

Key design notes baked in from spec:
- **No `depends_on: [postgres]`** — the drill never contacts the live DB; the throwaway cluster is ephemeral.
- **`:ro` volume mount** — the drill can never corrupt or delete backup artifacts.
- **No exposed ports** — the throwaway postgres runs on a UNIX socket inside the container.

**4c. Verify — YAML parse:**
```bash
docker compose config --quiet
# Expected: (no output — valid YAML)
```

**4d. Verify — build succeeds:**
```bash
docker compose build db-restore-drill
# Expected: last line contains "=> exporting to image" or "Successfully built <sha>"
```

**4e. Verify — no-backup path via manual one-shot:**
```bash
# Ensure BACKUP_DIR exists (may be empty on fresh deploy)
mkdir -p "${BACKUP_DIR:-/var/lib/markethawk/backups}"

docker compose run --rm db-restore-drill /scripts/restore-drill.sh
# Expected output includes:
# [restore-drill] No backup file found in /backups — skipping (fresh deploy or pre-first-backup window)
# Exit code 0
echo "Exit: $?"
```

**4f. Verify — full drill path (requires a real backup on disk):**
```bash
# Only run this if a backup exists
if ls "${BACKUP_DIR:-/var/lib/markethawk/backups}"/stockscanner_*.sql.gz 2>/dev/null | head -1; then
    docker compose run --rm db-restore-drill /scripts/restore-drill.sh
    # Expected: restore completes, row counts printed, exit 0
fi
```

**4g. Commit:**
```bash
git add docker-compose.yml
git commit -m "feat(restore-drill): add db-restore-drill service to docker-compose.yml (#386)"
```

---

### Task 5 — Documentation: `deployment-guide.md` + `ENV_VARIABLES.md`

**Files:** `deployment-guide.md`, `ENV_VARIABLES.md`

#### TDD Steps

**5a. Verify sections are absent:**
```bash
grep "Restore Drill" deployment-guide.md
# Expected: (no output)

grep "RESTORE_DRILL_SCHEDULE\|EXPECTED_ALEMBIC_HEAD" ENV_VARIABLES.md
# Expected: (no output)
```

**5b. Implement — `deployment-guide.md`:**

After the existing `**Restore procedure**` code block (line ~90 in the file), add:

```markdown

---

### Weekly Restore Drill

The `db-restore-drill` sidecar automatically validates each weekly backup by restoring it
into a throwaway postgres cluster and asserting data integrity — no human action required.

**How it works**

1. Finds the most recent `stockscanner_*.sql.gz` in `BACKUP_DIR`.
2. Starts an ephemeral postgres cluster on a UNIX socket inside the container (`initdb` +
   `postgres -h ''`). The live `stockscanner-db` is never contacted.
3. Restores the dump with `gunzip | psql`.
4. Asserts row count > 0 for five critical tables: `scanner_events`, `trades`,
   `signal_reviews`, `scanner_configs`, `stock_aggregates`.
5. Asserts `alembic_version` matches `EXPECTED_ALEMBIC_HEAD` (skipped with a warning if
   that env var is unset).
6. Emits a structured Seq CLEF event (`@mt = "Restore drill {Verdict}"`) — level
   `Information` on pass, `Error` on failure.
7. Kills the throwaway postgres and removes temp dirs unconditionally (trap on all exits).

The backup volume is mounted **read-only** (`:ro`); the drill cannot corrupt or delete backups.

**Schedule and manual invocation**

Runs weekly by default (Sundays at 4 AM UTC — one hour after the daily 3 AM backup).

```bash
# Trigger a manual one-shot drill (e.g., after first backup, to verify immediately)
docker compose run --rm db-restore-drill /scripts/restore-drill.sh
```

**Configuration (`.env`)**

| Variable | Default | Description |
|---|---|---|
| `RESTORE_DRILL_SCHEDULE` | `0 4 * * 0` | Supercronic cron expression (UTC) for the weekly drill |
| `EXPECTED_ALEMBIC_HEAD` | *(empty)* | Expected alembic migration head; if unset the alembic check is skipped with a warning. Set this to the output of `docker compose exec backend python -m alembic current` before deploying. |

**Reading drill events in Seq**

Open Seq and filter by:
- Pass: `@l = 'Information' and Verdict = 'passed'`
- Failure: `@l = 'Error' and Verdict = 'failed'`

Each event includes `BackupFile`, per-table row counts (`scanner_events`, `trades`, etc.),
`AlembicHead`, and (on failure) `FailReason`.

**Setting up a Seq alert rule for drill failures**

In Seq → Alerts → Add Alert Rule:
- Signal filter: `@l = 'Error' and Verdict = 'failed'`
- Count threshold: ≥ 1 in 1 hour
- Notification: your preferred channel (email, Slack, etc.)

**Deliberately triggering a failure (smoke test)**

```bash
# Create a truncated (corrupt) backup to verify the drill fails loudly
echo "NOT A VALID PG DUMP" | gzip > ${BACKUP_DIR:-/var/lib/markethawk/backups}/stockscanner_test_corrupt.sql.gz
docker compose run --rm db-restore-drill /scripts/restore-drill.sh
# Expected: restore fails, Seq Error event emitted, exit code 1
# Clean up afterward:
rm ${BACKUP_DIR:-/var/lib/markethawk/backups}/stockscanner_test_corrupt.sql.gz
```
```

**5c. Implement — `ENV_VARIABLES.md`:**

After the existing `## Database Backup (`db-backup` service)` table and before the `---` separator, add:

```markdown

## Database Restore Drill (`db-restore-drill` service)

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESTORE_DRILL_SCHEDULE` | `0 4 * * 0` | Supercronic cron expression (UTC) controlling when `restore-drill.sh` runs; default is Sundays at 4 AM UTC (one hour after the 3 AM backup) |
| `EXPECTED_ALEMBIC_HEAD` | *(empty)* | Expected `alembic_version.version_num`; if empty the alembic check is skipped with a log warning. Set to the output of `docker compose exec backend python -m alembic current` before each migration-bearing deploy. |
```

**5d. Verify — check new sections are present:**
```bash
grep -c "Restore Drill" deployment-guide.md
# Expected: >= 2 (heading + body reference)

grep "RESTORE_DRILL_SCHEDULE" ENV_VARIABLES.md
# Expected: | `RESTORE_DRILL_SCHEDULE` | ...

grep "EXPECTED_ALEMBIC_HEAD" ENV_VARIABLES.md
# Expected: | `EXPECTED_ALEMBIC_HEAD` | ...
```

**5e. Commit:**
```bash
git add deployment-guide.md ENV_VARIABLES.md
git commit -m "docs(restore-drill): document weekly restore drill, Seq events, env vars (#386)"
```

---

## Acceptance Criteria Mapping

| Spec requirement | Task | Addressed by |
|---|---|---|
| Weekly schedule via `RESTORE_DRILL_SCHEDULE` (default `0 4 * * 0`) | T2, T4 | Entrypoint crontab writer; docker-compose env |
| Latest backup selection; skip on empty dir | T3 | `ls -t ... | head -1`; `exit 0` path |
| Throwaway postgres on UNIX socket, no TCP, no live DB contact | T3 | `initdb` + `postgres -h ''`; no `depends_on: [postgres]` |
| `gunzip | psql` restore | T3 | Step 3 in restore-drill.sh |
| Row count > 0 assertions for 5 tables | T3 | `_count()` helper + loop |
| `alembic_version` assertion vs `EXPECTED_ALEMBIC_HEAD` | T3 | Steps 5 in restore-drill.sh |
| Seq CLEF event on pass (Information) and fail (Error) | T3 | `emit_seq_event()` in cleanup trap |
| Unconditional teardown via trap | T3 | `trap cleanup EXIT` |
| `:ro` backup volume mount | T4 | `volumes: ... :ro` in docker-compose |
| Manual one-shot invocation documented | T4, T5 | `docker compose run --rm db-restore-drill` |
| `deployment-guide.md` section | T5 | New "Weekly Restore Drill" subsection |
| `ENV_VARIABLES.md` entries | T5 | New `db-restore-drill` table |
| Drill survives `docker-compose up -d` recreation | T4 | `restart: unless-stopped` |
| Corrupted dump makes drill fail loudly | T3, T5 | Restore step exits non-zero → `@l=Error` event |
| Live DB provably untouched | T3, T4 | No DB credentials, no `depends_on: [postgres]`, UNIX socket only |

---

## Commit Sequence

```
Task 1: chore(restore-drill): add Dockerfile.restore-drill (Alpine + postgresql15 + supercronic) (#386)
Task 2: chore(restore-drill): add restore-drill-entrypoint.sh (supercronic crontab writer) (#386)
Task 3: feat(restore-drill): add restore-drill.sh — initdb/socket restore, assertions, Seq emit (#386)
Task 4: feat(restore-drill): add db-restore-drill service to docker-compose.yml (#386)
Task 5: docs(restore-drill): document weekly restore drill, Seq events, env vars (#386)
```

---

## Open Questions (non-blocking, from spec)

1. **Offsite backup**: the drill assumes local `BACKUP_DIR`. If cloud storage is added later
   (issue #90 deferred), the drill needs a pull step; out of scope here.
2. **Seq alert rule**: the docs explain how to create the rule manually in the Seq UI — not automated.
3. **Memory limit**: 256M is estimated for a typical small MarketHawk DB. Very large databases
   (>1M `stock_aggregates` rows) may require tuning via `COMPOSE_MEMORY_LIMIT` in `.env`.
