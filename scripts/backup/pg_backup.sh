#!/usr/bin/env bash
# PostgreSQL backup script for GetRich platform.
#
# Usage:
#   scripts/backup/pg_backup.sh                  # full backup, default config
#   BACKUP_DIR=/var/backups/getrich scripts/backup/pg_backup.sh
#   PG_HOST=localhost PG_USER=quant ./pg_backup.sh
#
# Cron suggestion (daily 02:00 UTC+8 = 18:00 UTC):
#   0 2 * * * /opt/getrich/scripts/backup/pg_backup.sh >> /var/log/getrich-backup.log 2>&1
#
# Retention:
#   - Daily dumps: 30 days (cleaned by `pg_backup.sh --prune` or manually)
#   - Monthly snapshots: 12 months
#
# Recovery:
#   pg_restore -U quant -d getrich /var/backups/getrich/getrich-YYYY-MM-DD.dump
#
# Environment variables (with defaults):
#   PG_HOST       localhost
#   PG_PORT       5432
#   PG_USER       quant
#   PGPASSWORD    (required, should come from .pgpass or env)
#   PG_DB         getrich
#   BACKUP_DIR    /var/backups/getrich
#   RETENTION_DAYS 30

set -euo pipefail

PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-quant}"
PG_DB="${PG_DB:-getrich}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/getrich}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [[ -z "${PGPASSWORD:-}" ]]; then
    echo "ERROR: PGPASSWORD env var is required (or set up ~/.pgpass)" >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DUMP_FILE="${BACKUP_DIR}/getrich-pg-${TIMESTAMP}.dump"

echo "[$(date -Iseconds)] PG backup starting → ${DUMP_FILE}"
echo "    host=${PG_HOST}:${PG_PORT} db=${PG_DB} user=${PG_USER}"

# -Fc = custom format (compressed, parallel-restore capable)
# -Z 9 = max compression (slower but smaller; ~3x ratio for our data)
# --no-owner = don't emit ALTER OWNER statements (we replay them on restore)
# --no-acl = skip GRANT/REVOKE (we manage perms via migrations)
pg_dump \
    -h "${PG_HOST}" \
    -p "${PG_PORT}" \
    -U "${PG_USER}" \
    -d "${PG_DB}" \
    -Fc -Z 9 \
    --no-owner --no-acl \
    -f "${DUMP_FILE}"

DUMP_SIZE=$(du -h "${DUMP_FILE}" | cut -f1)
echo "[$(date -Iseconds)] PG backup complete (${DUMP_SIZE})"

# Prune old daily dumps
PRUNED=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'getrich-pg-*.dump' -mtime +${RETENTION_DAYS} -delete -print | wc -l)
echo "[$(date -Iseconds)] Pruned ${PRUNED} dumps older than ${RETENTION_DAYS} days"

# Echo the file path so callers can pick it up (e.g. for S3 upload)
echo "${DUMP_FILE}"
