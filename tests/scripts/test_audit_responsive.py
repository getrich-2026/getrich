"""Tests for ``scripts/audit_responsive.py``.

The audit is a static analyzer over ``frontend/src/**/*.tsx``.
We test it with synthetic .tsx fixtures written to a tmp
dir so we don't depend on the real frontend tree staying
in any particular shape.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_responsive.py"


@pytest.fixture
def fake_frontend(tmp_path: Path) -> Path:
    """Build a minimal frontend/ tree with 3 known-bad and
    1 known-good .tsx file. The script reads from
    ``frontend/src`` relative to REPO_ROOT, so we make a
    symlink (or, on Windows, a copy) of the structure.
    """
    frontend = tmp_path / "frontend" / "src"
    frontend.mkdir(parents=True)
    # Known-bad: fixed width overflow
    (frontend / "Bad1.tsx").write_text(
        """export function Bad1() {
  return <div className="w-[800px]">wide</div>;
}""",
        encoding="utf-8",
    )
    # Known-bad: 4-col grid without mobile fallback
    (frontend / "Bad2.tsx").write_text(
        """export function Bad2() {
  return <div className="grid grid-cols-4 gap-2">cards</div>;
}""",
        encoding="utf-8",
    )
    # Known-bad: h-6 button (touch target too small)
    (frontend / "Bad3.tsx").write_text(
        """export function Bad3() {
  return <button className="h-6 w-6">x</button>;
}""",
        encoding="utf-8",
    )
    # Known-good: 2-col grid (no warning)
    (frontend / "Good1.tsx").write_text(
        """export function Good1() {
  return <div className="grid grid-cols-1 sm:grid-cols-2">cards</div>;
}""",
        encoding="utf-8",
    )
    # Known-good: small fixed width (under 343 px)
    (frontend / "Good2.tsx").write_text(
        """export function Good2() {
  return <div className="w-[200px]">narrow</div>;
}""",
        encoding="utf-8",
    )
    # Known-good: responsive grid chain (mobile 1, desktop 4)
    (frontend / "Good3.tsx").write_text(
        """export function Good3() {
  return <div className="grid grid-cols-1 md:grid-cols-4">cards</div>;
}""",
        encoding="utf-8",
    )
    return tmp_path


def _run(fake_root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the audit with REPO_ROOT redirected to fake_root."""
    # The script resolves FRONTEND = REPO_ROOT / "frontend" /
    # "src" via Path(__file__).resolve().parents[1]. So we
    # symlink scripts/ into our fake root.
    fake_scripts = fake_root / "scripts"
    fake_scripts.mkdir(exist_ok=True)
    fake_script = fake_scripts / "audit_responsive.py"
    fake_script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(fake_script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(fake_root),
    )


def test_audit_finds_known_bad_patterns(fake_frontend: Path) -> None:
    """All 3 known-bad files should be flagged."""
    proc = _run(fake_frontend, "--json")
    assert proc.returncode == 0, f"unexpected non-zero: {proc.stderr}"
    issues = json.loads(proc.stdout)
    rules = {i["rule"] for i in issues}
    # Bad1: fixed-width-overflows-mobile
    assert "fixed-width-overflows-mobile" in rules
    # Bad2: grid-cols-4-without-mobile-fallback
    assert "grid-cols-4-without-mobile-fallback" in rules
    # Bad3: touch-target-too-small
    assert "touch-target-too-small" in rules


def test_audit_skips_known_good_patterns(fake_frontend: Path) -> None:
    """None of the 3 known-good files should be flagged."""
    proc = _run(fake_frontend, "--json")
    issues = json.loads(proc.stdout)
    files = {i["file"] for i in issues}
    for good in ("Good1.tsx", "Good2.tsx", "Good3.tsx"):
        assert not any(good in f for f in files), (
            f"{good} should not be flagged, but appears in {files}"
        )


def test_audit_strict_exits_nonzero_on_issues(fake_frontend: Path) -> None:
    """With --strict, a non-empty issue set makes the script
    exit 1 (so a CI gate can block on it)."""
    proc = _run(fake_frontend, "--strict")
    assert proc.returncode == 1, (
        f"expected rc=1 with --strict and known-bad fixtures, "
        f"got {proc.returncode}; stdout={proc.stdout!r}"
    )


def test_audit_default_exits_zero(fake_frontend: Path) -> None:
    """Without --strict, the script reports but exits 0.
    A reviewer-driven audit is non-blocking."""
    proc = _run(fake_frontend)
    assert proc.returncode == 0, (
        f"expected rc=0 by default (non-blocking), got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


def test_audit_human_output_includes_fix_suggestion(fake_frontend: Path) -> None:
    """The non-JSON output must include a `fix:` line so a
    reviewer knows what to change without reading the code."""
    proc = _run(fake_frontend)  # human-readable
    assert "fix:" in proc.stdout
    assert "fixed-width-overflows-mobile" in proc.stdout


def test_audit_groups_by_file(fake_frontend: Path) -> None:
    """The human report groups by file with a `== file.tsx (N)`
    header, so a reviewer can navigate it without scrolling
    through individual line numbers.
    """
    proc = _run(fake_frontend)
    # At least one `==` line per known-bad file.
    assert "== " in proc.stdout
