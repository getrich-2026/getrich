#!/usr/bin/env python
"""ClickHouse migration topology linter.

Enforces the GetRich 3-DB topology铁律 (CLAUDE.md §2) at the
migration-file level. Without this guard, a future PR could
sneak a row-level UPDATE/DELETE into ``migrations/clickhouse/*.sql``
and we wouldn't catch it until a production outage (CH's
``ALTER ... UPDATE`` is implemented as a partition rewrite
that nukes performance for hot-path data).

What is allowed in a CH migration (the MergeTree-friendly subset):
  - CREATE TABLE / VIEW / MATERIALIZED VIEW / DICTIONARY
  - ALTER TABLE ... ADD COLUMN / MODIFY COLUMN / DROP COLUMN
  - INSERT INTO ... SELECT   (one-shot backfill; documented)
  - GRANT / REVOKE (multi-tenant auth)

What is forbidden (causes the linter to exit 1):
  - ALTER TABLE ... UPDATE
  - ALTER TABLE ... DELETE
  - DELETE FROM
  - TRUNCATE TABLE           (use DROP PARTITION when you really need to)
  - OPTIMIZE FINAL           (forces a partition merge; almost never
                              the right tool for an on-line correction)

Usage::

    uv run python scripts/lint_clickhouse_migrations.py
    # exits 0 on clean, 1 on violation

Tests in ``tests/scripts/test_lint_clickhouse_migrations.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CH_DIR = REPO_ROOT / "migrations" / "clickhouse"

# Forbidden patterns. Order matters: we report the *first* match in
# each statement, scanning the patterns top-to-bottom so the most
# specific rule wins.
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
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


def _split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, respecting string literals and comments.

    We don't need full SQL parsing — just enough to scan each
    statement independently. A statement is everything between two
    semicolons that are outside a single-quoted string and outside
    a line comment.
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


def _scan_file(path: Path) -> list[tuple[str, str, int]]:
    """Return list of (rule, statement_excerpt, statement_index) violations."""
    text = path.read_text(encoding="utf-8")
    statements = _split_statements(text)
    violations: list[tuple[str, str, int]] = []
    for idx, stmt in enumerate(statements, start=1):
        # Skip comment-only statements (sql_files can have just `-- header` lines)
        non_comment = re.sub(r"--[^\n]*", "", stmt).strip()
        if not non_comment:
            continue
        for rule_name, pattern in FORBIDDEN_PATTERNS:
            m = pattern.search(non_comment)
            if m:
                excerpt = non_comment[max(0, m.start() - 20) : m.end() + 20].strip()
                violations.append((rule_name, excerpt, idx))
                break  # one violation per statement
    return violations


def main() -> int:
    if not CH_DIR.is_dir():
        print(f"ERROR: {CH_DIR.relative_to(REPO_ROOT)} does not exist", file=sys.stderr)
        return 2

    files = sorted(CH_DIR.glob("*.sql"))
    if not files:
        print(f"WARN: {CH_DIR.relative_to(REPO_ROOT)} is empty; nothing to lint")
        return 0

    total_violations = 0
    for path in files:
        violations = _scan_file(path)
        rel = path.relative_to(REPO_ROOT)
        if violations:
            total_violations += len(violations)
            print(f"FAIL  {rel}  ({len(violations)} violation(s))")
            for rule, excerpt, idx in violations:
                print(f"      stmt #{idx}: rule={rule!r}")
                print(f"      match: ...{excerpt}...")

    if total_violations == 0:
        print(f"OK    {len(files)} ClickHouse migration(s) clean")
        print("      forbidden patterns checked: " + ", ".join(r for r, _ in FORBIDDEN_PATTERNS))
        return 0
    print(f"\nFAIL  {total_violations} violation(s) across {len(files)} file(s)")
    print("      See docs/operations/database-topology.md §2 for the policy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
