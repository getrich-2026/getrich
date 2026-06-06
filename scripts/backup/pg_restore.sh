#!/usr/bin/env bash
# PostgreSQL restore script for GetRich platform.
#
# Usage:
#   scripts/backup/pg_restore.sh /var/backups/getrich/getrich-pg-YYYYMMDD.dump
#   DROP_FIRST=1 scripts/backup/pg_restore.sh <dump_file>
#
# WARNING: this script DESTROYS data in the target DB. Use
# DROP_FIRST=1 with caution; the default behaviour is to ADD
# tables / data to the existing DB.
#
# Recovery workflow (DR scenario):
#   1. Stop API + worker
#       systemctl stop getrich-api getrich-worker.target
#   2. Drop + recreate DB
#       DROP_FIRST=1 ./pg_restore.sh <dump>
#   3. Run migrations (in case the dump is older than the
#      current migration set)
#       uv run getrich-migrate postgres
#   4. Restart services
#       systemctl start getrich-api getrich-worker.target
#   5. Verify
#       curl http://localhost:8000/health
#       psql -c "SELECT count(*) FROM frontend.signals"
#
# Environment variables:
#   PG_HOST, PG_PORT, PG_USER, PGPASSWORD, PG_DB  (same as pg_backup.sh)
#   DROP_FIRST  1 to drop + recreate the DB before restore (default 0)

set -euo pipefail

DUMP_FILE="${1:-}"
if [[ -z "${DUMP_FILE}" ]]; then
    echo "Usage: $0 <dump_file> [DROP_FIRST=1]" >&2
    exit 1
fi
if [[ ! -f "${DUMP_FILE}" ]]; then
    echo "ERROR: dump file ${DUMP_FILE} not found" >&2
    exit 1
fi

PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-quant}"
PG_DB="${PG_DB:-getrich}"
DROP_FIRST="${DROP_FIRST:-0}"

if [[ -z "${PGPASSWORD:-}" ]]; then
    echo "ERROR: PGPASSWORD env var is required" >&2
    exit 1
fi

echo "[$(date -Iseconds)] PG restore starting from ${DUMP_FILE}"

if [[ "${DROP_FIRST}" == "1" ]]; then
    echo "    DROP_FIRST=1: dropping + recreating ${PG_DB}..."
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d postgres \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${PG_DB}' AND pid <> pg_backend_pid();" \
        -c "DROP DATABASE IF EXISTS ${PG_DB};" \
        -c "CREATE DATABASE ${PG_DB};"
fi

# pg_restore flags:
#   -d <db>         target db
#   --no-owner      skip ALTER OWNER (we apply via migrations)
#   --no-acl        skip GRANT/REVOKE
#   --jobs=4        parallel restore
#   -Fc             input is custom format (matches pg_dump -Fc)
pg_restore -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
    -d "${PG_DB}" \
    --no-owner --no-acl \
    --jobs=4 \
    "${DUMP_FILE}"

echo "[$(date -Iseconds)] PG restore complete"

# Sanity check: row count on a key table
ROW_COUNT=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'frontend'")
echo "    frontend.* tables present: ${ROW_COUNT}"
if [[ "${ROW_COUNT}" -lt 5 ]]; then
    echo "WARN: fewer than 5 frontend tables found; dump may be from a pre-migration era" >&2
fi
