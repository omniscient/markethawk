#!/bin/sh
# Weekly restore drill — restores the latest pg_dump into a throwaway postgres container,
# asserts row counts for critical tables, checks alembic_version, emits a Seq event,
# and tears down the throwaway container unconditionally via trap.
#
# Critical tables must have COUNT(*) > 0 after restore for the drill to pass.
# alembic_version must have at least one row (confirms schema migration was restored).
# Failure emits a Seq Error event; success emits an Information event.
# Both include per-table counts as a structured field.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-stockscanner}"
PGPASSWORD="${PGPASSWORD:-}"
SEQ_URL="${SEQ_URL:-}"
DRILL_NETWORK="${DRILL_NETWORK:-markethawk_stockscanner-network}"
RESTORE_POSTGRES_IMAGE="${RESTORE_POSTGRES_IMAGE:-postgres:15-alpine}"
# Optional: set to a specific alembic revision to assert exact head match
ALEMBIC_EXPECTED_HEAD="${ALEMBIC_EXPECTED_HEAD:-}"

CRITICAL_TABLES="scanner_events trades signal_reviews scanner_configs stock_aggregates"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DRILL_CONTAINER="mh-restore-drill-${TIMESTAMP}"

EXIT_CODE=0
VERDICT="success"
ERROR_REASON=""
COUNTS_JSON="{}"
LATEST_BACKUP=""
ALEMBIC_VERSION=""

cleanup() {
    # Unconditional teardown — always attempt to remove the throwaway container
    docker rm -f "${DRILL_CONTAINER}" >/dev/null 2>&1 || true

    if [ -n "${SEQ_URL}" ]; then
        SEQ_LEVEL="Information"
        [ "${VERDICT}" = "failure" ] && SEQ_LEVEL="Error"
        curl -sf -X POST \
            "${SEQ_URL}/api/events/raw?clef" \
            -H "Content-Type: application/vnd.serilog.clef" \
            -d "{\"@t\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"@mt\":\"Database restore drill ${VERDICT}\",\"@l\":\"${SEQ_LEVEL}\",\"EventType\":\"backup.restore_drill\",\"Verdict\":\"${VERDICT}\",\"ErrorReason\":\"${ERROR_REASON}\",\"TableCounts\":${COUNTS_JSON},\"AlembicVersion\":\"${ALEMBIC_VERSION}\",\"BackupFile\":\"${LATEST_BACKUP}\"}" \
            || true
    fi

    exit "${EXIT_CODE}"
}

trap cleanup EXIT

# --- Step 1: Find the most recent backup ---
LATEST_BACKUP=$(ls -t "${BACKUP_DIR}"/stockscanner_*.sql.gz 2>/dev/null | head -1 || true)
if [ -z "${LATEST_BACKUP}" ]; then
    echo "restore-drill: ERROR — no backup files found in ${BACKUP_DIR}" >&2
    VERDICT="failure"
    ERROR_REASON="no backup files found in ${BACKUP_DIR}"
    EXIT_CODE=1
    exit 1
fi
echo "restore-drill: using backup $(basename "${LATEST_BACKUP}")"

# --- Step 2: Spin up throwaway postgres container on the compose network ---
docker run -d \
    --name "${DRILL_CONTAINER}" \
    --network "${DRILL_NETWORK}" \
    -e POSTGRES_USER="${POSTGRES_USER}" \
    -e POSTGRES_PASSWORD="${PGPASSWORD}" \
    -e POSTGRES_DB="${POSTGRES_DB}" \
    "${RESTORE_POSTGRES_IMAGE}" >/dev/null
echo "restore-drill: started throwaway container ${DRILL_CONTAINER}"

# --- Step 3: Wait up to 30 s for postgres to be ready ---
READY=0
for i in $(seq 1 30); do
    if PGPASSWORD="${PGPASSWORD}" pg_isready \
            -h "${DRILL_CONTAINER}" \
            -U "${POSTGRES_USER}" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
if [ "${READY}" -eq 0 ]; then
    echo "restore-drill: ERROR — throwaway postgres did not become ready within 30 s" >&2
    VERDICT="failure"
    ERROR_REASON="throwaway postgres did not become ready within 30 s"
    EXIT_CODE=1
    exit 1
fi
echo "restore-drill: throwaway postgres ready"

# --- Step 4: Restore the dump ---
if ! gunzip -c "${LATEST_BACKUP}" | PGPASSWORD="${PGPASSWORD}" psql \
        -h "${DRILL_CONTAINER}" \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        -v ON_ERROR_STOP=1 \
        >/dev/null 2>/tmp/restore_stderr; then
    RESTORE_ERR=$(head -1 /tmp/restore_stderr 2>/dev/null || true)
    echo "restore-drill: ERROR — restore failed: ${RESTORE_ERR}" >&2
    VERDICT="failure"
    ERROR_REASON="psql restore failed: ${RESTORE_ERR}"
    EXIT_CODE=1
    exit 1
fi
echo "restore-drill: restore complete"

# --- Step 5: Assert row counts > 0 for critical tables ---
FAILED_TABLES=""
FIRST=1
COUNTS_JSON="{"
for TABLE in ${CRITICAL_TABLES}; do
    COUNT=$(PGPASSWORD="${PGPASSWORD}" psql \
        -h "${DRILL_CONTAINER}" \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        -t -c "SELECT COUNT(*) FROM ${TABLE}" 2>/dev/null | tr -d ' \n' || echo "0")
    COUNT="${COUNT:-0}"

    if [ "${FIRST}" -eq 1 ]; then
        FIRST=0
    else
        COUNTS_JSON="${COUNTS_JSON},"
    fi
    COUNTS_JSON="${COUNTS_JSON}\"${TABLE}\":${COUNT}"

    if [ "${COUNT}" -le 0 ] 2>/dev/null || [ "${COUNT}" = "0" ]; then
        FAILED_TABLES="${FAILED_TABLES} ${TABLE}"
    fi
done
COUNTS_JSON="${COUNTS_JSON}}"
echo "restore-drill: table counts: ${COUNTS_JSON}"

if [ -n "${FAILED_TABLES}" ]; then
    echo "restore-drill: ERROR — zero rows in:${FAILED_TABLES}" >&2
    VERDICT="failure"
    ERROR_REASON="zero rows in critical tables:${FAILED_TABLES}"
    EXIT_CODE=1
    exit 1
fi

# --- Step 6: Assert alembic_version is non-empty ---
ALEMBIC_VERSION=$(PGPASSWORD="${PGPASSWORD}" psql \
    -h "${DRILL_CONTAINER}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    -t -c "SELECT version_num FROM alembic_version LIMIT 1" 2>/dev/null | tr -d ' \n' || true)

if [ -z "${ALEMBIC_VERSION}" ]; then
    echo "restore-drill: ERROR — alembic_version table empty or missing" >&2
    VERDICT="failure"
    ERROR_REASON="alembic_version table empty or missing after restore"
    EXIT_CODE=1
    exit 1
fi

# Optional strict head check
if [ -n "${ALEMBIC_EXPECTED_HEAD}" ] && [ "${ALEMBIC_VERSION}" != "${ALEMBIC_EXPECTED_HEAD}" ]; then
    echo "restore-drill: ERROR — alembic head mismatch: got ${ALEMBIC_VERSION}, expected ${ALEMBIC_EXPECTED_HEAD}" >&2
    VERDICT="failure"
    ERROR_REASON="alembic head mismatch: got ${ALEMBIC_VERSION}, expected ${ALEMBIC_EXPECTED_HEAD}"
    EXIT_CODE=1
    exit 1
fi

echo "restore-drill: PASS — backup=$(basename "${LATEST_BACKUP}") alembic=${ALEMBIC_VERSION}"
# Cleanup + Seq emit happen in the trap
