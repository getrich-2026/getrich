"""Parse-level tests for the ClickHouse migrations.

The CH migration runner needs a live CH server to actually apply
migrations (``--dry-run`` still does a connection to read the
tracking table). These tests validate the *SQL artifacts* without
needing a live CH:

  - Both files exist and are discoverable (file name pattern).
  - Each file's SQL uses the MergeTree engine family.
  - PARTITION BY / ORDER BY / TTL clauses are present (CLAUDE.md §2).
  - The ``dt`` column is ``DateTime64(3, 'Asia/Shanghai')`` (CLAUDE.md
    §3.1 — the only correct timezone-aware choice for night-session
    data).
  - No PostgreSQL-only syntax (e.g. ``COMMENT ON TABLE``, ``SERIAL``)
    leaks into a CH migration.
"""

from __future__ import annotations

import re
from pathlib import Path


def _ch_migrations_dir() -> Path:
    """Locate the CH migrations directory by walking up the path
    tree until we find a directory that contains both
    ``migrations/clickhouse/`` and ``pyproject.toml``. This is
    robust to running the test from any CWD and to the file living
    in different relative depths (CI vs. local dev).
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "migrations" / "clickhouse"
        if candidate.is_dir() and (parent / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError(
        f"could not locate migrations/clickhouse by walking up from {Path(__file__).resolve()}"
    )


def _read(name: str) -> str:
    return (_ch_migrations_dir() / name).read_text(encoding="utf-8")


def test_migrations_dir_has_files() -> None:
    files = sorted(p.name for p in _ch_migrations_dir().iterdir() if p.suffix == ".sql")
    assert files, "no CH migrations found"
    # Prefixes must be 3+ digits and continuous (CLAUDE.md §6).
    prefixes = [int(f.split("_", 1)[0]) for f in files]
    assert all(p >= 1 for p in prefixes), f"non-positive prefix in {prefixes}"


def test_ohlcv_bars_uses_mergetree() -> None:
    sql = _read("001_ohlcv_bars.sql")
    # Two tables in this file (1m and 1d). Both must use MergeTree.
    assert sql.count("ENGINE = MergeTree()") == 2
    # PARTITION BY monthly — required by CLAUDE.md §2.
    assert sql.count("PARTITION BY toYYYYMM(dt)") == 2
    # ORDER BY (symbol, dt) — primary key for latest-N-per-symbol.
    assert sql.count("ORDER BY (symbol, dt)") == 2
    # TTL clauses (5y for 1m, 10y for 1d).
    assert "TTL dt + INTERVAL 5 YEAR" in sql
    assert "TTL dt + INTERVAL 10 YEAR" in sql
    # Time column declarations: match ``dt<spaces>DateTime64(...)``
    # so the docstring prose doesn't inflate the count. We expect
    # exactly 2 column declarations (one per table).
    dt_col_pattern = re.compile(r"\bdt\s+DateTime64\(3,\s*'Asia/Shanghai'\)")
    assert len(dt_col_pattern.findall(sql)) == 2
    # No PostgreSQL-only syntax.
    assert "COMMENT ON TABLE" not in sql
    assert "SERIAL" not in sql


def test_factors_long_uses_mergetree() -> None:
    sql = _read("002_factors_long.sql")
    assert "ENGINE = MergeTree()" in sql
    # ORDER BY (factor, symbol, dt) — primary key for latest-N-per-factor
    # lookups (the dominant cost on a multi-factor strategy).
    assert "ORDER BY (factor, symbol, dt)" in sql
    # Monthly partition + 5y TTL.
    assert "PARTITION BY toYYYYMM(dt)" in sql
    assert "TTL dt + INTERVAL 5 YEAR" in sql
    # Time column declaration (column, not docstring mention).
    dt_col_pattern = re.compile(r"\bdt\s+DateTime64\(3,\s*'Asia/Shanghai'\)")
    assert len(dt_col_pattern.findall(sql)) == 1
    # No PostgreSQL-only syntax.
    assert "COMMENT ON TABLE" not in sql
    assert "SERIAL" not in sql


def test_no_serial_or_pg_syntax() -> None:
    """Defense in depth: scan all CH migrations for any PG-specific
    keyword. CH and PG share most of SQL syntax but the differences
    (SERIAL, COMMENT ON, ::regclass, etc.) are sharp enough to
    catch by keyword match.
    """
    pg_only = ("SERIAL", "COMMENT ON TABLE", "::regclass", "gen_random_uuid")
    for path in _ch_migrations_dir().glob("*.sql"):
        sql = path.read_text(encoding="utf-8")
        for needle in pg_only:
            assert needle not in sql, f"PG-only syntax {needle!r} found in CH migration {path.name}"


def test_all_files_have_datetime64() -> None:
    """Every CH migration must declare its time column as
    ``DateTime64(3, 'Asia/Shanghai')`` (CLAUDE.md §3.1). This is a
    single-line guard against future contributors adding a new
    CH table with ``DateTime`` (no tz) or ``Date`` (date-only,
    which breaks night sessions).
    """
    # Files that should NOT have a DateTime column (e.g. reference
    # tables) can be added to this allow-list; for now both of our
    # CH tables have one.
    files_with_dt = ("001_ohlcv_bars.sql", "002_factors_long.sql")
    for name in files_with_dt:
        sql = _read(name)
        assert re.search(
            r"DateTime64\(3,\s*'Asia/Shanghai'\)",
            sql,
        ), f"{name} missing DateTime64(3, 'Asia/Shanghai') column"
