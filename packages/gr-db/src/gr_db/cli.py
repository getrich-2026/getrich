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
import os
import sys
from pathlib import Path
from uuid import uuid4

from gr_data.config import settings
from gr_data.config.pipeline import load_config

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
        choices=("migrate", "status", "docs"),
        help="migrate=应用 DDL；status=只看磁盘 DDL；docs=生成数据字典（默认 migrate）。",
    )
    parser.add_argument(
        "--target",
        default="all",
        choices=("postgres", "pg", "clickhouse", "ch", "all"),
        help="作用于哪个数据库（默认 all）。",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="数据字典输出路径；'-' 输出到 stdout。默认 raw_root/_docs/data-dictionary.html。",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("html", "json"),
        default="html",
        help="数据字典输出格式（默认 html）。",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="生成数据字典时，发现 error 级漂移则以非零退出。",
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


def _open_postgres_connection() -> object:
    """按迁移 CLI 相同配置建立 PostgreSQL 连接。

    Time Complexity: O(1)。
    Space Complexity: O(1)。
    """
    import psycopg

    cfg = settings.postgres
    dsn = (
        f"host={cfg.host} port={cfg.port} user={cfg.user} "
        f"password={cfg.password} dbname={cfg.database}"
    )
    return psycopg.connect(dsn, autocommit=True)


def _open_clickhouse_client() -> object:
    """按迁移 CLI 相同配置建立 ClickHouse 客户端。

    Time Complexity: O(1)。
    Space Complexity: O(1)。
    """
    import clickhouse_connect

    cfg = settings.clickhouse
    return clickhouse_connect.get_client(
        host=cfg.host,
        port=cfg.port,
        username=cfg.user,
        password=cfg.password,
        database=cfg.database,
        secure=cfg.protocol.lower() == "https",
    )


def _default_docs_out() -> Path:
    """返回数据字典默认产物路径。

    Time Complexity: O(1)。
    Space Complexity: O(1)。
    """
    configured = os.environ.get("GETRICH_DOCS_OUT", "").strip()
    if configured:
        return Path(configured)
    return load_config().raw_root / "_docs" / "data-dictionary.html"


def _write_atomically(path: Path, content: str) -> None:
    """原子写入文本输出，避免读者看到半份字典。

    Time Complexity: O(n)，n 为内容字符数。
    Space Complexity: O(n)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _run_docs(args: argparse.Namespace) -> int:
    """反射所选活库并输出数据字典。

    Time Complexity: O(t + c + r)，由数据库 catalog 与契约规模决定。
    Space Complexity: O(t + c + r)。
    """
    from gr_db.docs import build_dictionary, render_html
    from gr_db.docs.render import render_json

    target = {"pg": "postgres", "ch": "clickhouse"}.get(args.target, args.target)
    postgres_conn = None
    clickhouse_client = None
    try:
        if target in ("postgres", "all"):
            postgres_conn = _open_postgres_connection()
        if target in ("clickhouse", "all"):
            clickhouse_client = _open_clickhouse_client()
        dictionary = build_dictionary(postgres_conn, clickhouse_client)
    except Exception as exc:  # noqa: BLE001
        logger.error("cannot build data dictionary: %s", exc)
        return 2
    finally:
        if postgres_conn is not None:
            postgres_conn.close()
        if clickhouse_client is not None and hasattr(clickhouse_client, "close"):
            clickhouse_client.close()

    content = render_json(dictionary) if args.output_format == "json" else render_html(dictionary)
    output = args.out or _default_docs_out()
    if str(output) == "-":
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
    else:
        _write_atomically(output, content)
        logger.info("data dictionary written to %s", output)
    return int(args.fail_on_drift and any(item.severity == "error" for item in dictionary.findings))


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

    if args.command == "docs":
        return _run_docs(args)

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
