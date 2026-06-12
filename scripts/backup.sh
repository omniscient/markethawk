#!/bin/sh
# PostgreSQL backup script — dumps, compresses, rotates, and emits Seq events on failure.
# Called by supercronic inside the db-backup container (or manually for ad-hoc backups).
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-stockscanner}"
SEQ_URL="${SEQ_URL:-}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/stockscanner_${TIMESTAMP}.sql.gz"
TMP_FILE="${BACKUP_FILE}.tmp"

EXIT_CODE=0
ERROR_REASON=""

cleanup() {
    # Remove incomplete temp file on any exit
    rm -f "${TMP_FILE}"

    if [ "${EXIT_CODE}" -ne 0 ] && [ -n "${SEQ_URL}" ]; then
        # Emit structured CLEF event to Seq on failure (best-effort, never abort backup run)
        curl -sf -X POST \
            "${SEQ_URL}/api/events/raw?clef" \
            -H "Content-Type: application/vnd.serilog.clef" \
            -d "{\"@t\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"@mt\":\"Database backup failed\",\"@l\":\"Error\",\"BackupStatus\":\"failed\",\"ErrorReason\":\"${ERROR_REASON}\",\"BackupFile\":\"${BACKUP_FILE}\",\"Timestamp\":\"${TIMESTAMP}\"}" \
            || true
    fi

    exit "${EXIT_CODE}"
}

trap cleanup EXIT

mkdir -p "${BACKUP_DIR}"

# Dump to temp file so a partial dump is never left behind as a valid backup
if ! pg_dump \
        -h "${POSTGRES_HOST}" \
        -p "${POSTGRES_PORT}" \
        -U "${POSTGRES_USER}" \
        "${POSTGRES_DB}" \
        | gzip > "${TMP_FILE}" 2>/tmp/pg_dump_stderr; then
    ERROR_REASON="pg_dump exited non-zero: $(cat /tmp/pg_dump_stderr 2>/dev/null | head -1)"
    EXIT_CODE=1
    exit 1
fi

# Verify gzip output is non-empty (catches silent failures)
if [ ! -s "${TMP_FILE}" ]; then
    ERROR_REASON="dump produced empty file"
    EXIT_CODE=1
    exit 1
fi

# Atomic rename: only promote to final name when dump is complete
mv "${TMP_FILE}" "${BACKUP_FILE}"

echo "Backup written: ${BACKUP_FILE} ($(du -sh "${BACKUP_FILE}" | cut -f1))"

# Rotate backups older than retention period
find "${BACKUP_DIR}" -maxdepth 1 -name "stockscanner_*.sql.gz" \
    -mtime "+${BACKUP_RETENTION_DAYS}" -delete

echo "Rotation complete: removed files older than ${BACKUP_RETENTION_DAYS} days"
