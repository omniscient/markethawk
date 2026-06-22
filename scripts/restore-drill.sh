#!/bin/sh
# Weekly restore drill — restores the latest pg_dump into a throwaway postgres cluster
# (initdb + UNIX socket, no TCP, no live DB contact), asserts row counts for critical
# tables, checks alembic_version, emits a Seq event, and tears down the cluster
# unconditionally via trap.
#
# Critical tables must have COUNT(*) > 0 after restore for the drill to pass.
# alembic_version must have at least one row (confirms schema migration was restored).
# Failure emits a Seq Error event; success emits an Information event.
# Both include per-table counts as a structured field.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
SEQ_URL="${SEQ_URL:-}"
# Set to a specific alembic revision to assert exact head match; empty = non-empty check only
EXPECTED_ALEMBIC_HEAD="${EXPECTED_ALEMBIC_HEAD:-}"

CRITICAL_TABLES="scanner_events trades signal_reviews scanner_configs stock_aggregates"

PGDATA="/tmp/drill_pgdata_$$"
PGSOCKET="/tmp/drill_socket_$$"
PGPID=""

EXIT_CODE=0
VERDICT="passed"
FAIL_REASON=""
COUNTS_JSON="{}"
ALEMBIC_HEAD=""
LATEST_BACKUP=""

cleanup() {
    # Unconditional teardown: kill throwaway postgres and remove temp dirs
    [ -n "${PGPID}" ] && kill "${PGPID}" 2>/dev/null || true
    rm -rf "${PGDATA}" "${PGSOCKET}"

    if [ -n "${SEQ_URL}" ]; then
        SEQ_LEVEL="Information"
        [ "${VERDICT}" = "failed" ] && SEQ_LEVEL="Error"
        curl -sf -X POST \
            "${SEQ_URL}/api/events/raw?clef" \
            -H "Content-Type: application/vnd.serilog.clef" \
            -d "{\"@t\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"@mt\":\"Restore drill {Verdict}\",\"@l\":\"${SEQ_LEVEL}\",\"EventType\":\"backup.restore_drill\",\"Verdict\":\"${VERDICT}\",\"FailReason\":\"${FAIL_REASON}\",\"AlembicHead\":\"${ALEMBIC_HEAD}\",\"BackupFile\":\"$(basename "${LATEST_BACKUP:-none}")\",\"TableCounts\":${COUNTS_JSON}}" \
            || true
    fi

    exit "${EXIT_CODE}"
}

# --- Step 1: Find the most recent backup ---
LATEST_BACKUP=$(ls -t "${BACKUP_DIR}"/stockscanner_*.sql.gz 2>/dev/null | head -1 || true)
if [ -z "${LATEST_BACKUP}" ]; then
    echo "restore-drill: no backup found in ${BACKUP_DIR} — skipping (fresh deploy?)"
    exit 0
fi
echo "restore-drill: using backup $(basename "${LATEST_BACKUP}")"

# Backup confirmed — register cleanup trap (nothing to tear down in the skip path above)
trap cleanup EXIT

# --- Step 2: initdb throwaway postgres cluster on UNIX socket (no TCP listener) ---
mkdir -p "${PGDATA}" "${PGSOCKET}"
initdb -D "${PGDATA}" --no-locale --encoding=UTF8 -A trust -U postgres >/dev/null 2>&1
postgres -D "${PGDATA}" -k "${PGSOCKET}" -h '' >/dev/null 2>&1 &
PGPID=$!
echo "restore-drill: started throwaway postgres (pid ${PGPID})"

# Wait up to 30 s for socket to appear
READY=0
for i in $(seq 1 30); do
    if [ -S "${PGSOCKET}/.s.PGSQL.5432" ]; then
        READY=1
        break
    fi
    sleep 1
done
if [ "${READY}" -eq 0 ]; then
    echo "restore-drill: ERROR — postgres socket did not appear within 30 s" >&2
    VERDICT="failed"
    FAIL_REASON="throwaway postgres socket did not appear within 30 s"
    EXIT_CODE=1
    exit 1
fi
echo "restore-drill: throwaway postgres ready"

# pg_dump plain format does not include CREATE DATABASE; create it before restoring
psql -h "${PGSOCKET}" -U postgres -c "CREATE DATABASE stockscanner;" >/dev/null 2>&1

# --- Step 3: Restore the dump ---
if ! gunzip -c "${LATEST_BACKUP}" | psql \
        -h "${PGSOCKET}" \
        -U postgres \
        -d stockscanner \
        >/dev/null 2>/tmp/restore_stderr; then
    RESTORE_ERR=$(head -1 /tmp/restore_stderr 2>/dev/null || true)
    echo "restore-drill: ERROR — restore failed: ${RESTORE_ERR}" >&2
    VERDICT="failed"
    FAIL_REASON="psql restore failed: ${RESTORE_ERR}"
    EXIT_CODE=1
    exit 1
fi
echo "restore-drill: restore complete"

# --- Step 4: Assert row counts > 0 for critical tables ---
FAILED_TABLES=""
FIRST=1
COUNTS_JSON="{"
for TABLE in ${CRITICAL_TABLES}; do
    COUNT=$(psql \
        -h "${PGSOCKET}" \
        -U postgres \
        -d stockscanner \
        -t -c "SELECT COUNT(*) FROM ${TABLE}" 2>/dev/null | tr -d ' \n' || echo "0")
    COUNT="${COUNT:-0}"

    if [ "${FIRST}" -eq 1 ]; then
        FIRST=0
    else
        COUNTS_JSON="${COUNTS_JSON},"
    fi
    COUNTS_JSON="${COUNTS_JSON}\"${TABLE}\":${COUNT}"

    if [ "${COUNT}" = "0" ]; then
        FAILED_TABLES="${FAILED_TABLES} ${TABLE}"
    fi
done
COUNTS_JSON="${COUNTS_JSON}}"
echo "restore-drill: table counts: ${COUNTS_JSON}"

if [ -n "${FAILED_TABLES}" ]; then
    echo "restore-drill: ERROR — zero rows in:${FAILED_TABLES}" >&2
    VERDICT="failed"
    FAIL_REASON="zero rows in critical tables:${FAILED_TABLES}"
    EXIT_CODE=1
    exit 1
fi

# --- Step 5: Assert alembic_version is non-empty ---
ALEMBIC_HEAD=$(psql \
    -h "${PGSOCKET}" \
    -U postgres \
    -d stockscanner \
    -t -c "SELECT version_num FROM alembic_version LIMIT 1" 2>/dev/null | tr -d ' \n' || true)

if [ -z "${ALEMBIC_HEAD}" ]; then
    echo "restore-drill: ERROR — alembic_version table empty or missing" >&2
    VERDICT="failed"
    FAIL_REASON="alembic_version table empty or missing after restore"
    EXIT_CODE=1
    exit 1
fi

# Optional strict head check
if [ -n "${EXPECTED_ALEMBIC_HEAD}" ] && [ "${ALEMBIC_HEAD}" != "${EXPECTED_ALEMBIC_HEAD}" ]; then
    echo "restore-drill: ERROR — alembic head mismatch: got ${ALEMBIC_HEAD}, expected ${EXPECTED_ALEMBIC_HEAD}" >&2
    VERDICT="failed"
    FAIL_REASON="alembic head mismatch: got ${ALEMBIC_HEAD} expected ${EXPECTED_ALEMBIC_HEAD}"
    EXIT_CODE=1
    exit 1
fi

echo "restore-drill: PASS — backup=$(basename "${LATEST_BACKUP}") alembic=${ALEMBIC_HEAD}"
# Cleanup trap fires: kills postgres, rm -rf PGDATA/PGSOCKET, emits Seq event
