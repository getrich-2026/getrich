#!/usr/bin/env bash
# Master daily backup script: runs PG + CH + artifact in sequence.
#
# Usage:
#   scripts/backup/daily_backup.sh
#   scripts/backup/daily_backup.sh --skip-ch     # for the dev box
#   scripts/backup/daily_backup.sh --skip-artifact
#
# This is the script wired into the systemd timer (see
# scripts/backup/getrich-backup.{service,timer}). The
# individual pg_backup.sh / ch_backup.sh / artifact_backup.sh
# scripts can be run standalone for one-off recovery scenarios.
#
# Failure handling:
#   The script runs the 3 components in sequence. If PG fails,
#   we still try CH + artifact (they're independent). The
#   script's exit code is 0 only if ALL THREE succeed.
#
# Logging:
#   Output is structured (timestamp + component) so it can be
#   grepped for failures by the runbook's §5 "clickhouse 磁盘满"
#   (any backup that didn't run for 24h is itself an alert).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKIP_PG=0
SKIP_CH=0
SKIP_ARTIFACT=0
for arg in "$@"; do
    case "$arg" in
        --skip-pg) SKIP_PG=1 ;;
        --skip-ch) SKIP_CH=1 ;;
        --skip-artifact) SKIP_ARTIFACT=1 ;;
        --help|-h)
            sed -n '2,15p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
    esac
done

log() { echo "[$(date -Iseconds)] $*"; }
FAILED=()

# 1. PG (highest priority; the business data lives here)
if [[ "${SKIP_PG}" -eq 0 ]]; then
    log "==> PG backup"
    if PGPASSWORD="${PGPASSWORD:-}" bash "${SCRIPT_DIR}/pg_backup.sh" > /tmp/getrich-pg-backup.log 2>&1; then
        log "    PG OK"
    else
        log "    PG FAILED — see /tmp/getrich-pg-backup.log"
        FAILED+=("pg")
    fi
fi

# 2. CH (market data; largest, most important to back up)
if [[ "${SKIP_CH}" -eq 0 ]]; then
    log "==> CH backup"
    if bash "${SCRIPT_DIR}/ch_backup.sh" > /tmp/getrich-ch-backup.log 2>&1; then
        log "    CH OK"
    else
        log "    CH FAILED — see /tmp/getrich-ch-backup.log"
        FAILED+=("ch")
    fi
fi

# 3. Artifact (cheap; keep last)
if [[ "${SKIP_ARTIFACT}" -eq 0 ]]; then
    log "==> Artifact backup"
    if bash "${SCRIPT_DIR}/artifact_backup.sh" > /tmp/getrich-artifact-backup.log 2>&1; then
        log "    Artifact OK"
    else
        log "    Artifact FAILED — see /tmp/getrich-artifact-backup.log"
        FAILED+=("artifact")
    fi
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
    log "BACKUP INCOMPLETE — failed components: ${FAILED[*]}"
    exit 1
fi
log "All backups complete"
