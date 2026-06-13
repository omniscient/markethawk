#!/bin/sh
# Entrypoint for the db-backup container: writes crontab from env, then runs supercronic.
set -eu

BACKUP_SCHEDULE="${BACKUP_SCHEDULE:-0 3 * * *}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

mkdir -p "${BACKUP_DIR}"

# Write a crontab file for supercronic at runtime so the schedule is configurable
CRONTAB_FILE="/tmp/backup-crontab"
printf '%s /scripts/backup.sh >> /proc/1/fd/1 2>&1\n' "${BACKUP_SCHEDULE}" > "${CRONTAB_FILE}"

echo "db-backup: schedule='${BACKUP_SCHEDULE}' retention=${BACKUP_RETENTION_DAYS:-30}d dir=${BACKUP_DIR}"

exec /usr/local/bin/supercronic "${CRONTAB_FILE}"
