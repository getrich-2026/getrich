#!/usr/bin/env bash
# ClickHouse restore script for GetRich platform.
#
# Usage:
#   scripts/backup/ch_restore.sh /var/backups/getrich/ch/freeze-YYYYMMDD-HHMMSS
#
# WARNING: this script OVERWRITES the CH data directory for
# the named tables. It assumes you've stopped clickhouse-server
# first.
#
# Recovery workflow (DR scenario):
#   1. Stop clickhouse-server
#       systemctl stop clickhouse-server
#   2. Stop API + worker (they will reconnect on restart)
#       systemctl stop getrich-api getrich-worker.target
#   3. Wipe the affected table's data dir
#       rm -rf /var/lib/clickhouse/data/default/md_bars_1m/
#   4. Restore from backup
#       ./ch_restore.sh /var/backups/getrich/ch/freeze-YYYYMMDD-HHMMSS
#   5. Start clickhouse-server
#       systemctl start clickhouse-server
#   6. Verify
#       clickhouse-client --query "SELECT count() FROM default.md_bars_1m"
#   7. Start API + worker
#       systemctl start getrich-api getrich-worker.target
#
# Strategy:
#   CH's FREEZE PARTITION creates a snapshot under
#   /var/lib/clickhouse/shadow/. The backup script cp -a's that
#   into BACKUP_DIR. To restore we copy the shadow subtree back
#   into /var/lib/clickhouse/data/, which is what CH reads on
#   startup. We use --remove-pre-existing to overwrite any partial
#   restore.

set -euo pipefail

SNAPSHOT_DIR="${1:-}"
if [[ -z "${SNAPSHOT_DIR}" ]]; then
    echo "Usage: $0 <snapshot_dir>" >&2
    exit 1
fi
if [[ ! -d "${SNAPSHOT_DIR}" ]]; then
    echo "ERROR: snapshot dir ${SNAPSHOT_DIR} not found" >&2
    exit 1
fi

# Confirm CH is down (refuse to restore into a live server — the
# data dir is locked while CH is running and the cp will silently
# corrupt).
if systemctl is-active --quiet clickhouse-server 2>/dev/null; then
    echo "ERROR: clickhouse-server is still running. Stop it first." >&2
    echo "    systemctl stop clickhouse-server" >&2
    exit 2
fi

DATA_DIR="/var/lib/clickhouse/data"
echo "[$(date -Iseconds)] CH restore starting from ${SNAPSHOT_DIR}"
echo "    target=${DATA_DIR}"

# The shadow snapshot has the structure
#   <DATA_DIR>/<database>/<table>/<partition>/...
# so we rsync it into DATA_DIR.
# We DON'T --delete because we only want to restore the tables
# the backup contains; other DBs / tables on the server should
# be left alone.
rsync -a "${SNAPSHOT_DIR}/data/" "${DATA_DIR}/"

# Fix ownership (the rsync preserves mode but may not preserve
# ownership if the backup was made as a different user; CH runs
# as clickhouse).
chown -R clickhouse:clickhouse "${DATA_DIR}/" 2>/dev/null || \
    echo "WARN: chown clickhouse failed; check DATA_DIR permissions manually" >&2

echo "[$(date -Iseconds)] CH restore complete"
echo "    Next: systemctl start clickhouse-server"
echo "    Then verify with: clickhouse-client --query 'SELECT count() FROM default.md_bars_1m'"
