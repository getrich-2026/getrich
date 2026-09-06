#!/usr/bin/env python
"""Reject unsafe SQL patterns in GetRich migration files.

This is a small repository guard, not a SQL validator. It removes comments and
quoted strings before checking the operations forbidden by ``CLAUDE.md``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from gr_db.docs.ddl_lint import changed_migrations, comment_violations


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "packages/gr-db/src/gr_db/ddl"

Rule = tuple[str, re.Pattern[str]]

RULES: dict[str, tuple[Rule, ...]] = {
    "ch": tuple(
        (name, re.compile(pattern, re.IGNORECASE | re.DOTALL))
        for name, pattern in (
            ("ALTER TABLE ... UPDATE", r"\bALTER\s+TABLE\b[^;]*\bUPDATE\b"),
            ("ALTER TABLE ... DELETE", r"\bALTER\s+TABLE\b[^;]*\bDELETE\b"),
            ("DELETE FROM", r"\bDELETE\s+FROM\b"),
            ("TRUNCATE TABLE", r"\bTRUNCATE(?:\s+TABLE)?\b"),
            ("OPTIMIZE ... FINAL", r"\bOPTIMIZE\b[^;]*\bFINAL\b"),
        )
    ),
    "pg": (
        (
            "ALTER TABLE ... DROP COLUMN",
            re.compile(r"\bALTER\s+TABLE\b[^;]*\bDROP\s+COLUMN\b", re.IGNORECASE | re.DOTALL),
        ),
        ("CREATE INDEX CONCURRENTLY", re.compile(r"\bCREATE\s+INDEX\s+CONCURRENTLY\b", re.I)),
    ),
}

IGNORED_SQL = re.compile(
    r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'",
    re.DOTALL,
)


def find_violations(sql: str, rules: tuple[Rule, ...]) -> list[str]:
    """Return forbidden operation names, ignoring SQL comments and literals."""
    executable_sql = IGNORED_SQL.sub(" ", sql)
    return [name for name, pattern in rules if pattern.search(executable_sql)]


def lint_files(paths: list[Path], rules: tuple[Rule, ...]) -> int:
    """Print violations and return their total count."""
    total = 0
    for path in paths:
        violations = find_violations(path.read_text(encoding="utf-8"), rules)
        for violation in violations:
            print(f"FAIL  {path.relative_to(REPO_ROOT)}: {violation}")
        total += len(violations)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", choices=("ch", "pg", "all"), default="all")
    parser.add_argument(
        "--comments",
        action="store_true",
        help="检查相对 base ref 新增或修改的 PG 建表迁移是否补齐注释。",
    )
    parser.add_argument(
        "--base-ref",
        default="origin/dev",
        help="注释检查的 git diff 基线（默认 origin/dev）。",
    )
    args = parser.parse_args(argv)

    selected = ("ch", "pg") if args.db == "all" else (args.db,)
    paths = {
        "ch": sorted((MIGRATIONS_DIR / "clickhouse").glob("*.sql")),
        "pg": sorted((MIGRATIONS_DIR / "postgres").glob("*.sql")),
    }
    total = 0
    for database in selected:
        files = paths[database]
        if not files:
            print(f"WARN  no {database} migrations found")
            continue
        violations = lint_files(files, RULES[database])
        total += violations
        if violations == 0:
            print(f"OK    {len(files)} {database} migration(s)")
    if args.comments:
        changed, warning = changed_migrations(REPO_ROOT, MIGRATIONS_DIR / "postgres", args.base_ref)
        if warning:
            print(f"WARN  {warning}")
        else:
            comments = comment_violations(changed, MIGRATIONS_DIR / "postgres")
            for violation in comments:
                print(f"FAIL  {violation}")
            total += len(comments)
            if not comments:
                print(f"OK    {len(changed)} changed PostgreSQL migration(s) have comments")
    return int(total > 0)


if __name__ == "__main__":
    sys.exit(main())
