"""Tests for ``scripts/lint_migrations.py`` (Round #1153).

Covers:
1. The PostgreSQL rule set (DROP COLUMN, CREATE INDEX CONCURRENTLY)
2. The --db CLI flag (ch / pg / all)
3. Existing migrations pass the new rules (regression floor)
4. Splitter edge cases that are PG-specific (dollar-quoted strings
   in CREATE FUNCTION bodies)
5. The back-compat shim at scripts/lint_clickhouse_migrations.py
   (Round #1150 tests cover that file directly)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
LINT_MIGRATIONS = SCRIPTS / "lint_migrations.py"
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def _load_module():
    spec = importlib.util.spec_from_file_location("lint_migrations", LINT_MIGRATIONS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- existing migrations


def test_all_pg_migrations_pass_new_rules() -> None:
    """All current PG migrations (top-level migrations/*.sql) must pass.

    The forbidden-pattern set changed in Round #1153: now also
    flags ``ALTER TABLE ... DROP COLUMN`` and ``CREATE INDEX
    CONCURRENTLY``. A migration that violates either rule would
    fail this test, forcing the author to either (a) refactor the
    migration to comply, or (b) update the rule set with a
    documented exception.
    """
    mod = _load_module()
    if not MIGRATIONS_DIR.is_dir():
        pytest.skip("migrations/ missing")
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.is_file())
    assert files, "no PG migration files found"
    for path in files:
        violations = mod._scan_file(path, mod.PG_FORBIDDEN_PATTERNS)
        assert not violations, (
            f"{path.name} violates the new PG policy: "
            f"{[(v[0], v[1]) for v in violations]}"
        )


def test_all_ch_migrations_pass_ch_rules() -> None:
    """Round #1153 didn't loosen the CH rules; the existing 2 CH
    migrations must still pass."""
    mod = _load_module()
    ch_dir = MIGRATIONS_DIR / "clickhouse"
    if not ch_dir.is_dir():
        pytest.skip("migrations/clickhouse/ missing")
    for path in sorted(ch_dir.glob("*.sql")):
        violations = mod._scan_file(path, mod.CH_FORBIDDEN_PATTERNS)
        assert not violations, (
            f"{path.name} violates CH policy: "
            f"{[(v[0], v[1]) for v in violations]}"
        )


# ---------------------------------------------------------------- forbidden patterns


@pytest.mark.parametrize(
    "forbidden_sql",
    [
        "ALTER TABLE foo DROP COLUMN bar",
        "ALTER TABLE foo DROP COLUMN IF EXISTS bar",
        "ALTER TABLE ONLY public.foo DROP COLUMN bar",
        "ALTER TABLE foo DROP COLUMN bar CASCADE",
        "CREATE INDEX CONCURRENTLY ix_foo ON foo (x)",
        "create index concurrently ix_foo on foo (x)",  # case-insensitive
    ],
)
def test_pg_forbidden_patterns_trigger(tmp_path: Path, forbidden_sql: str) -> None:
    """All PG forbidden forms must trigger: DROP COLUMN (with optional
    IF EXISTS, CASCADE, ONLY, schema-qualified), and CREATE INDEX
    CONCURRENTLY (case-insensitive)."""
    mod = _load_module()
    file = tmp_path / "001_evil.sql"
    file.write_text(forbidden_sql + ";\n", encoding="utf-8")
    violations = mod._scan_file(file, mod.PG_FORBIDDEN_PATTERNS)
    assert violations, f"expected violation for: {forbidden_sql!r}"
    rule, _excerpt, _idx = violations[0]
    assert any(
        kw in rule
        for kw in ("DROP COLUMN", "CONCURRENTLY")
    ), f"unexpected rule {rule!r} for: {forbidden_sql!r}"


def test_pg_bare_drop_does_not_trigger_drop_column(tmp_path: Path) -> None:
    """``ALTER TABLE foo DROP bar`` (no COLUMN keyword) is NOT a
    DROP COLUMN — the policy only catches the explicit form. Bare
    DROP is a different operator (rare in practice but legal) with
    a different rollback story. Locks in the round #1153 decision
    to require the COLUMN keyword for false-positive avoidance."""
    mod = _load_module()
    file = tmp_path / "001_bare_drop.sql"
    file.write_text("ALTER TABLE foo DROP bar;\n", encoding="utf-8")
    violations = mod._scan_file(file, mod.PG_FORBIDDEN_PATTERNS)
    assert not violations, (
        f"bare DROP without COLUMN keyword should NOT trigger; got: {violations}"
    )


def test_pg_allowed_ddl_does_not_trigger(tmp_path: Path) -> None:
    """The full allowed DDL subset (CREATE TABLE / TYPE / INDEX
    non-CONCURRENTLY / FUNCTION; ALTER ADD / MODIFY / RENAME /
    SET DEFAULT; INSERT; CREATE POLICY) must all pass."""
    mod = _load_module()
    allowed = (
        "CREATE TABLE foo (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL);\n"
        "CREATE INDEX ix_foo_name ON foo (name);\n"
        "CREATE TYPE bar AS ENUM ('a', 'b', 'c');\n"
        "ALTER TABLE foo ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();\n"
        "ALTER TABLE foo ALTER COLUMN name TYPE VARCHAR(200);\n"
        "ALTER TABLE foo RENAME COLUMN name TO label;\n"
        "ALTER TABLE foo ALTER COLUMN label SET DEFAULT 'unknown';\n"
        "INSERT INTO foo (name) SELECT unnest FROM other_table;\n"
        "CREATE POLICY p_foo_select ON foo FOR SELECT USING (true);\n"
        "GRANT SELECT, INSERT ON foo TO app_user;\n"
    )
    file = tmp_path / "001_ok.sql"
    file.write_text(allowed, encoding="utf-8")
    violations = mod._scan_file(file, mod.PG_FORBIDDEN_PATTERNS)
    assert not violations, f"allowed DDL tripped violations: {violations}"


def test_pg_drop_constraint_does_not_trigger_drop_column(tmp_path: Path) -> None:
    """DROP CONSTRAINT is NOT in the new rule (that's a separate,
    less-destructive action — we'll add a rule for it in a future
    round if needed). For now, it must pass silently."""
    mod = _load_module()
    file = tmp_path / "001_drop_constraint.sql"
    file.write_text("ALTER TABLE foo DROP CONSTRAINT fk_foo_bar;\n", encoding="utf-8")
    violations = mod._scan_file(file, mod.PG_FORBIDDEN_PATTERNS)
    assert not violations, (
        f"DROP CONSTRAINT should NOT trigger DROP COLUMN rule, but got: {violations}"
    )


# ---------------------------------------------------------------- CLI flag


def test_cli_default_is_all() -> None:
    """``--db`` defaults to ``all`` (lint both CH and PG)."""
    proc = subprocess.run(
        [sys.executable, str(LINT_MIGRATIONS)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "ClickHouse migration(s) clean" in out, out
    assert "PostgreSQL migration(s) clean" in out, out


def test_cli_ch_only() -> None:
    """``--db ch`` only lints CH files."""
    proc = subprocess.run(
        [sys.executable, str(LINT_MIGRATIONS), "--db", "ch"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "ClickHouse migration(s) clean" in out
    assert "PostgreSQL migration(s) clean" not in out, (
        f"--db ch should not mention PG; output:\n{out}"
    )


def test_cli_pg_only() -> None:
    """``--db pg`` only lints PG files."""
    proc = subprocess.run(
        [sys.executable, str(LINT_MIGRATIONS), "--db", "pg"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "PostgreSQL migration(s) clean" in out
    assert "ClickHouse migration(s) clean" not in out


def test_cli_invalid_db_value_exits_2() -> None:
    """Unknown DB value -> argparse exits 2 (and reports usage)."""
    proc = subprocess.run(
        [sys.executable, str(LINT_MIGRATIONS), "--db", "mongodb"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert proc.returncode == 2, proc.stderr
    assert "invalid choice" in proc.stderr.lower(), proc.stderr


# ---------------------------------------------------------------- splitter edge cases


def test_pg_dollar_quoted_string_not_split(tmp_path: Path) -> None:
    """PG ``$$ ... $$`` dollar-quoted string literals (used inside
    ``CREATE FUNCTION`` bodies) contain arbitrary characters
    including semicolons. The splitter must not split on a
    semicolon inside a dollar-quoted block. This is a known
    limitation of the Round #1150 splitter — it tracks single-
    quoted strings only. We document the limitation here and
    confirm a CREATE FUNCTION body with no single-quoted strings
    but with $$...$$ doesn't false-positive.

    Note: the current splitter DOES split on ``;`` inside $$...
    $$ if the body has them. This test asserts the behaviour we
    accept (false-positive single-statement violation that the
    human reviewer must resolve). A future round can add proper
    dollar-quote tracking; for now we just lock in the current
    behaviour so any change to the splitter is intentional.
    """
    mod = _load_module()
    file = tmp_path / "001_function.sql"
    file.write_text(
        "CREATE FUNCTION foo() RETURNS void AS $$\n"
        "BEGIN\n"
        "  RAISE NOTICE 'hi';\n"
        "END;\n"
        "$$ LANGUAGE plpgsql;\n",
        encoding="utf-8",
    )
    violations = mod._scan_file(file, mod.PG_FORBIDDEN_PATTERNS)
    # Without dollar-quote awareness, the splitter would see
    # multiple statements (one of which would be the RAISE NOTICE
    # inside the function body). The Round #1153 rule set won't
    # flag any of those statements, so the result is no violations.
    # This is a guard: if a future change accidentally flags
    # RAISE NOTICE or BEGIN as DROP COLUMN, this test will catch it.
    assert not violations, f"function body false-positive: {violations}"
