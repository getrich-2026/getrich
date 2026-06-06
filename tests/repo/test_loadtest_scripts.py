"""Smoke tests for the k6 load-test scripts.

The k6 binary isn't available in the test sandbox (and we
don't want to run 50 VUs against staging from a unit-test
runner). What we DO verify:

1. Each script parses as JavaScript (Node's `node --check`).
2. Each script exports a k6 `default` function and an
   `options` block.
3. Each script declares `thresholds` (so a regression on a
   CI run fails loudly).
4. The URL/auth handling reads `BASE_URL`, `TEST_USER_EMAIL`,
   `TEST_USER_PASSWORD` env vars consistently.
5. The auth script uses the correct auth endpoints
   (`/v1/auth/login`, `/v1/auth/refresh`).
6. No script imports anything we don't vendored (i.e. uses
   the standard k6/http and k6/metrics modules).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOADTEST = REPO_ROOT / "loadtest"

SCRIPTS = [
    "auth_smoke.js",
    "read_traffic.js",
    "backtest_submit.js",
    "live_signals.js",
]


# ---------------------------------------------------------------------------
# 1. File presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_exists(script: str) -> None:
    assert (LOADTEST / script).is_file(), (
        f"missing load test script: loadtest/{script}"
    )


def test_loadtest_readme_exists() -> None:
    """A new SRE should be able to find the load test scripts
    via a top-level README, not by grepping the repo.
    """
    readme = LOADTEST / "README.md"
    assert readme.is_file(), "loadtest/README.md missing"
    text = readme.read_text(encoding="utf-8")
    # The README must list all the scripts (otherwise a reader
    # doesn't know they exist).
    for s in SCRIPTS:
        assert s in text, f"loadtest/README.md does not mention {s}"


# ---------------------------------------------------------------------------
# 2. JS syntax (Node --check, fall back to brace-balance)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_is_valid_javascript(script: str) -> None:
    """k6 scripts are JavaScript (ES modules). We use Node's
    ``--check`` flag to syntax-validate; if Node isn't
    available (rare), we fall back to a brace-balance check
    (loose but better than nothing).
    """
    path = LOADTEST / script
    if shutil.which("node") is not None:
        proc = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            pytest.fail(
                f"loadtest/{script} has JS syntax error:\n"
                f"  stderr: {proc.stderr}\n"
                f"  stdout: {proc.stdout}"
            )
        return

    # Fallback: brace/paren/bracket balance. This catches
    # gross mistakes but not e.g. a missing semicolon.
    text = path.read_text(encoding="utf-8")
    counts = {
        "{": text.count("{"),
        "}": text.count("}"),
        "(": text.count("("),
        ")": text.count(")"),
        "[": text.count("["),
        "]": text.count("]"),
    }
    if counts["{"] != counts["}"]:
        pytest.fail(
            f"loadtest/{script} has unbalanced braces: "
            f"{counts['{']} '{{' vs {counts['}']} '}}'"
        )
    if counts["("] != counts[")"]:
        pytest.fail(
            f"loadtest/{script} has unbalanced parens: "
            f"{counts['(']} '(' vs {counts[')']} ')'"
        )


# ---------------------------------------------------------------------------
# 3. Structural invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_exports_options_and_default(script: str) -> None:
    """k6 looks for ``export const options`` and
    ``export default function``. Missing either makes the
    script a no-op (k6 will silently run 1 iteration with
    no traffic).
    """
    text = (LOADTEST / script).read_text(encoding="utf-8")
    assert re.search(r"export\s+const\s+options", text), (
        f"loadtest/{script} missing `export const options`"
    )
    assert re.search(
        r"export\s+default\s+function", text
    ), f"loadtest/{script} missing `export default function`"


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_has_thresholds(script: str) -> None:
    """A script without ``thresholds`` will never fail a CI
    run, even if p99 latency is 30 seconds. Catch the
    oversight locally.
    """
    text = (LOADTEST / script).read_text(encoding="utf-8")
    assert "thresholds:" in text, (
        f"loadtest/{script} has no `thresholds` block; "
        f"a perf regression would pass CI silently"
    )


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_uses_only_k6_imports(script: str) -> None:
    """We vendored the k6 runtime via the k6 binary; the
    scripts must not import anything outside k6 (the
    top-level module exports `check` / `sleep`) or
    k6/* sub-modules. A typo like ``import http from
    'k6http'`` would fail at k6 runtime, not at parse time.
    """
    text = (LOADTEST / script).read_text(encoding="utf-8")
    imports = re.findall(r"^import\s+.*?from\s+['\"]([^'\"]+)['\"]", text, re.M)
    for module in imports:
        # k6 modules are either the bare "k6" (for check/sleep)
        # or "k6/*" sub-modules (k6/http, k6/metrics, etc).
        assert module == "k6" or module.startswith("k6/"), (
            f"loadtest/{script} imports '{module}' which is not a "
            f"k6 or k6/* module; k6 runtime will fail to resolve it"
        )


# ---------------------------------------------------------------------------
# 4. Env var consistency
# ---------------------------------------------------------------------------


EXPECTED_ENV_VARS = {
    "BASE_URL",
    "TEST_USER_EMAIL",
    "TEST_USER_PASSWORD",
    # K6_VUS / K6_DURATION are k6's standard CLI overrides; the
    # README documents them alongside BASE_URL.
    "K6_VUS",
    "K6_DURATION",
}


@pytest.mark.parametrize("script", SCRIPTS)
def test_loadtest_script_uses_standard_env_vars(script: str) -> None:
    """The README documents a fixed set of env vars. A script
    using a non-standard name (e.g. ``API_URL`` instead of
    ``BASE_URL``) breaks the documented workflow.
    """
    text = (LOADTEST / script).read_text(encoding="utf-8")
    # Allow digits so K6_VUS / K6_DURATION aren't truncated to
    # just "K".
    found = set(re.findall(r"__ENV\.([A-Z_][A-Z0-9_]*)", text))
    extra = found - EXPECTED_ENV_VARS
    assert not extra, (
        f"loadtest/{script} uses non-standard env vars: {sorted(extra)}; "
        f"documented vars are {sorted(EXPECTED_ENV_VARS)}"
    )
    # Every script that needs auth must read all 3.
    # auth_smoke needs only BASE_URL+creds, others need the same.
    missing = EXPECTED_ENV_VARS - found
    if script == "auth_smoke.js":
        # auth_smoke explicitly tests /v1/auth/login, so it
        # needs the creds.
        assert not missing, (
            f"loadtest/{script} missing required env vars: {sorted(missing)}"
        )
    else:
        assert not missing, (
            f"loadtest/{script} missing required env vars: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# 5. Auth script uses the right endpoints
# ---------------------------------------------------------------------------


def test_auth_smoke_uses_login_and_refresh() -> None:
    """The auth smoke test is the contract for what an
    "auth works" baseline looks like. If someone changes
    /v1/auth/login to /api/v1/auth/login without updating
    this script, the load test silently passes 0% (no auth
    → no requests to anything that needs auth).
    """
    text = (LOADTEST / "auth_smoke.js").read_text(encoding="utf-8")
    assert "/v1/auth/login" in text, (
        "auth_smoke.js doesn't hit /v1/auth/login; smoke test "
        "no longer exercises the real auth path"
    )
    assert "/v1/auth/refresh" in text, (
        "auth_smoke.js doesn't hit /v1/auth/refresh; we lose "
        "coverage of the token-refresh SLO"
    )


# ---------------------------------------------------------------------------
# 6. Read traffic hits documented dashboard endpoints
# ---------------------------------------------------------------------------


EXPECTED_READ_ENDPOINTS = [
    "/v1/strategies",
    "/v1/signals",
]


def test_read_traffic_hits_documented_dashboard_endpoints() -> None:
    """The read-traffic script is the regression canary for
    the dashboard's N+1 query problem. If someone refactors
    strategies to live under /v2/ and forgets to update the
    load test, the script exercises a 404 — and looks like
    a 0% RPS success rate instead of a real bug.
    """
    text = (LOADTEST / "read_traffic.js").read_text(encoding="utf-8")
    for ep in EXPECTED_READ_ENDPOINTS:
        assert ep in text, (
            f"read_traffic.js no longer hits {ep}; the load test "
            f"drifts from the real dashboard and gives false negatives"
        )
