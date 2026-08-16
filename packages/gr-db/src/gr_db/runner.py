"""Core migration runner logic.

Pure functions and small classes — no I/O outside the public API.
The CLI module in ``gr_db.cli`` wires this up to actual
PostgreSQL / ClickHouse connections.

记账用 **checksum**（file_name -> sha256），不是单纯的「前缀是否出现过」：
后者检测不到「文件已应用、之后又被改过」这种情况，会让库结构和仓库里的
DDL 静默分叉。checksum 变了就重新应用（``reapplied``），因此所有 DDL
文件必须写成幂等的（``CREATE ... IF NOT EXISTS`` / ``ADD COLUMN IF NOT EXISTS``）。

Public API
----------
* :class:`Migration` — value object for one discovered migration file.
* :class:`MigrationPlan` — ordered plan of migrations to apply.
* :func:`discover_migrations` — scan a directory for ``NNN_*.sql`` files.
* :func:`build_plan` — given discovered migrations + a set of already-
  applied prefixes, produce the ordered list of new migrations.
* :func:`apply_migrations` — execute a plan against a target DB.
* :class:`MigrationError` — raised on any failure.

The runner does not depend on ``clickhouse_connect`` or ``psycopg`` at
import time — callers inject a simple ``MigrationExecutor`` protocol
that the runner drives. This keeps the module testable without a live
database.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


_MIGRATION_FILENAME_RE = re.compile(r"^(\d{3,})_.+\.sql$")


class MigrationError(RuntimeError):
    """Raised when the migration runner fails for any reason."""


@dataclass(frozen=True)
class Migration:
    """A single migration file on disk.

    Attributes
    ----------
    prefix : str
        The numeric prefix as a string (e.g. ``"001"`` or ``"010"``).
        Kept as a string so lexicographic sort produces the same
        ordering as numeric sort for 3+ digit prefixes.
    name : str
        The filename including prefix (e.g. ``"001_sub_account_routing.sql"``).
    path : Path
        Absolute path to the file on disk.
    sql : str
        The full file contents (read at discovery time).
    checksum : str
        ``sha256`` of ``sql``；用于判断已应用的文件是否被改动过。
    """

    prefix: str
    name: str
    path: Path
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationPlan:
    """The set of migrations to apply, in order."""

    migrations: tuple[Migration, ...]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.migrations)

    def __len__(self) -> int:
        return len(self.migrations)

    @property
    def is_empty(self) -> bool:
        return len(self.migrations) == 0


class MigrationExecutor(Protocol):
    """Protocol implemented by the PostgreSQL / ClickHouse executors.

    The runner drives three operations on the target DB:

    * :meth:`ensure_tracking_table` — create the ``schema_migrations``
      bookkeeping table if absent.
    * :meth:`fetch_applied` — return ``{file_name: checksum}`` of已应用文件。
    * :meth:`apply_one` — execute one migration's SQL and record the
      name + checksum in the tracking table. Implementations are expected
      to be transactional so a failure rolls back both the schema change
      and the bookkeeping row.
    """

    async def ensure_tracking_table(self) -> None: ...

    async def fetch_applied(self) -> dict[str, str]: ...

    async def apply_one(self, migration: Migration) -> None: ...


# ---------------------------------------------------------------- discovery


def discover_migrations(directory: Path) -> list[Migration]:
    """Scan *directory* for ``NNN_*.sql`` files and return them in
    numeric-prefix order.

    Files that do not match the ``NNN_*.sql`` pattern (e.g.
    ``README.md`` or ``seed.sql``) are ignored. The function does not
    recurse into subdirectories.

    Raises
    ------
    MigrationError
        If two files share the same numeric prefix, or if the numeric
        prefixes are not contiguous (a gap from 003 to 005 means 004 is
        missing and the runner refuses to proceed silently).
    """
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise MigrationError(f"migration path is not a directory: {directory}")

    found: dict[str, Migration] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        match = _MIGRATION_FILENAME_RE.match(path.name)
        if match is None:
            logger.debug("skipping non-migration file: %s", path.name)
            continue
        prefix = match.group(1)
        if prefix in found:
            raise MigrationError(
                f"duplicate migration prefix {prefix!r}: {found[prefix].name} and {path.name}"
            )
        sql = path.read_text(encoding="utf-8")
        found[prefix] = Migration(
            prefix=prefix,
            name=path.name,
            path=path.resolve(),
            sql=sql,
            checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        )

    if not found:
        return []

    # Contiguity check: every integer from the smallest to the largest
    # prefix must be present.
    numeric = sorted(int(p) for p in found)
    expected = list(range(numeric[0], numeric[-1] + 1))
    if numeric != expected:
        missing = sorted(set(expected) - set(numeric))
        raise MigrationError(
            f"non-contiguous migration prefixes under {directory}: missing {missing}"
        )

    # Return sorted by the (string) prefix, which is identical to
    # numeric sort for fixed-width 3+ digit prefixes.
    return [found[f"{n:03d}"] if n < 1000 else found[str(n)] for n in numeric]


def build_plan(discovered: list[Migration], applied: dict[str, str]) -> MigrationPlan:
    """给定已发现的迁移与 ``{file_name: checksum}``，产出待执行计划（按前缀序）。

    一个文件会进入计划，当且仅当：

    * 从未应用过（``name`` 不在 ``applied`` 里）；或
    * 应用过但内容已变（checksum 不一致）—— 此时重新应用，依赖 DDL 的幂等性。

    ``applied`` 里有、但仓库里已删除的文件只记日志，不报错（允许下线旧迁移）。
    """
    stale = set(applied) - {m.name for m in discovered}
    if stale:
        logger.info(
            "ledger has %d applied file(s) no longer on disk: %s", len(stale), sorted(stale)
        )

    new: list[Migration] = []
    for m in discovered:
        previous = applied.get(m.name)
        if previous is None:
            new.append(m)
        elif previous != m.checksum:
            logger.warning(
                "migration %s changed since it was applied (checksum %s -> %s); re-applying",
                m.name,
                previous[:12],
                m.checksum[:12],
            )
            new.append(m)
    return MigrationPlan(migrations=tuple(new))


# ---------------------------------------------------------------- execution


async def apply_migrations(
    plan: MigrationPlan,
    executor: MigrationExecutor,
    *,
    dry_run: bool = False,
) -> tuple[MigrationPlan, list[Migration]]:
    """Apply a plan against a target DB.

    Returns a tuple ``(applied, skipped)`` where ``applied`` is the
    plan that was successfully committed and ``skipped`` is the list
    of migrations that were discovered but already applied (only
    populated for logging convenience when the caller assembles the
    full list).

    When ``dry_run`` is True, the executor's :meth:`apply_one` is
    never called; instead the runner logs which migrations *would* be
    applied and returns an empty applied list.

    Raises
    ------
    MigrationError
        If the executor's :meth:`apply_one` raises. The exception is
        wrapped to indicate which migration failed.
    """
    if plan.is_empty:
        logger.info("no migrations to apply (plan is empty)")
        return plan, []

    applied: list[Migration] = []
    for migration in plan:
        if dry_run:
            logger.info("DRY-RUN would apply: %s", migration.name)
            continue
        logger.info("applying migration: %s", migration.name)
        try:
            await executor.apply_one(migration)
        except Exception as exc:  # noqa: BLE001
            raise MigrationError(f"failed to apply migration {migration.name!r}: {exc}") from exc
        applied.append(migration)

    if not dry_run and applied:
        logger.info("applied %d migration(s) successfully", len(applied))
    return MigrationPlan(migrations=tuple(applied)), []


# ---------------------------------------------------------------- high-level entry


async def run_directory(
    directory: Path,
    executor: MigrationExecutor,
    *,
    dry_run: bool = False,
) -> MigrationPlan:
    """High-level helper: discover + plan + apply.

    The single entry point for both the CLI and tests. Performs the
    full happy path in one call.
    """
    discovered = discover_migrations(directory)
    if not discovered:
        logger.info("no migration files found under %s", directory)
        return MigrationPlan(migrations=())

    await executor.ensure_tracking_table()
    applied = await executor.fetch_applied()
    plan = build_plan(discovered, applied)
    if plan.is_empty:
        logger.info("all %d discovered migration(s) already applied", len(discovered))
        return plan

    logger.info(
        "plan: %d migration(s) pending out of %d discovered",
        len(plan),
        len(discovered),
    )
    return (await apply_migrations(plan, executor, dry_run=dry_run))[0]
