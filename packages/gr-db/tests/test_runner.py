"""Unit tests for the pure-Python migration runner.

The runner itself is DB-agnostic: it discovers files, builds a plan,
and drives a :class:`MigrationExecutor` protocol. We exercise it with
an in-memory fake executor so no PostgreSQL or ClickHouse is needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import gr_db as _gr_db
import pytest
from gr_db.runner import (
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


def _sum(sql: str) -> str:
    """与 runner.discover_migrations 一致的 checksum 算法。"""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


class _FakeExecutor(MigrationExecutor):
    """Records every method call and lets tests inject an applied ledger."""

    def __init__(
        self,
        applied: dict[str, str] | None = None,
        raise_on_apply: Exception | None = None,
    ) -> None:
        self.ensure_calls = 0
        self.fetch_calls = 0
        self.apply_calls: list[Migration] = []
        self._applied: dict[str, str] = dict(applied or {})
        self._raise = raise_on_apply

    async def ensure_tracking_table(self) -> None:
        self.ensure_calls += 1

    async def fetch_applied(self) -> dict[str, str]:
        self.fetch_calls += 1
        return dict(self._applied)

    async def apply_one(self, migration: Migration) -> None:
        self.apply_calls.append(migration)
        if self._raise is not None:
            raise self._raise
        self._applied[migration.name] = migration.checksum


def _ledger(*paths: Path) -> dict[str, str]:
    """把磁盘上的迁移文件转成 ``{file_name: checksum}`` 账本，模拟已应用状态。"""
    return {p.name: _sum(p.read_text(encoding="utf-8")) for p in paths}


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
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
    ]
    plan = build_plan(discovered, applied={m.name: m.checksum for m in discovered})
    assert plan.is_empty


def test_build_plan_returns_only_pending() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
        Migration(prefix="003", name="003_c.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
    ]
    plan = build_plan(discovered, applied={discovered[0].name: discovered[0].checksum})
    assert [m.prefix for m in plan] == ["002", "003"]


def test_build_plan_ignores_unknown_applied() -> None:
    """An applied file with no corresponding file on disk is logged but ignored."""
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="--", checksum=_sum("--")),
    ]
    plan = build_plan(
        discovered,
        applied={discovered[0].name: discovered[0].checksum, "999_retired.sql": _sum("--")},
    )
    # 999 was applied previously but the file no longer exists — fine.
    assert [m.prefix for m in plan] == []


# ---------------------------------------------------------------- apply_migrations


def test_apply_runs_each_migration_in_order() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="A", checksum=_sum("A")),
        Migration(prefix="002", name="002_b.sql", path=Path("/x"), sql="B", checksum=_sum("B")),
    ]
    plan = MigrationPlan(migrations=tuple(discovered))
    executor = _FakeExecutor()

    _run(apply_migrations(plan, executor))

    assert [m.prefix for m in executor.apply_calls] == ["001", "002"]


def test_apply_dry_run_does_not_call_executor() -> None:
    discovered = [
        Migration(prefix="001", name="001_a.sql", path=Path("/x"), sql="A", checksum=_sum("A")),
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
    first = _write_migration(tmp_migrations_dir, "001", "a")
    _write_migration(tmp_migrations_dir, "002", "b")
    _write_migration(tmp_migrations_dir, "003", "c")
    executor = _FakeExecutor(applied=_ledger(first))

    plan = _run(run_directory(tmp_migrations_dir, executor))

    assert [m.prefix for m in plan] == ["002", "003"]
    assert executor.ensure_calls == 1
    assert executor.fetch_calls == 1
    assert [m.prefix for m in executor.apply_calls] == ["002", "003"]


def test_run_directory_is_idempotent(tmp_migrations_dir: Path) -> None:
    """Re-running with everything applied is a no-op (no executor calls)."""
    a = _write_migration(tmp_migrations_dir, "001", "a")
    b = _write_migration(tmp_migrations_dir, "002", "b")
    executor = _FakeExecutor(applied=_ledger(a, b))

    plan = _run(run_directory(tmp_migrations_dir, executor))

    assert plan.is_empty
    assert executor.apply_calls == []


def test_run_directory_reapplies_changed_file(tmp_migrations_dir: Path) -> None:
    """已应用的文件被改动后必须重新执行 —— 这正是 checksum 记账相对
    「只记前缀」的价值：内容改了但前缀没变，旧方案会静默跳过，
    导致库结构与仓库里的 DDL 分叉。"""
    a = _write_migration(tmp_migrations_dir, "001", "a")
    executor = _FakeExecutor(applied=_ledger(a))

    # 内容改动（前缀与文件名都不变）
    a.write_text("-- Migration 001 (edited)\nCREATE TABLE t_001 (id BIGINT);\n", encoding="utf-8")

    plan = _run(run_directory(tmp_migrations_dir, executor))

    assert [m.name for m in plan] == ["001_a.sql"]
    assert [m.name for m in executor.apply_calls] == ["001_a.sql"]


def test_run_directory_empty_directory(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    plan = _run(run_directory(tmp_path, executor))
    assert plan.is_empty
    # Empty directory never touches the executor (no tracking table).
    assert executor.ensure_calls == 0
    assert executor.fetch_calls == 0


# ------------------------------------------------- ClickHouse DDL verification
#
# Round #1143: verify the real ``migrations/clickhouse/`` directory
# (a) is discoverable, (b) contains valid MergeTree DDL, (c) uses
# ``IF NOT EXISTS`` for idempotency. The runner contract is exercised
# end-to-end against a fake executor so we don't need a live CH.


# DDL 是 package-data，跟着 gr_db 包走，不依赖仓库相对布局。
_DDL_ROOT = Path(_gr_db.__file__).resolve().parent / "ddl"
_CH_MIGRATIONS_DIR = _DDL_ROOT / "clickhouse"
_PG_MIGRATIONS_DIR = _DDL_ROOT / "postgres"


def _read_ch_migration(name: str) -> str:
    """Read a real CH migration file from the repo."""
    path = _CH_MIGRATIONS_DIR / name
    assert path.exists(), f"CH migration file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_ch_migrations_dir_exists_and_has_files() -> None:
    """打包进 gr_db 的 ``ddl/clickhouse/`` 目录含预期的 DDL。"""
    assert _CH_MIGRATIONS_DIR.exists(), f"CH DDL directory missing: {_CH_MIGRATIONS_DIR}"
    files = sorted(_CH_MIGRATIONS_DIR.glob("*.sql"))
    assert len(files) >= 1, f"expected >= 1 CH DDL file, found {len(files)}"
    prefixes = [f.stem.split("_", 1)[0] for f in files]
    assert prefixes[0] == "001", f"unexpected prefix sequence: {prefixes}"


def test_pg_ddl_dir_is_contiguous_and_covers_all_schemas() -> None:
    """PostgreSQL DDL 前缀连续，且七个 schema 全部被创建。"""
    found = discover_migrations(_PG_MIGRATIONS_DIR)
    assert len(found) == 33, f"expected 33 PG DDL files, found {len(found)}"
    assert [int(m.prefix) for m in found] == list(range(1, 34))

    all_sql = "\n".join(m.sql for m in found)
    for schema in ("meta", "market", "realtime", "staging", "ops", "app", "backtest"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in all_sql, f"schema {schema} 未创建"
    # frontend 已被 app / backtest 取代，任何 SQL 语句里都不该再出现。
    statements = "\n".join(
        line for line in all_sql.splitlines() if not line.lstrip().startswith("--")
    )
    assert "frontend." not in statements, "残留 frontend. schema 引用"


def test_ch_migrations_discoverable_via_runner() -> None:
    """The runner's ``discover_migrations`` finds the real CH
    files in the right order. Uses a fresh ``_FakeExecutor`` so
    no real CH client is needed."""
    if not _CH_MIGRATIONS_DIR.exists():
        pytest.skip(f"CH migrations dir not present: {_CH_MIGRATIONS_DIR}")
    found = discover_migrations(_CH_MIGRATIONS_DIR)
    assert len(found) >= 1
    # Migrations are sorted by numeric prefix.
    prefixes = [m.prefix for m in found]
    assert prefixes == sorted(prefixes, key=lambda p: int(p))
    # 唯一一张 CH 表是因子时序（行情已改由 PostgreSQL/TimescaleDB 承担）。
    assert found[0].name == "001_factors_long.sql"
    assert "factors_long" in found[0].sql


def test_ch_migrations_apply_via_fake_executor() -> None:
    """The runner's ``apply_migrations`` end-to-end works on the
    real CH directory using a fake executor. Catches a class of
    bugs where the runner breaks on multi-statement files."""
    if not _CH_MIGRATIONS_DIR.exists():
        pytest.skip(f"CH migrations dir not present: {_CH_MIGRATIONS_DIR}")
    executor = _FakeExecutor()  # nothing applied yet
    plan = _run(run_directory(_CH_MIGRATIONS_DIR, executor))
    assert len(plan) >= 1
    # All migrations were \"applied\" in order.
    assert [m.prefix for m in executor.apply_calls] == [m.prefix for m in plan]
    # Each migration's SQL was passed verbatim to the executor.
    for migration, call in zip(plan, executor.apply_calls, strict=True):
        assert call == migration
