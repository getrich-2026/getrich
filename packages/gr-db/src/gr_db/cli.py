"""Command-line entry point for the migration runner.

Invoke via:

    gr-db [migrate|status] [--target pg|ch|all] [--dry-run]

``migrate`` 按数字前缀顺序应用 DDL，``status`` 只列出磁盘上有哪些 DDL。
``--target`` 选数据库：``pg``/``postgres`` 只跑 ``ddl/postgres/*.sql``，
``ch``/``clickhouse`` 只跑 ``ddl/clickhouse/*.sql``，``all``（默认）两者都跑，
PostgreSQL 在前。

The script exits with a non-zero code on any failure. On success it
prints a summary of what was applied (or "no migrations to apply" if
the database is already up to date).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from gr_data.config import settings

from .executors import (
    ClickHouseMigrationExecutor,
    PostgresMigrationExecutor,
)
from .runner import MigrationError, discover_migrations, run_directory


logger = logging.getLogger(__name__)


# DDL 随包安装（见 pyproject 的 package-data），所以基于本模块定位，
# 不依赖仓库布局 —— pip 安装后 gr-db 也能建库。
_DDL_ROOT = Path(__file__).resolve().parent / "ddl"
_DEFAULT_MIGRATIONS_DIR = _DDL_ROOT / "postgres"
_DEFAULT_CLICKHOUSE_DIR = _DDL_ROOT / "clickhouse"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="gr-db",
        description="Apply GetRich database migrations in order.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="migrate",
        choices=("migrate", "status"),
        help="migrate=应用 DDL；status=只看磁盘上有哪些 DDL（默认 migrate）。",
    )
    parser.add_argument(
        "--target",
        default="all",
        choices=("postgres", "pg", "clickhouse", "ch", "all"),
        help="作用于哪个数据库（默认 all）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover + plan only; do not execute any SQL.",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=_DEFAULT_MIGRATIONS_DIR,
        help="Override the PostgreSQL migrations directory.",
    )
    parser.add_argument(
        "--clickhouse-dir",
        type=Path,
        default=_DEFAULT_CLICKHOUSE_DIR,
        help="Override the ClickHouse migrations directory.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Emit DEBUG-level logs.",
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _print_status(directory: Path) -> int:
    """Print applied vs discovered for one directory. Returns 0."""
    discovered = discover_migrations(directory)
    if not discovered:
        print(f"[{directory.name}] no migration files found")
        return 0
    # We don't connect to the DB for ``status`` if the user only wants
    # to see what's on disk; just print the discovered set.
    print(f"[{directory.name}] {len(discovered)} migration(s) discovered:")
    for m in discovered:
        print(f"  - {m.name}")
    print("  (run without 'status' to query the DB and see applied vs pending)")
    return 0


def _run_postgres(args: argparse.Namespace) -> int:
    """Apply PostgreSQL migrations. Returns process exit code."""
    import psycopg

    cfg = settings.postgres
    dsn = (
        f"host={cfg.host} port={cfg.port} user={cfg.user} "
        f"password={cfg.password} dbname={cfg.database}"
    )
    try:
        # 不设 search_path：DDL 全部写全限定 schema 名（见 executors.py）。
        with psycopg.connect(dsn, autocommit=False) as conn:
            executor = PostgresMigrationExecutor(conn)
            plan = asyncio.run(run_directory(args.migrations_dir, executor, dry_run=args.dry_run))
    except MigrationError as exc:
        logger.error("postgres migration failed: %s", exc)
        return 1
    except psycopg.OperationalError as exc:
        logger.error("cannot connect to postgres: %s", exc)
        return 2

    if args.dry_run:
        print(f"[postgres] dry-run complete; {len(plan)} migration(s) would be applied")
    elif plan.migrations:
        print(
            f"[postgres] applied {len(plan)} migration(s): "
            + ", ".join(m.name for m in plan.migrations)
        )
    else:
        print("[postgres] no migrations to apply (already up to date)")
    return 0


def _run_clickhouse(args: argparse.Namespace) -> int:
    """Apply ClickHouse migrations. Returns process exit code."""
    import clickhouse_connect

    cfg = settings.clickhouse
    try:
        # ``clickhouse_connect`` 1.x takes a bare hostname (no URL
        # scheme) and a separate ``secure=`` boolean to pick HTTP
        # vs HTTPS. Earlier versions of this code path passed a
        # ``protocol=`` kwarg that ``HttpClient.__init__`` does
        # not accept, which surfaced as
        #   TypeError: __init__() got an unexpected keyword argument 'protocol'
        # on every migration run. We translate the legacy
        # ``cfg.protocol`` ("http" | "https") into the modern
        # ``secure=`` boolean here.
        secure = cfg.protocol.lower() == "https"
        client = clickhouse_connect.get_client(
            host=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=cfg.password,
            database=cfg.database,
            secure=secure,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("cannot connect to clickhouse: %s", exc)
        return 2

    executor = ClickHouseMigrationExecutor(client)
    try:
        plan = asyncio.run(run_directory(args.clickhouse_dir, executor, dry_run=args.dry_run))
    except MigrationError as exc:
        logger.error("clickhouse migration failed: %s", exc)
        return 1

    if args.dry_run:
        print(f"[clickhouse] dry-run complete; {len(plan)} migration(s) would be applied")
    elif plan.migrations:
        print(
            f"[clickhouse] applied {len(plan)} migration(s): "
            + ", ".join(m.name for m in plan.migrations)
        )
    else:
        print("[clickhouse] no migrations to apply (already up to date)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    target = {"pg": "postgres", "ch": "clickhouse"}.get(args.target, args.target)
    want_pg = target in ("postgres", "all")
    want_ch = target in ("clickhouse", "all")

    if args.command == "status":
        rc = 0
        if want_pg:
            rc = _print_status(args.migrations_dir)
        if want_ch and args.clickhouse_dir.exists():
            rc = _print_status(args.clickhouse_dir) or rc
        return rc

    rc = 0
    if want_pg:
        rc = _run_postgres(args)
        if rc != 0:
            return rc
    if want_ch:
        rc = _run_clickhouse(args)
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
