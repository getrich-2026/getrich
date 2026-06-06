"""Tests for ``scripts/lint_clickhouse_migrations.py``.

Covers three classes of behaviour:
1. Existing migrations in the repo (must stay clean forever)
2. Forbidden patterns (UPDATE / DELETE / TRUNCATE / OPTIMIZE FINAL)
3. Edge cases in the SQL splitter (comments, strings, multi-statement files)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lint_clickhouse_migrations.py"
CH_DIR = REPO_ROOT / "migrations" / "clickhouse"


def _load_module():
    """Import the linter script as a module so we can call its helpers directly."""
    spec = importlib.util.spec_from_file_location("lint_ch", SCRIPT)
    assert spec and spec.loader, f"could not load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- existing migrations


def test_existing_migrations_are_clean() -> None:
    """All migrations/clickhouse/*.sql must pass the linter as-is."""
    mod = _load_module()
    for path in sorted(CH_DIR.glob("*.sql")):
        violations = mod._scan_file(path)
        assert not violations, (
            f"{path.relative_to(REPO_ROOT)} contains forbidden patterns: "
            f"{[(v[0], v[1]) for v in violations]}"
        )


def test_linter_cli_exits_zero_on_clean_repo() -> None:
    """Running the linter against the real CH dir must exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, (
        f"linter failed on a clean repo:\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
    assert "OK" in proc.stdout, proc.stdout


# ---------------------------------------------------------------- splitter edge cases


def test_split_statements_skips_line_comments() -> None:
    mod = _load_module()
    sql = (
        "-- this is a comment\n"
        "CREATE TABLE x (a Int32) ENGINE = MergeTree ORDER BY a;\n"
    )
    stmts = mod._split_statements(sql)
    assert len(stmts) == 1
    assert "CREATE TABLE" in stmts[0]


def test_split_statements_skips_block_comments() -> None:
    mod = _load_module()
    sql = "/* a multi\nline\ncomment */ CREATE TABLE x (a Int32) ENGINE = MergeTree ORDER BY a;"
    stmts = mod._split_statements(sql)
    assert len(stmts) == 1
    assert "CREATE TABLE" in stmts[0]


def test_split_statements_respects_string_literals() -> None:
    mod = _load_module()
    # The semicolon inside the string literal must not split the statement
    sql = "INSERT INTO x VALUES ('a;b;c'), ('d');"
    stmts = mod._split_statements(sql)
    assert len(stmts) == 1
    assert "INSERT INTO x" in stmts[0]


def test_split_statements_handles_trailing_semicolon() -> None:
    mod = _load_module()
    sql = "SELECT 1; SELECT 2;"
    stmts = mod._split_statements(sql)
    assert len(stmts) == 2


# ---------------------------------------------------------------- forbidden patterns


@pytest.mark.parametrize(
    "forbidden_sql",
    [
        "ALTER TABLE md_bars_1m UPDATE close = 0 WHERE 1",
        "ALTER TABLE md_bars_1m DELETE WHERE symbol = 'X'",
        "DELETE FROM md_bars_1m WHERE 1",
        "TRUNCATE TABLE md_bars_1m",
        "TRUNCATE md_bars_1m",
        "OPTIMIZE TABLE md_bars_1m FINAL",
    ],
)
def test_forbidden_patterns_trigger_violations(tmp_path: Path, forbidden_sql: str) -> None:
    mod = _load_module()
    file = tmp_path / "003_evil.sql"
    file.write_text(forbidden_sql + ";\n", encoding="utf-8")
    violations = mod._scan_file(file)
    assert violations, f"expected violation for: {forbidden_sql!r}"
    rule, excerpt, _idx = violations[0]
    # Rule names from FORBIDDEN_PATTERNS (top to bottom priority)
    assert any(
        keyword in rule
        for keyword in ("UPDATE", "DELETE", "TRUNCATE", "OPTIMIZE")
    ), f"unexpected rule {rule!r} for: {forbidden_sql!r}"


def test_allowed_ddl_does_not_trigger() -> None:
    mod = _load_module()
    # Construct a CH migration that uses the allowed DDL subset
    allowed = (
        "CREATE TABLE IF NOT EXISTS md_bars_1m ("
        "  symbol LowCardinality(String),"
        "  dt      DateTime64(3, 'Asia/Shanghai'),"
        "  open    Float64"
        ") ENGINE = MergeTree()"
        "  PARTITION BY toYYYYMM(dt)"
        "  ORDER BY (symbol, dt)"
        "  TTL dt + INTERVAL 5 YEAR;\n"
        "CREATE MATERIALIZED VIEW mv_bars_1d ENGINE = MergeTree()"
        "  ORDER BY (symbol, dt)"
        "  POPULATE AS SELECT symbol, toDate(dt) AS dt, close FROM md_bars_1m;\n"
        "ALTER TABLE md_bars_1m ADD COLUMN IF NOT EXISTS vwap Float64 DEFAULT 0;\n"
        "INSERT INTO md_bars_1m (symbol, dt, open) SELECT 'X', now(), 1.0;\n"
    )
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as fh:
        fh.write(allowed)
        path = Path(fh.name)
    try:
        violations = mod._scan_file(path)
        assert not violations, f"allowed DDL tripped violations: {violations}"
    finally:
        path.unlink()


def test_update_in_string_literal_does_not_trigger(tmp_path: Path) -> None:
    """The string 'UPDATE this field' inside a comment or literal must not trigger.

    The splitter strips -- and /* */ comments before regex matching,
    and skips single-quoted strings. A bogus SQL file that only
    contains a string with the word 'UPDATE' should be clean.
    """
    mod = _load_module()
    file = tmp_path / "004_string.sql"
    file.write_text(
        "INSERT INTO x (label) VALUES ('please UPDATE this later');\n",
        encoding="utf-8",
    )
    violations = mod._scan_file(file)
    assert not violations, f"string literal triggered false positive: {violations}"


def test_comment_with_update_does_not_trigger(tmp_path: Path) -> None:
    mod = _load_module()
    file = tmp_path / "005_comment.sql"
    file.write_text(
        "-- TODO: don't UPDATE in CH\n"
        "CREATE TABLE x (a Int32) ENGINE = MergeTree ORDER BY a;\n",
        encoding="utf-8",
    )
    violations = mod._scan_file(file)
    assert not violations, f"comment triggered false positive: {violations}"
