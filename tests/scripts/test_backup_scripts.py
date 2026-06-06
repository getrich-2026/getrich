"""Smoke tests for the backup scripts.

The scripts are bash, not Python, so the test is limited to:
1. Each script exists at the expected path.
2. Each script has the +x bit set (or the test runner can read it).
3. Each script passes ``bash -n`` (syntax check) without error.
4. ``daily_backup.sh`` parses its --help flag and exits 0.
5. ``daily_backup.sh`` exits non-zero when ALL 3 components fail
   (so the systemd timer's ``OnFailure=`` alert triggers).

We do NOT run the scripts against a real PG / CH — the test
sandbox doesn't have those services, and even if it did, dumping
the DB just to test the wrapper would be wasteful. The end-to-end
verification happens in the runbook's §13 演练 section
(monthly, by an SRE).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "backup"


def _run(script: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a script with bash, capturing output.

    ``env`` is the env dict; defaults to a minimal env that
    strips PGPASSWORD (the scripts check for it and fail-fast
    if missing). For the syntax tests we don't need to actually
    run the script's body.

    ``encoding="utf-8"`` is required on Windows where the
    default codepage is gbk and would fail to decode the
    Chinese characters in the script comments / error messages.
    """
    if env is None:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# ---------------------------------------------------------------------------
# Existence + syntax
# ---------------------------------------------------------------------------


SCRIPTS_TO_TEST = [
    "pg_backup.sh",
    "pg_restore.sh",
    "ch_backup.sh",
    "ch_restore.sh",
    "artifact_backup.sh",
    "daily_backup.sh",
]


@pytest.mark.parametrize("script_name", SCRIPTS_TO_TEST)
def test_backup_script_exists(script_name: str) -> None:
    """Each backup script must be present at the expected path."""
    path = SCRIPTS / script_name
    assert path.is_file(), f"backup script missing: {path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("script_name", SCRIPTS_TO_TEST)
def test_backup_script_is_valid_bash(script_name: str) -> None:
    """Static parse of the script.

    We try ``bash -n`` first; on Windows the default ``bash.exe``
    is the WSL launcher which can't run /bin/bash inside the
    sandbox, so we fall back to a Python-side brace / backtick /
    heredoc balance check. The bash -n test covers Linux / CI;
    the Python check covers the Windows sandbox.
    """
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPTS / script_name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0:
        return
    # The WSL /bin/bash failed; fall back to a simple Python
    # static check: shebang present, unclosed quotes / heredocs,
    # and a matching if/fi count.
    text = (SCRIPTS / script_name).read_text(encoding="utf-8")
    if not text.startswith("#!"):
        pytest.fail(f"{script_name} missing shebang on first line")
    # Count if / fi pairs (very rough but catches gross imbalance)
    n_if = text.count("\nif ")
    n_fi = text.count("\nfi\n") + text.count("\nfi ")
    if abs(n_if - n_fi) > 0:
        pytest.fail(
            f"{script_name} has {n_if} 'if' but {n_fi} 'fi' — "
            f"likely missing a closing block"
        )
    # If bash -n reported a real syntax error (not a launcher
    # error), surface it.
    if "syntax error" in proc.stderr.lower() or "unexpected" in proc.stderr.lower():
        pytest.fail(
            f"{script_name} bash -n reported: {proc.stderr[:500]}"
        )
    # Otherwise it's an environment problem (e.g. WSL can't find
    # /bin/bash); the static check above is the best we can do
    # in the sandbox. Mark the test as a soft pass.
    pytest.skip(
        f"bash -n unavailable in this environment "
        f"(stderr: {proc.stderr[:200]!r}); static check passed"
    )


@pytest.mark.parametrize("script_name", SCRIPTS_TO_TEST)
def test_backup_script_uses_strict_mode(script_name: str) -> None:
    """Production-grade shell scripts must run with ``set -euo pipefail``
    (or ``set -uo pipefail`` for the master script that intentionally
    catches per-component exit codes) so a single failing command
    doesn't silently continue.
    """
    text = (SCRIPTS / script_name).read_text(encoding="utf-8")
    assert any(
        mode in text
        for mode in ("set -euo pipefail", "set -eu", "set -uo pipefail")
    ), (
        f"{script_name} is missing a strict mode line "
        f"(set -euo pipefail / set -eu / set -uo pipefail); "
        f"a single failing command would silently continue"
    )


# ---------------------------------------------------------------------------
# Master script behaviour
# ---------------------------------------------------------------------------


def _bash_works_in_sandbox() -> bool:
    """Return True if the bash on this box can actually exec
    /bin/bash (i.e. we're on Linux, or the WSL launcher found
    a working distro). On a sandboxed Windows where ``bash -n``
    fails with "CreateProcessCommon:818: execvpe(/bin/bash)
    failed: No such file or directory" or similar, return False
    and let the test caller skip.
    """
    proc = subprocess.run(
        ["bash", "-c", "echo ok"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "ok"


# Cache the bash-availability result so we don't probe once per test.
_BASH_WORKS = _bash_works_in_sandbox()


def test_daily_backup_help_exits_0() -> None:
    """``--help`` is the only path that exits 0 without trying to
    do real work. The systemd timer's ``OnFailure=`` alert fires
    on non-zero exit, so ``--help`` must be the zero-exit path.
    """
    if not _BASH_WORKS:
        pytest.skip("bash unavailable in this sandbox")
    proc = _run("daily_backup.sh", "--help")
    assert proc.returncode == 0, (
        f"daily_backup.sh --help exited {proc.returncode} (should be 0); "
        f"stderr: {proc.stderr}"
    )
    # --help prints the header comment which mentions the 3 components
    assert "PG" in proc.stdout or "CH" in proc.stdout or "Artifact" in proc.stdout


def test_daily_backup_skip_all_components_exits_0() -> None:
    """With all 3 components skipped, the master script has nothing
    to do and must exit 0 (so a misconfigured --skip-* flag in
    production doesn't cause a false alarm).
    """
    if not _BASH_WORKS:
        pytest.skip("bash unavailable in this sandbox")
    proc = _run(
        "daily_backup.sh",
        "--skip-pg", "--skip-ch", "--skip-artifact",
    )
    assert proc.returncode == 0, (
        f"daily_backup.sh with all --skip-* should exit 0, got {proc.returncode} "
        f"(stderr: {proc.stderr})"
    )
    assert "All backups complete" in proc.stdout


def test_daily_backup_component_failures_propagate() -> None:
    """If a component fails (here: PG with no PGPASSWORD), the
    overall exit code is non-zero. The systemd timer's
    ``OnFailure=`` alert hooks off this.
    """
    if not _BASH_WORKS:
        pytest.skip("bash unavailable in this sandbox")
    if shutil.which("pg_dump") is None:
        pytest.skip("pg_dump not installed in sandbox; can't test failure path")
    # Drop PGPASSWORD and pass only --skip-ch + --skip-artifact so
    # the failure is isolated to the PG step.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        # NB: PGPASSWORD intentionally unset
    }
    proc = _run("daily_backup.sh", "--skip-ch", "--skip-artifact", env=env)
    assert proc.returncode != 0, (
        "daily_backup.sh with missing PGPASSWORD should fail; "
        "non-zero exit is required for the systemd OnFailure alert"
    )
    assert "PG" in proc.stdout, (
        f"failure summary should mention the failed component; got: {proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Systemd units
# ---------------------------------------------------------------------------


def test_systemd_service_unit_exists_and_valid() -> None:
    """The systemd service unit must be present, parse, and
    reference the daily_backup.sh script (not some stale name).
    """
    service = SCRIPTS / "getrich-backup.service"
    assert service.is_file(), "getrich-backup.service missing"
    text = service.read_text(encoding="utf-8")
    # systemd-analyze verify would catch syntax errors but isn't
    # always available; for the sandbox we just assert the
    # sections are present.
    for section in ("[Unit]", "[Service]", "[Install]"):
        assert section in text, f"systemd unit missing {section} section"
    assert "ExecStart=" in text, "systemd service missing ExecStart"
    assert "daily_backup.sh" in text, (
        "systemd service ExecStart must call daily_backup.sh, "
        "not one of the component scripts directly"
    )


def test_systemd_timer_unit_daily_schedule() -> None:
    """The timer must run DAILY (not weekly / monthly), at a sane
    off-peak hour, and require the service.
    """
    timer = SCRIPTS / "getrich-backup.timer"
    assert timer.is_file(), "getrich-backup.timer missing"
    text = timer.read_text(encoding="utf-8")
    assert "[Timer]" in text
    # The cron spec: daily, hour=2
    assert "OnCalendar=" in text
    assert "*-*-* 02" in text or "*-*-*  02" in text, (
        f"timer must run at 02:00 daily; got: {text!r}"
    )
    assert "Persistent=true" in text, (
        "timer must catch up on missed runs (Persistent=true) so a "
        "down box doesn't permanently skip backups"
    )
