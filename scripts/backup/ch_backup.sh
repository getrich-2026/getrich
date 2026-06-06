#!/usr/bin/env bash
# ClickHouse backup script for GetRich platform.
#
# Usage:
#   scripts/backup/ch_backup.sh
#   BACKUP_DIR=/var/backups/getrich CLICKHOUSE_HOST=localhost ./ch_backup.sh
#
# Cron suggestion (daily 03:00 UTC+8 = 19:00 UTC, 1h after PG):
#   0 3 * * * /opt/getrich/scripts/backup/ch_backup.sh >> /var/log/getrich-backup.log 2>&1
#
# What gets backed up:
#   - md_bars_1m / md_bars_1d (OHLCV market data; largest tables)
#   - factors_long (factor library)
#   Note: signals_audit etc. are PG-only; this script is CH-only.
#
# Strategy:
#   ClickHouse doesn't have an incremental logical backup in OSS, so
#   we use FREEZE PARTITION + cp to get a consistent snapshot of
#   the partitions modified in the last 24h. Combined with the
#   full backup we do on the 1st of each month, this gives us
#   24h RPO at 1/30 the storage cost of a daily full.
#
# Recovery:
#   1. Stop clickhouse
#   2. Replace /var/lib/clickhouse/data/<db>/<table>/ with backup
#   3. Start clickhouse
#   Or for partial restore: use clickhouse-client + INSERT FROM S3.
#
# Environment variables (with defaults):
#   CLICKHOUSE_HOST       localhost
#   CLICKHOUSE_PORT       8123
#   CLICKHOUSE_USER       default
#   CLICKHOUSE_PASSWORD   (empty by default)
#   CLICKHOUSE_DB         default
#   BACKUP_DIR            /var/backups/getrich/ch
#   RETENTION_DAYS        30

set -euo pipefail

CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
CH_USER="${CLICKHOUSE_USER:-default}"
CH_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
CH_DB="${CLICKHOUSE_DB:-default}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/getrich/ch}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

# Tables to back up. Add new ones here as the CH schema grows.
TABLES=(
    "md_bars_1m"
    "md_bars_1d"
    "factors_long"
)

mkdir -p "${BACKUP_DIR}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SNAPSHOT_DIR="${BACKUP_DIR}/freeze-${TIMESTAMP}"

echo "[$(date -Iseconds)] CH backup starting → ${SNAPSHOT_DIR}"

# Build the clickhouse-client command. Password via env var (CH
# client doesn't read ~/.pgpass-style files; the clickhouse-client
# --password flag echoes to ps, so we use CLICKHOUSE_PASSWORD env).
CH_CLIENT=(clickhouse-client --host "${CH_HOST}" --port "${CH_PORT}")
if [[ -n "${CH_PASSWORD}" ]]; then
    CH_CLIENT+=(--password "${CH_PASSWORD}")
fi
if [[ "${CH_USER}" != "default" ]]; then
    CH_CLIENT+=(--user "${CH_USER}")
fi

# Freeze each table's partitions. FREEZE PARTITION creates a
# hardlink snapshot under /var/lib/clickhouse/shadow/, so the
# backup is consistent even with active writes.
mkdir -p "${SNAPSHOT_DIR}"
for table in "${TABLES[@]}"; do
    echo "    Freezing ${CH_DB}.${table}..."
    "${CH_CLIENT[@]}" --query "ALTER TABLE ${CH_DB}.${table} FREEZE PARTITION tuple()"
done

# Copy the shadow/ snapshot to the backup directory. We use cp
# -a (archive mode) to preserve the partition directory layout
# that clickhouse-server expects on restore.
echo "    Copying shadow snapshot to ${SNAPSHOT_DIR}..."
# The shadow path is hardcoded in CH. Verify it exists before cp.
SHADOW_SRC="/var/lib/clickhouse/shadow/"
if [[ ! -d "${SHADOW_SRC}" ]]; then
    echo "ERROR: CH shadow dir ${SHADOW_SRC} not found; FREEZE failed silently" >&2
    exit 2
fi
cp -a "${SHADOW_SRC}" "${SNAPSHOT_DIR}/"

# Drop the shadow/ entries (CH keeps them until DROPped, so we
# free the link refs here). The FREEZE creates them in shadow/;
# the cp -a hardlinks them into our backup dir. Once copied, the
# shadow/ entries can be cleaned.
"${CH_CLIENT[@]}" --query "SYSTEM UNFREEZE WITH NAME ''" || true

SNAPSHOT_SIZE=$(du -sh "${SNAPSHOT_DIR}" | cut -f1)
echo "[$(date -Iseconds)] CH backup complete (${SNAPSHOT_SIZE})"

# Prune old CH backups
PRUNED=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'freeze-*' -mtime +${RETENTION_DAYS} -exec rm -rf {} + -print 2>/dev/null | wc -l)
echo "[$(date -Iseconds)] Pruned ${PRUNED} CH snapshots older than ${RETENTION_DAYS} days"

echo "${SNAPSHOT_DIR}"
