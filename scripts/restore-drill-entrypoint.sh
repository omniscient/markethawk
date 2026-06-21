#!/bin/sh
# Entrypoint for the db-restore-drill container: writes crontab from env, then runs supercronic.
set -eu

RESTORE_DRILL_SCHEDULE="${RESTORE_DRILL_SCHEDULE:-0 4 * * 0}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

mkdir -p "${BACKUP_DIR}"

CRONTAB_FILE="/tmp/restore-drill-crontab"
printf '%s /scripts/restore-drill.sh >> /proc/1/fd/1 2>&1\n' "${RESTORE_DRILL_SCHEDULE}" > "${CRONTAB_FILE}"

echo "db-restore-drill: schedule='${RESTORE_DRILL_SCHEDULE}' dir=${BACKUP_DIR}"

exec /usr/local/bin/supercronic "${CRONTAB_FILE}"
