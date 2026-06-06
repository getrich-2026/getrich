#!/usr/bin/env python
"""Multi-DB migration topology linter (CH + PostgreSQL).

Enforces the GetRich 3-DB topology铁律 (CLAUDE.md §2) at the
migration-file level. Without this guard, a future PR could
sneak destructive or unsafe DDL into the migrations and we
wouldn't catch it until a production outage.

Two rule sets, one splitter:

  CH (MergeTree-friendly)
  -----------------------
  Forbidden:
    - ALTER TABLE ... UPDATE         (partition rewrite perf bomb)
    - ALTER TABLE ... DELETE         (row-level delete in CH is also rewrite)
    - DELETE FROM                    (not supported by MergeTree)
    - TRUNCATE TABLE / TRUNCATE      (use DROP PARTITION when needed)
    - OPTIMIZE ... FINAL             (forces partition merge; rarely the right tool)
  Allowed:
    - CREATE TABLE / VIEW / MATERIALIZED VIEW / DICTIONARY
    - ALTER TABLE ... ADD / MODIFY / DROP COLUMN
    - INSERT INTO ... SELECT   (one-shot backfill; documented)
    - GRANT / REVOKE (multi-tenant auth)

  PG (transactional / migration-runner safe)
  -----------------------------------------
  Forbidden:
    - ALTER TABLE ... DROP COLUMN     (destructive; needs explicit review
                                       + a separate migration to be safe
                                       to roll back). ADD/MODIFY COLUMN
                                       with DEFAULT is fine.
    - CREATE INDEX CONCURRENTLY       (CONCURRENTLY cannot run inside a
                                       transaction block. The GetRich
                                       migration runner wraps each file
                                       in BEGIN/COMMIT, so a CONCURRENTLY
                                       migration would fail mid-flight
                                       and leave the DB in an undefined
                                       state. Use a manual migration
                                       that runs psql --single-transaction=off
                                       outside the runner, or build the
                                       index in a non-CONCURRENTLY migration
                                       that takes a brief ACCESS EXCLUSIVE
                                       lock).
  Allowed:
    - CREATE TABLE / TYPE / INDEX (non-CONCURRENTLY) / VIEW / FUNCTION
    - ALTER TABLE ... ADD COLUMN / MODIFY COLUMN / RENAME / SET DEFAULT
    - INSERT / UPDATE (one-shot backfill; for migrations that need
      data movement, document the lock impact in the migration
      header comment)
    - GRANT / REVOKE / CREATE POLICY
    - SELECT (for sanity-check queries that the runner ignores)

The shared SQL splitter is the same one used in Round #1150:
it respects ``--`` line comments, ``/* */`` block comments, and
``'...'`` single-quoted string literals (so a semicolon inside
a string literal doesn't accidentally split a statement).

Usage::

    uv run python scripts/lint_migrations.py                # all DBs
    uv run python scripts/lint_migrations.py --db ch        # ClickHouse only
    uv run python scripts/lint_migrations.py --db pg        # PostgreSQL only

Exit codes: 0 = clean, 1 = violation(s), 2 = missing dir / bad arg.

Tests in ``tests/scripts/test_lint_migrations.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
CH_DIR = MIGRATIONS_DIR / "clickhouse"
# PG migrations are top-level .sql files in migrations/ (the CH
# subdir is excluded by the glob pattern).
PG_GLOB = "*.sql"

# ---------------------------------------------------------------- rule sets

# ClickHouse: 5 forbidden patterns. Order matters — we report the
# first match per statement, so more-specific rules (e.g. ALTER
# TABLE ... UPDATE) come before generic ones (e.g. DELETE FROM).
CH_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ALTER TABLE ... UPDATE",
        re.compile(r"\bALTER\s+TABLE\s+[^;]*\bUPDATE\b", re.IGNORECASE | re.DOTALL),
    ),
    (
        "ALTER TABLE ... DELETE",
        re.compile(r"\bALTER\s+TABLE\s+[^;]*\bDELETE\b", re.IGNORECASE | re.DOTALL),
    ),
    (
        "DELETE FROM",
        re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    ),
    (
        "TRUNCATE TABLE",
        re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?\S+", re.IGNORECASE),
    ),
    (
        "OPTIMIZE FINAL",
        re.compile(r"\bOPTIMIZE\s+[^;]*\bFINAL\b", re.IGNORECASE | re.DOTALL),
    ),
)

# PostgreSQL: 2 forbidden patterns. See module docstring for rationale.
PG_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ALTER TABLE ... DROP COLUMN",
        # Match ``ALTER TABLE ... DROP COLUMN name``. We deliberately
        # require the COLUMN keyword so that DROP CONSTRAINT /
        # DROP INDEX (which have a different rollback story) pass.
        # Case-insensitive. The pattern tolerates ``ALTER TABLE ONLY``
        # (PG's row-scope modifier) and the optional IF EXISTS.
        re.compile(
            r"\bALTER\s+TABLE\s+(?:ONLY\s+)?\w+(?:\.\w+)?\s+"
            r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?\w+",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "CREATE INDEX CONCURRENTLY",
        # CONCURRENTLY cannot run inside a transaction. We require
        # such migrations to be run manually outside the runner.
        re.compile(r"\bCREATE\s+INDEX\s+CONCURRENTLY\b", re.IGNORECASE),
    ),
)


# ---------------------------------------------------------------- splitter


def _split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, respecting string literals and comments.

    We don't need full SQL parsing — just enough to scan each
    statement independently. A statement is everything between two
    semicolons that are outside a single-quoted string and outside
    a line / block comment.
    """
    out: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql_text)
    while i < n:
        ch = sql_text[i]
        # Line comment to end-of-line
        if ch == "-" and i + 1 < n and sql_text[i + 1] == "-":
            j = sql_text.find("\n", i)
            if j == -1:
                j = n
            buf.append(sql_text[i:j])
            i = j
            continue
        # Block comment
        if ch == "/" and i + 1 < n and sql_text[i + 1] == "*":
            j = sql_text.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            buf.append(sql_text[i:j])
            i = j
            continue
        # Single-quoted string literal
        if ch == "'":
            j = i + 1
            while j < n:
                if sql_text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql_text[j] == "'":
                    j += 1
                    break
                j += 1
            buf.append(sql_text[i:j])
            i = j
            continue
        # Statement separator
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _scan_file(
    path: Path, patterns: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, str, int]]:
    """Return list of (rule, statement_excerpt, statement_index) violations."""
    text = path.read_text(encoding="utf-8")
    statements = _split_statements(text)
    violations: list[tuple[str, str, int]] = []
    for idx, stmt in enumerate(statements, start=1):
        # Skip comment-only statements (sql_files can have just `-- header` lines)
        non_comment = re.sub(r"--[^\n]*", "", stmt).strip()
        if not non_comment:
            continue
        for rule_name, pattern in patterns:
            m = pattern.search(non_comment)
            if m:
                excerpt = non_comment[max(0, m.start() - 20) : m.end() + 20].strip()
                violations.append((rule_name, excerpt, idx))
                break  # one violation per statement
    return violations


# ---------------------------------------------------------------- DB-specific runners


def _lint_clickhouse() -> tuple[int, int, list[str]]:
    """Lint ``migrations/clickhouse/*.sql``. Returns (violations, file_count, files_linted)."""
    if not CH_DIR.is_dir():
        return 0, 0, []
    files = sorted(CH_DIR.glob("*.sql"))
    total = 0
    for path in files:
        violations = _scan_file(path, CH_FORBIDDEN_PATTERNS)
        if violations:
            total += len(violations)
            rel = path.relative_to(REPO_ROOT)
            print(f"FAIL  {rel}  ({len(violations)} violation(s))")
            for rule, excerpt, idx in violations:
                print(f"      stmt #{idx}: rule={rule!r}")
                print(f"      match: ...{excerpt}...")
    return total, len(files), [p.name for p in files]


def _lint_postgres() -> tuple[int, int, list[str]]:
    """Lint top-level ``migrations/*.sql`` (excludes the CH subdir).

    Returns (violations, file_count, files_linted).
    """
    if not MIGRATIONS_DIR.is_dir():
        return 0, 0, []
    files = sorted(p for p in MIGRATIONS_DIR.glob(PG_GLOB) if p.is_file())
    total = 0
    for path in files:
        violations = _scan_file(path, PG_FORBIDDEN_PATTERNS)
        if violations:
            total += len(violations)
            rel = path.relative_to(REPO_ROOT)
            print(f"FAIL  {rel}  ({len(violations)} violation(s))")
            for rule, excerpt, idx in violations:
                print(f"      stmt #{idx}: rule={rule!r}")
                print(f"      match: ...{excerpt}...")
    return total, len(files), [p.name for p in files]


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint GetRich DB migrations against topology policy.",
    )
    parser.add_argument(
        "--db",
        choices=("ch", "pg", "all"),
        default="all",
        help="Which DB's migrations to scan (default: all)",
    )
    args = parser.parse_args(argv)

    grand_total = 0
    ran_any = False

    if args.db in ("ch", "all"):
        ran_any = True
        ch_total, ch_n, _ch_files = _lint_clickhouse()
        if ch_n == 0 and not CH_DIR.is_dir():
            print(
                f"WARN: {CH_DIR.relative_to(REPO_ROOT)} does not exist; skipping CH"
            )
        elif ch_n == 0:
            print(
                f"WARN: {CH_DIR.relative_to(REPO_ROOT)} is empty; nothing to lint for CH"
            )
        else:
            grand_total += ch_total
            if ch_total == 0:
                print(
                    f"OK    {ch_n} ClickHouse migration(s) clean; "
                    f"checked: {', '.join(r for r, _ in CH_FORBIDDEN_PATTERNS)}"
                )

    if args.db in ("pg", "all"):
        ran_any = True
        pg_total, pg_n, _pg_files = _lint_postgres()
        if pg_n == 0:
            print(
                f"WARN: {MIGRATIONS_DIR.relative_to(REPO_ROOT)} has no top-level .sql; "
                f"skipping PG"
            )
        else:
            grand_total += pg_total
            if pg_total == 0:
                print(
                    f"OK    {pg_n} PostgreSQL migration(s) clean; "
                    f"checked: {', '.join(r for r, _ in PG_FORBIDDEN_PATTERNS)}"
                )

    if not ran_any:
        parser.error("no DB selected")

    if grand_total == 0:
        return 0
    print(
        f"\nFAIL  {grand_total} total violation(s). "
        f"See docs/operations/database-topology.md §2 for the policy."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
