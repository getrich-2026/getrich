"""Command-line entry point for the migration runner.

Invoke via:

    python -m getrich.migrations.cli [TARGET] [--dry-run]

Where ``TARGET`` is one of:

* ``postgres`` (default) — apply ``migrations/*.sql`` in order.
* ``clickhouse`` — apply ``migrations/clickhouse/*.sql`` in order.
* ``all`` — apply both, in order (postgres first).
* ``status`` — print the current applied-vs-discovered state for
  either DB without applying anything.

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

from getrich.config import settings

from .executors import (
    ClickHouseMigrationExecutor,
    PostgresMigrationExecutor,
)
from .runner import MigrationError, discover_migrations, run_directory


logger = logging.getLogger(__name__)


# Package layout: ``migrations/`` lives at the package root, above ``src/``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MIGRATIONS_DIR = _REPO_ROOT / "migrations"
_DEFAULT_CLICKHOUSE_DIR = _DEFAULT_MIGRATIONS_DIR / "clickhouse"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="getrich-migrate",
        description="Apply GetRich database migrations in order.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=("postgres", "clickhouse", "all", "status"),
        help="Which migration set to apply (default: all).",
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
        with psycopg.connect(dsn, options="-c search_path=frontend", autocommit=False) as conn:
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

    if args.target == "status":
        rc = _print_status(args.migrations_dir)
        if args.clickhouse_dir.exists():
            rc = _print_status(args.clickhouse_dir) or rc
        return rc

    rc = 0
    if args.target in ("postgres", "all"):
        rc = _run_postgres(args)
        if rc != 0:
            return rc
    if args.target in ("clickhouse", "all"):
        rc = _run_clickhouse(args)
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
