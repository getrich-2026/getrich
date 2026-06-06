#!/usr/bin/env bash
# Local coverage measurement script.
#
# Mirrors what CI runs (in .github/workflows/ci.yml) so a developer
# can verify the gate locally before pushing. CI sets a hard floor
# via ``--cov-fail-under``; here we make the floor OPTIONAL via
# the COVERAGE_FLOOR env var (default 0 = report only, no failure).
#
# Usage:
#   scripts/measure_coverage.sh                 # report only
#   COVERAGE_FLOOR=60 scripts/measure_coverage.sh  # fail if < 60%
#   scripts/measure_coverage.sh html            # also write htmlcov/
#   scripts/measure_coverage.sh xml             # also write coverage.xml
#
# Exits 0 when coverage >= floor (or no floor), 1 otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

FLOOR="${COVERAGE_FLOOR:-0}"
EXTRA_ARGS=()

# Optional positional arg: "html" / "xml" / "html,xml" to emit
# those formats in addition to the terminal report.
FORMAT="${1:-}"
case "${FORMAT}" in
    html)
        EXTRA_ARGS+=("--cov-report=html")
        ;;
    xml)
        EXTRA_ARGS+=("--cov-report=xml")
        ;;
    "html,xml")
        EXTRA_ARGS+=("--cov-report=html")
        EXTRA_ARGS+=("--cov-report=xml")
        ;;
    "")
        # report-only
        ;;
    *)
        echo "Unknown format: ${FORMAT}" >&2
        echo "Usage: $0 [html|xml|html,xml]" >&2
        exit 2
        ;;
esac

if [[ "${FLOOR}" -gt 0 ]]; then
    echo "[measure_coverage] floor = ${FLOOR}%"
    EXTRA_ARGS+=("--cov-fail-under=${FLOOR}")
fi

# The same packages as pyproject.toml [tool.coverage.run].source.
# Listing them here is a belt-and-suspenders in case pyproject is
# ever changed to use ``--cov=auto``.
PACKAGES=(
    "getrich"
    "getrich_backtest"
)

# Same exclusion as CI (the ``--ignore`` flag keeps tests/scripts out
# of the run-time collection; tests/ is the pytest rootdir so the
# filter is a defense-in-depth).
uv run --frozen pytest \
    --cov=getrich \
    --cov=getrich_backtest \
    --cov-report=term-missing \
    --no-cov-on-fail \
    --timeout=120 \
    "${EXTRA_ARGS[@]}" \
    tests/getrich_backtest tests/getrich/apps tests/libs tests/repo tests/scripts
