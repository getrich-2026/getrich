"""Smoke tests for the coverage gate introduced in Round #1161.

We don't try to run pytest-cov here (the test sandbox lacks
the dependency); we verify the *config* invariants the rest of
the pipeline relies on:

1. pyproject.toml has the [tool.coverage.*] blocks.
2. ``branch = true`` is set (engine code has lots of if/else).
3. ``source`` lists the right packages (NOT tests/).
4. ``exclude_lines`` covers the standard "skip me" comments.
5. The CI workflow invokes pytest with --cov-fail-under.
6. The threshold in CI matches the documented floor in
   pyproject.toml (we read the YAML, not the comment, so a
   future drift fails this test).
7. The measure_coverage.sh script is present and has the
   ``set -euo pipefail`` strict mode line (matches the
   pre-commit hook policy from Round #1159).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

# ``tomllib`` was added in Python 3.11. The CI matrix runs on
# 3.10, 3.11, 3.12, and 3.13, so prefer the stdlib module and
# fall back to ``tomli`` (already a transitive dev dep via
# pip's PEP 517 build) on older interpreters.
if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef, import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPT = REPO_ROOT / "scripts" / "measure_coverage.sh"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ci() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. pyproject.toml coverage config
# ---------------------------------------------------------------------------


def test_coverage_run_block_exists(pyproject: dict) -> None:
    assert "coverage" in pyproject["tool"], (
        "pyproject.toml is missing [tool.coverage]; CI will fall back "
        "to coverage's defaults (e.g. branch=False, no exclude_lines)"
    )
    assert "run" in pyproject["tool"]["coverage"], (
        "missing [tool.coverage.run]; pytest-cov needs `source` and `branch`"
    )
    assert "report" in pyproject["tool"]["coverage"], (
        "missing [tool.coverage.report]; missing-lines display will be "
        "the ugly default"
    )


def test_coverage_branch_is_enabled(pyproject: dict) -> None:
    """Branch coverage is required for the engine's many if/else
    paths (execution / account / portfolio). Without it, a 100%
    line-coverage score can hide a missing else-branch.
    """
    run = pyproject["tool"]["coverage"]["run"]
    assert run.get("branch") is True, (
        f"branch coverage must be enabled (got {run.get('branch')!r}); "
        f"otherwise 100% line-coverage hides missing else-branches"
    )


def test_coverage_source_lists_correct_packages(pyproject: dict) -> None:
    """The ``source`` list is the DENOMINATOR of the coverage
    percentage. Including tests/ inflates the denominator
    (tests/ is 100% covered by definition) and the reported
    percentage stays high while real source drifts; excluding
    getrich / getrich_backtest from ``source`` means we get a
    0% report because the coverage tool finds nothing to
    measure.
    """
    source = pyproject["tool"]["coverage"]["run"].get("source", [])
    expected = {"getrich", "getrich_backtest"}
    assert expected.issubset(set(source)), (
        f"coverage.run.source must include {expected}, got {source}"
    )
    # And NO test paths. Match a few unambiguous signals —
    # any of these is enough to fail the test:
    #   - the literal substring "tests/" or "test_"
    #   - the entry is "tests" or starts with "test"
    bad = [
        s for s in source
        if s.startswith("test")
        or s == "tests"
        or "tests/" in s
        or s.endswith("_test")
    ]
    assert not bad, (
        f"coverage.run.source must not include test paths; "
        f"tests/ inflates the denominator: {bad} (full: {source})"
    )


def test_exclude_lines_includes_standard_pragmas(pyproject: dict) -> None:
    """Standard "skip me" comments must be in exclude_lines so
    a missing ``pragma: no cover`` in a defensive branch
    doesn't drag the percentage down.
    """
    exclude = pyproject["tool"]["coverage"]["report"].get("exclude_lines", [])
    must_have = {
        "pragma: no cover",
        "raise NotImplementedError",
        "if __name__ == .__main__.:",
    }
    missing = must_have - set(exclude)
    assert not missing, (
        f"coverage.report.exclude_lines is missing standard pragmas: "
        f"{sorted(missing)}; a defensive `raise NotImplementedError` "
        f"would drag the percentage down"
    )


# ---------------------------------------------------------------------------
# 2. CI gate
# ---------------------------------------------------------------------------


def _ci_test_step(ci: dict) -> str:
    """Return the body of the test step in the ci.yml workflow.

    The CI yaml structure is::
        jobs:
          test:
            steps:
              - name: Run tests
                run: |
                  uv run pytest ... --cov-fail-under=60
    We walk into jobs.test.steps to find the step with name
    'Run tests', which is where the pytest invocation lives.
    """
    test_job = ci["jobs"]["test"]
    for step in test_job["steps"]:
        if step.get("name") == "Run tests":
            return step["run"]
    raise AssertionError(
        "ci.yml is missing a 'Run tests' step in jobs.test; "
        "the coverage gate can't be wired up"
    )


def test_ci_runs_pytest_with_cov(ci: dict) -> None:
    body = _ci_test_step(ci)
    assert "--cov=" in body, (
        "ci.yml's 'Run tests' step must pass at least one --cov=<pkg> "
        "flag; without it pytest-cov measures nothing"
    )


def test_ci_has_cov_fail_under(ci: dict) -> None:
    body = _ci_test_step(ci)
    match = re.search(r"--cov-fail-under=(\d+)", body)
    assert match, (
        "ci.yml's 'Run tests' step must set --cov-fail-under=<N>; "
        "without it the threshold gate doesn't fire"
    )
    floor = int(match.group(1))
    assert 0 < floor <= 100, (
        f"coverage floor must be a percentage 1-100, got {floor}"
    )


def test_ci_floor_matches_documented_policy(ci: dict) -> None:
    """The CI floor is the SINGLE SOURCE OF TRUTH for the gate.
    The pyproject.toml comment block in [tool.coverage.*] documents
    a 60→70→80 schedule; we hard-fail this test if the CI floor
    drifts off the schedule (catches a manual edit that doesn't
    update the docs).
    """
    body = _ci_test_step(ci)
    match = re.search(r"--cov-fail-under=(\d+)", body)
    assert match
    floor = int(match.group(1))
    # Round #1161 initial floor; bump to 70 next quarter, etc.
    assert floor in (60, 70, 80), (
        f"CI coverage floor is {floor}; the policy is 60 → 70 → 80. "
        f"If you're intentionally raising, update the comment in "
        f"pyproject.toml [tool.coverage.*] AND this test."
    )


def test_ci_emits_terminal_missing_report(ci: dict) -> None:
    """The terminal report shows the N lowest-covered files so a
    reviewer can spot what regressed in the diff. Without this
    flag, CI just shows a single percentage.
    """
    body = _ci_test_step(ci)
    assert "--cov-report=term-missing" in body, (
        "ci.yml 'Run tests' step must include --cov-report=term-missing; "
        "otherwise the PR diff shows only a percentage, not the "
        "covered/uncovered columns"
    )


# ---------------------------------------------------------------------------
# 3. measure_coverage.sh local script
# ---------------------------------------------------------------------------


def test_measure_coverage_script_exists() -> None:
    assert SCRIPT.is_file(), (
        f"missing {SCRIPT.relative_to(REPO_ROOT)}; the local coverage "
        f"script is what a developer runs to verify the gate before pushing"
    )


def test_measure_coverage_script_uses_strict_mode() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text, (
        f"{SCRIPT.name} is missing `set -euo pipefail`; an unset variable "
        f"or failed command would silently continue"
    )


def test_measure_coverage_script_mentions_cov_packages() -> None:
    """Belt-and-suspenders: the script must enumerate the
    --cov packages even though pyproject.toml also lists them.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--cov=getrich" in text, (
        f"{SCRIPT.name} must pass --cov=getrich so coverage is enabled "
        f"even if pyproject.toml's [tool.coverage.run].source is later "
        f"replaced with `[\"auto\"]`"
    )
    assert "--cov=getrich_backtest" in text, (
        f"{SCRIPT.name} must pass --cov=getrich_backtest (the engine is "
        f"in a separate package and is easy to miss)"
    )
