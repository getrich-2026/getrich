"""Unit tests for the pure-Python migration runner.

The runner itself is DB-agnostic: it discovers files, builds a plan,
and drives a :class:`MigrationExecutor` protocol. We exercise it with
an in-memory fake executor so no PostgreSQL or ClickHouse is needed.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from getrich.migrations.runner import (
    Migration,
    MigrationError,
    MigrationExecutor,
    MigrationPlan,
    apply_migrations,
    build_plan,
    discover_migrations,
    run_directory,
)


# ---------------------------------------------------------------- fakes


class _FakeExecutor(MigrationExecutor):
    """Records every method call and lets tests inject applied prefixes."""

    def __init__(
        self,
        applied: set[str] | None = None,
        raise_on_apply: Exception | None = None,
    ) -> None:
        self.ensure_calls = 0
        self.fetch_calls = 0
        self.apply_calls: list[Migration] = []
        self._applied: set[str] = set(applied or [])
        self._raise = raise_on_apply

    async def ensure_tracking_table(self) -> None:
        self.ensure_calls += 1

    async def fetch_applied(self) -> set[str]:
        self.fetch_calls += 1
        return set(self._applied)

    async def apply_one(self, migration: Migration) -> None:
        self.apply_calls.append(migration)
        if self._raise is not None:
            raise self._raise
        self._applied.add(migration.prefix)


def _write_migration(directory: Path, prefix: str, name: str = "init") -> Path:
    path = directory / f"{prefix}_{name}.sql"
    path.write_text(
        f"-- Migration {prefix}\nCREATE TABLE t_{prefix} (id INT);\n",
        encoding="utf-8",
    )
    return path


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def tmp_migrations_dir() -> Iterator[Path]:
    d = Path(tempfile.mkdtemp(prefix="getrich_mig_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- discover_migrations


def test_discover_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    """A non-existent directory is treated as an empty migration set."""
    missing = tmp_path / "no_such_dir"
    assert discover_migrations(missing) == []


def test_discover_returns_empty_for_empty_directory(tmp_path: Path) -> None:
    assert discover_migrations(tmp_path) == []


def test_discover_finds_single_migration(tmp_migrations_dir: Path) -> None:
    _write_migration(tmp_migrations_dir, "001", "init")
    found = discover_migrations(tmp_migrations_dir)
    assert [m.prefix for m in found] == ["001"]
    assert found[0].name == "001_init.sql"
    assert "CREATE TABLE t_001" in found[0].sql


def test_discover_sorts_by_numeric_prefix(tmp_migrations_dir: Path) -> None:
    """Migrations are applied in numeric-prefix order.

    With 3+ digit fixed-width prefixes, lexicographic and numeric
    ordering coincide, so we can't easily test the distinction here
    (the contiguity check would force us to also create 003-009 to
    insert 010). The ordering is verified by the prefix round-trip
    (it comes from ``sorted(int(p) for p in found)``).
    """
    _write_migration(tmp_migrations_dir, "001", "a")
    _write_migration(tmp_migrations_dir, "002", "b")
    _write_migration(tmp_migrations_dir, "003", "c")
    found = discover_migrations(tmp_migrations_dir)
    assert [m.prefix for m in found] == ["001", "002", "003"]
    # And the prefixes round-trip as integers in the same order.
    assert [int(m.prefix) for m in found] == [1, 2, 3]


def test_discover_ignores_non_matching_files(tmp_migrations_dir: Path) -> None:
    """README.md, seed.sql, dotfiles, etc. are silently skipped."""
    _write_migration(tmp_migrations_dir, "001", "init")
    (tmp_migrations_dir / "README.md").write_text("hello", encoding="utf-8")
    (tmp_migrations_dir / "seed.sql").write_text("noop", encoding="utf-8")
    (tmp_migrations_dir / ".hidden").write_text("noop", encoding="utf-8")
    found = discover_migrations(tmp_migrations_dir)
    assert [m.prefix for m in found] == ["001"]


def test_discover_rejects_duplicate_prefixes(tmp_migrations_dir: Path) -> None:
    _write_migration(tmp_migrations_dir, "001", "first")
    _write_migration(tmp_migrations_dir, "001", "second")
    with pytest.raises(MigrationError, match="duplicate migration prefix"):
        discover_migrations(tmp_migrations_dir)


def test_discover_rejects_non_contiguous_prefixes(tmp_migrations_dir: Path) -> None:
    """A gap (e.g. 003 to 005 missing 004) is a hard error."""
    _write_migration(tmp_migrations_dir, "001", "first")
    _write_migration(tmp_migrations_dir, "003", "third")
    with pytest.raises(MigrationError, match="non-contiguous"):
        discover_migrations(tmp_migrations_dir)


def test_discover_rejects_directory_path(tmp_path: Path) -> None:
    """If the path exists but is a file, raise clearly."""
    f = tmp_path / "not_a_dir"
    f.write_text("oops", encoding="utf-8")
    with pytest.raises(MigrationError, match="not a directory"):
        discover_migrations(f)


# ---------------------------------------------------------------- build_plan


def test_build_plan_returns_empty_when_all_applied() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--"),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="--"),
    ]
    plan = build_plan(discovered, applied={"001", "002"})
    assert plan.is_empty


def test_build_plan_returns_only_pending() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--"),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="--"),
        Migration(prefix="003", name="003_c.sql", path=Path("/x"), sql="--"),
    ]
    plan = build_plan(discovered, applied={"001"})
    assert [m.prefix for m in plan] == ["002", "003"]


def test_build_plan_ignores_unknown_applied() -> None:
    """An applied prefix with no corresponding file is logged but ignored."""
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--"),
    ]
    plan = build_plan(discovered, applied={"001", "999_retired"})
    # 999 was applied previously but the file no longer exists — fine.
    assert [m.prefix for m in plan] == []


# ---------------------------------------------------------------- apply_migrations


def test_apply_runs_each_migration_in_order() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="A"),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="B"),
    ]
    plan = MigrationPlan(migrations=tuple(discovered))
    executor = _FakeExecutor()

    _run(apply_migrations(plan, executor))

    assert [m.prefix for m in executor.apply_calls] == ["001", "002"]


def test_apply_dry_run_does_not_call_executor() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="A"),
    ]
    plan = MigrationPlan(migrations=tuple(discovered))
    executor = _FakeExecutor()

    _run(apply_migrations(plan, executor, dry_run=True))

    assert executor.apply_calls == []


def test_apply_wraps_executor_exception(tmp_migrations_dir: Path) -> None:
    """If the executor raises, the runner wraps it in MigrationError."""
    _write_migration(tmp_migrations_dir, "001", "boom")
    discovered = discover_migrations(tmp_migrations_dir)
    plan = MigrationPlan(migrations=tuple(discovered))
    executor = _FakeExecutor(raise_on_apply=RuntimeError("DB blew up"))

    with pytest.raises(MigrationError, match="failed to apply"):
        _run(apply_migrations(plan, executor))


# ---------------------------------------------------------------- run_directory (end-to-end)


def test_run_directory_applies_pending_migrations(
    tmp_migrations_dir: Path,
) -> None:
    _write_migration(tmp_migrations_dir, "001", "a")
    _write_migration(tmp_migrations_dir, "002", "b")
    _write_migration(tmp_migrations_dir, "003", "c")
    executor = _FakeExecutor(applied={"001"})

    plan = _run(run_directory(tmp_migrations_dir, executor))

    assert [m.prefix for m in plan] == ["002", "003"]
    assert executor.ensure_calls == 1
    assert executor.fetch_calls == 1
    assert [m.prefix for m in executor.apply_calls] == ["002", "003"]


def test_run_directory_is_idempotent(tmp_migrations_dir: Path) -> None:
    """Re-running with everything applied is a no-op (no executor calls)."""
    _write_migration(tmp_migrations_dir, "001", "a")
    _write_migration(tmp_migrations_dir, "002", "b")
    executor = _FakeExecutor(applied={"001", "002"})

    plan = _run(run_directory(tmp_migrations_dir, executor))

    assert plan.is_empty
    assert executor.apply_calls == []


def test_run_directory_empty_directory(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    plan = _run(run_directory(tmp_path, executor))
    assert plan.is_empty
    # Empty directory never touches the executor (no tracking table).
    assert executor.ensure_calls == 0
    assert executor.fetch_calls == 0


# ---------------------------------------------------------------- #1143 ClickHouse migration verification
#
# Round #1143: verify the real ``migrations/clickhouse/`` directory
# (a) is discoverable, (b) contains valid MergeTree DDL, (c) uses
# ``IF NOT EXISTS`` for idempotency. The runner contract is exercised
# end-to-end against a fake executor so we don't need a live CH.


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CH_MIGRATIONS_DIR = _PROJECT_ROOT / "migrations" / "clickhouse"


def _read_ch_migration(name: str) -> str:
    """Read a real CH migration file from the repo."""
    path = _CH_MIGRATIONS_DIR / name
    assert path.exists(), f"CH migration file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_ch_migrations_dir_exists_and_has_files() -> None:
    """The committed ``migrations/clickhouse/`` directory contains
    the expected migrations."""
    assert _CH_MIGRATIONS_DIR.exists(), (
        f"CH migrations directory missing: {_CH_MIGRATIONS_DIR}"
    )
    files = sorted(_CH_MIGRATIONS_DIR.glob("*.sql"))
    assert len(files) >= 2, f"expected >= 2 CH migrations, found {len(files)}"
    prefixes = [f.stem.split("_", 1)[0] for f in files]
    # First two should be 001 and 002 (contiguous, no gaps).
    assert prefixes[:2] == ["001", "002"], f"unexpected prefix sequence: {prefixes}"


def test_ch_migrations_discoverable_via_runner() -> None:
    """The runner's ``discover_migrations`` finds the real CH
    files in the right order. Uses a fresh ``_FakeExecutor`` so
    no real CH client is needed."""
    if not _CH_MIGRATIONS_DIR.exists():
        pytest.skip(f"CH migrations dir not present: {_CH_MIGRATIONS_DIR}")
    found = discover_migrations(_CH_MIGRATIONS_DIR)
    assert len(found) >= 2
    # Migrations are sorted by numeric prefix.
    prefixes = [m.prefix for m in found]
    assert prefixes == sorted(prefixes, key=lambda p: int(p))
    # First migration is 001_ohlcv_bars.
    assert found[0].name == "001_ohlcv_bars.sql"
    assert found[0].sql.strip().startswith("-- 001_ohlcv_bars.sql") or "ohlcv" in found[0].sql.lower()


def test_ch_001_ohlcv_bars_uses_merge_tree() -> None:
    """The OHLCV migration declares two MergeTree tables
    (1m and 1d) with the platform's required clauses."""
    sql = _read_ch_migration("001_ohlcv_bars.sql")
    # Both tables must use MergeTree.
    assert sql.count("ENGINE = MergeTree()") == 2, (
        "expected 2 MergeTree tables (1m + 1d) in 001_ohlcv_bars.sql"
    )
    # Both tables must use ``IF NOT EXISTS`` for idempotent re-runs.
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 2
    # The minute and daily tables are both declared.
    assert "md_bars_1m" in sql
    assert "md_bars_1d" in sql
    # Time column is the platform's primary timezone (Asia/Shanghai).
    assert "DateTime64(3, 'Asia/Shanghai')" in sql
    # Both tables partition by month.
    assert sql.count("PARTITION BY toYYYYMM(dt)") == 2


def test_ch_002_factors_long_uses_merge_tree() -> None:
    """The factors_long migration is a single MergeTree table
    with the long-format (factor, symbol, dt) primary key."""
    sql = _read_ch_migration("002_factors_long.sql")
    assert sql.count("ENGINE = MergeTree()") == 1
    assert "CREATE TABLE IF NOT EXISTS factors_long" in sql
    # Long format: (factor, symbol, dt) — factor first because the
    # read pattern is "latest N for factor F" (the inverse of bars).
    assert "ORDER BY (factor, symbol, dt)" in sql
    assert "DateTime64(3, 'Asia/Shanghai')" in sql
    assert "PARTITION BY toYYYYMM(dt)" in sql


def test_ch_migrations_apply_via_fake_executor() -> None:
    """The runner's ``apply_migrations`` end-to-end works on the
    real CH directory using a fake executor. Catches a class of
    bugs where the runner breaks on multi-statement files."""
    if not _CH_MIGRATIONS_DIR.exists():
        pytest.skip(f"CH migrations dir not present: {_CH_MIGRATIONS_DIR}")
    executor = _FakeExecutor()  # nothing applied yet
    plan = _run(run_directory(_CH_MIGRATIONS_DIR, executor))
    assert len(plan) >= 2
    # All migrations were \"applied\" in order.
    assert [m.prefix for m in executor.apply_calls] == [m.prefix for m in plan]
    # Each migration's SQL was passed verbatim to the executor.
    for migration, call in zip(plan, executor.apply_calls):
        assert call == migration
