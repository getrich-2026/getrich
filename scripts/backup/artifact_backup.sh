#!/usr/bin/env bash
# Backtest artifact backup script for GetRich platform.
#
# Usage:
#   scripts/backup/artifact_backup.sh
#   ARTIFACT_DIR=/var/lib/getrich/artifacts BACKUP_DIR=/var/backups/getrich/artifact ./artifact_backup.sh
#
# What gets backed up:
#   The artifact directory contains:
#     - manifest.json (per run)
#     - equity.parquet (Polars / pyarrow)
#     - fills.parquet
#     - tear_sheet.html
#     - metrics.json
#   These are needed to re-display a backtest result without
#   having to re-run it.
#
# Strategy:
#   tar+gz the whole artifact dir, with a manifest of the
#   last N runs (so we don't back up runs older than RETENTION).
#   This is a "best effort" backup — if the artifact is half-
#   written, the tar will still succeed (gzip doesn't require
#   consistency).
#
# Recovery:
#   tar -xzf getrich-artifact-YYYYMMDD-HHMMSS.tar.gz -C /var/lib/getrich/artifacts
#
# Environment variables (with defaults):
#   ARTIFACT_DIR   /var/lib/getrich/artifacts
#   BACKUP_DIR     /var/backups/getrich/artifact
#   RETENTION_DAYS 60 (artifacts are kept longer than DB; cheap to retain)

set -euo pipefail

ARTIFACT_DIR="${ARTIFACT_DIR:-/var/lib/getrich/artifacts}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/getrich/artifact}"
RETENTION_DAYS="${RETENTION_DAYS:-60}"

if [[ ! -d "${ARTIFACT_DIR}" ]]; then
    echo "ERROR: ARTIFACT_DIR ${ARTIFACT_DIR} does not exist" >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_FILE="${BACKUP_DIR}/getrich-artifact-${TIMESTAMP}.tar.gz"

echo "[$(date -Iseconds)] Artifact backup starting → ${ARCHIVE_FILE}"
echo "    source=${ARTIFACT_DIR}"

# tar -C switches to ARTIFACT_DIR so the archive contains relative
# paths (./<run_id>/...) — the absolute-path alternative makes
# extraction risky if the target FS layout differs.
# --warning=no-file-changed: parquet files are atomically renamed
# during the write, so tar can sometimes race the rename. We
# tolerate the warning rather than failing the backup.
tar -C "${ARTIFACT_DIR}" \
    --ignore-command-error \
    --warning=no-file-changed \
    -czf "${ARCHIVE_FILE}" \
    ./

ARCHIVE_SIZE=$(du -h "${ARCHIVE_FILE}" | cut -f1)
echo "[$(date -Iseconds)] Artifact backup complete (${ARCHIVE_SIZE})"

# Prune old archives
PRUNED=$(find "${BACKUP_DIR}" -maxdepth 1 -name 'getrich-artifact-*.tar.gz' -mtime +${RETENTION_DAYS} -delete -print | wc -l)
echo "[$(date -Iseconds)] Pruned ${PRUNED} archives older than ${RETENTION_DAYS} days"

echo "${ARCHIVE_FILE}"
