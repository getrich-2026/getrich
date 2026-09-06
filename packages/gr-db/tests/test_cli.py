"""Tests for ``gr_db.cli``.

The CLI is the entry point for ``python -m gr_db.cli``
— it parses argv, dispatches to a per-DB executor
(PostgreSQL / ClickHouse / both), and propagates exit codes:

- ``0`` — success (or "no migrations to apply")
- ``1`` — `MigrationError` (a migration failed to apply)
- ``2`` — connection / driver error (could not reach the DB)
- ``2`` — usage error (no / unknown subcommand)

We test by mocking the executors, the ``psycopg`` and
``clickhouse_connect`` modules, and ``asyncio.run``. That
way no real DB is required.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from gr_db import cli
from gr_db.runner import Migration, MigrationError, MigrationPlan


_EMPTY_SUM = hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults_to_migrate_all() -> None:
    """无参数时：command=migrate、target=all（PG 与 CH 都跑）。"""
    ns = cli._parse_args([])
    assert ns.command == "migrate"
    assert ns.target == "all"
    assert ns.dry_run is False
    assert ns.verbose is False


def test_parse_args_postgres_target() -> None:
    ns = cli._parse_args(["migrate", "--target", "postgres"])
    assert ns.command == "migrate"
    assert ns.target == "postgres"


def test_parse_args_clickhouse_target() -> None:
    ns = cli._parse_args(["migrate", "--target", "clickhouse"])
    assert ns.target == "clickhouse"


def test_parse_args_accepts_short_target_aliases() -> None:
    """``pg``/``ch`` 是 ``postgres``/``clickhouse`` 的简写。"""
    assert cli._parse_args(["migrate", "--target", "pg"]).target == "pg"
    assert cli._parse_args(["migrate", "--target", "ch"]).target == "ch"


def test_parse_args_status_command() -> None:
    ns = cli._parse_args(["status"])
    assert ns.command == "status"
    assert ns.target == "all"


def test_parse_args_docs_command() -> None:
    """数据字典命令提供结构化输出与严格漂移模式。"""
    ns = cli._parse_args(["docs", "--target", "pg", "--format", "json", "--fail-on-drift"])
    assert ns.command == "docs"
    assert ns.output_format == "json"
    assert ns.fail_on_drift is True


def test_run_docs_clickhouse_only_strict_mode_skips_postgres_drift_checks(
    tmp_path: Path,
) -> None:
    """ClickHouse-only 严格模式不应因未连接 PG 而返回漂移错误。"""
    output = tmp_path / "dictionary.json"
    args = cli._parse_args(
        [
            "docs",
            "--target",
            "ch",
            "--format",
            "json",
            "--out",
            str(output),
            "--fail-on-drift",
        ]
    )
    clickhouse_client = MagicMock()

    with (
        patch.object(cli, "_open_postgres_connection") as open_postgres,
        patch.object(cli, "_open_clickhouse_client", return_value=clickhouse_client),
        patch("gr_db.docs.introspect_clickhouse", return_value=()),
        patch("gr_db.docs.discover_datasets", return_value=()),
    ):
        rc = cli._run_docs(args)

    assert rc == 0
    assert output.exists()
    open_postgres.assert_not_called()
    clickhouse_client.close.assert_called_once()


def test_parse_args_unknown_command_exits() -> None:
    """未知子命令触发 argparse 的 error → SystemExit(2)。"""
    with pytest.raises(SystemExit) as exc_info:
        cli._parse_args(["frobnicate"])
    assert exc_info.value.code == 2


def test_parse_args_unknown_target_exits() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._parse_args(["migrate", "--target", "mysql"])
    assert exc_info.value.code == 2


def test_parse_args_dry_run_flag() -> None:
    ns = cli._parse_args(["--dry-run"])
    assert ns.dry_run is True


def test_parse_args_verbose_flag() -> None:
    ns = cli._parse_args(["-v"])
    assert ns.verbose is True

    ns = cli._parse_args(["--verbose"])
    assert ns.verbose is True


def test_parse_args_custom_migrations_dir() -> None:
    ns = cli._parse_args(["--migrations-dir", "/tmp/custom"])
    assert ns.migrations_dir == Path("/tmp/custom")


def test_parse_args_custom_clickhouse_dir() -> None:
    ns = cli._parse_args(["--clickhouse-dir", "/tmp/ch"])
    assert ns.clickhouse_dir == Path("/tmp/ch")


def test_parse_args_default_dirs_point_into_package() -> None:
    """默认 DDL 目录从 ``gr_db.__file__`` 推导，跟着包走而不是跟着 cwd 或仓库布局。

    DDL 是 package-data，``pip install gr-db`` 之后也必须能建库。
    """
    ns = cli._parse_args([])
    assert ns.migrations_dir.name == "postgres"
    assert ns.clickhouse_dir.name == "clickhouse"
    assert ns.migrations_dir.parent == ns.clickhouse_dir.parent
    assert ns.migrations_dir.parent.name == "ddl"
    assert ns.migrations_dir.is_dir()
    assert ns.clickhouse_dir.is_dir()


# ---------------------------------------------------------------------------
# _configure_logging
# ---------------------------------------------------------------------------


def test_configure_logging_info_default() -> None:
    with patch.object(cli, "logging") as fake_logging:
        cli._configure_logging(verbose=False)
    fake_logging.basicConfig.assert_called_once()
    kwargs = fake_logging.basicConfig.call_args.kwargs
    assert kwargs["level"] == fake_logging.INFO
    assert "%(asctime)s" in kwargs["format"]


def test_configure_logging_debug_when_verbose() -> None:
    with patch.object(cli, "logging") as fake_logging:
        cli._configure_logging(verbose=True)
    kwargs = fake_logging.basicConfig.call_args.kwargs
    assert kwargs["level"] == fake_logging.DEBUG


# ---------------------------------------------------------------------------
# _print_status
# ---------------------------------------------------------------------------


def test_print_status_empty_directory(tmp_path: Path, capsys) -> None:
    """`status` on an empty directory prints a 'no migrations
    found' line and returns 0."""
    rc = cli._print_status(tmp_path)
    captured = capsys.readouterr()
    assert "no migration files found" in captured.out
    assert rc == 0


def test_print_status_lists_discovered_migrations(tmp_path: Path, capsys) -> None:
    """With two .sql files in the directory, status prints
    the count and the names."""
    (tmp_path / "001_init.sql").write_text("-- init", encoding="utf-8")
    (tmp_path / "002_add_users.sql").write_text("-- users", encoding="utf-8")

    rc = cli._print_status(tmp_path)
    captured = capsys.readouterr()
    assert "2 migration(s) discovered" in captured.out
    assert "001_init.sql" in captured.out
    assert "002_add_users.sql" in captured.out
    assert rc == 0


# ---------------------------------------------------------------------------
# _run_postgres
# ---------------------------------------------------------------------------


def _fake_settings_postgres():
    """Build a `MagicMock` standing in for `settings.postgres`."""
    cfg = MagicMock()
    cfg.host = "pg.host"
    cfg.port = 5432
    cfg.user = "alice"
    cfg.password = "secret"
    cfg.database = "getrich"
    return cfg


def test_run_postgres_success_prints_summary(tmp_path: Path, capsys) -> None:
    """A successful apply prints 'applied N migration(s): ...'
    and returns 0."""
    plan = MigrationPlan(
        migrations=(
            Migration(
                prefix="001",
                name="001_init.sql",
                path=Path("001_init.sql"),
                sql="",
                checksum=_EMPTY_SUM,
            ),
            Migration(
                prefix="002",
                name="002_users.sql",
                path=Path("002_users.sql"),
                sql="",
                checksum=_EMPTY_SUM,
            ),
        )
    )

    fake_conn = MagicMock()
    fake_psycopg = MagicMock()
    # `psycopg.connect(...)` returns a context manager.
    fake_psycopg.connect.return_value.__enter__.return_value = fake_conn
    fake_psycopg.connect.return_value.__exit__.return_value = False

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"psycopg": fake_psycopg}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.postgres = _fake_settings_postgres()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_postgres(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "applied 2 migration(s)" in captured.out
    assert "001_init" in captured.out
    assert "002_users" in captured.out


def test_run_postgres_no_migrations_prints_already_up_to_date(tmp_path: Path, capsys) -> None:
    """Empty plan: 'no migrations to apply (already up to date)'."""
    plan = MigrationPlan(migrations=())

    fake_conn = MagicMock()
    fake_psycopg = MagicMock()
    fake_psycopg.connect.return_value.__enter__.return_value = fake_conn
    fake_psycopg.connect.return_value.__exit__.return_value = False

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"psycopg": fake_psycopg}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.postgres = _fake_settings_postgres()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_postgres(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "no migrations to apply" in captured.out


def test_run_postgres_dry_run_prints_dry_run_message(tmp_path: Path, capsys) -> None:
    """`--dry-run` triggers the dry-run message, regardless
    of plan contents."""
    plan = MigrationPlan(
        migrations=(
            Migration(
                prefix="001",
                name="001_init.sql",
                path=Path("001_init.sql"),
                sql="",
                checksum=_EMPTY_SUM,
            ),
        )
    )

    fake_conn = MagicMock()
    fake_psycopg = MagicMock()
    fake_psycopg.connect.return_value.__enter__.return_value = fake_conn
    fake_psycopg.connect.return_value.__exit__.return_value = False

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"psycopg": fake_psycopg}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.postgres = _fake_settings_postgres()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=True,
        )
        rc = cli._run_postgres(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "dry-run complete" in captured.out


def test_run_postgres_migration_error_returns_1(tmp_path: Path) -> None:
    """`MigrationError` is mapped to exit code 1 (failure
    that the operator should investigate)."""
    fake_conn = MagicMock()
    fake_psycopg = MagicMock()
    fake_psycopg.connect.return_value.__enter__.return_value = fake_conn
    fake_psycopg.connect.return_value.__exit__.return_value = False

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"psycopg": fake_psycopg}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.postgres = _fake_settings_postgres()
        fake_asyncio.run.side_effect = MigrationError("table create failed")

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_postgres(args)

    assert rc == 1


def test_run_postgres_connection_error_returns_2(tmp_path: Path) -> None:
    """`psycopg.OperationalError` (DB unreachable) is mapped
    to exit code 2 (infra error, distinct from migration
    failure)."""
    fake_psycopg = MagicMock()
    fake_psycopg.OperationalError = RuntimeError
    fake_psycopg.connect.side_effect = RuntimeError("connection refused")

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"psycopg": fake_psycopg}),
    ):
        fake_settings.postgres = _fake_settings_postgres()

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_postgres(args)

    assert rc == 2


# ---------------------------------------------------------------------------
# _run_clickhouse
# ---------------------------------------------------------------------------


def _fake_settings_clickhouse():
    cfg = MagicMock()
    cfg.host = "ch.host"
    cfg.port = 9000
    cfg.user = "default"
    cfg.password = ""
    cfg.database = "goldmine"
    cfg.protocol = "native"
    return cfg


def test_run_clickhouse_success_returns_0(tmp_path: Path, capsys) -> None:
    plan = MigrationPlan(
        migrations=(
            Migration(
                prefix="003",
                name="003_klines.sql",
                path=Path("003_klines.sql"),
                sql="",
                checksum=_EMPTY_SUM,
            ),
        )
    )

    fake_chc = MagicMock()
    fake_chc.get_client.return_value = MagicMock()

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"clickhouse_connect": fake_chc}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.clickhouse = _fake_settings_clickhouse()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_clickhouse(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "applied 1 migration(s)" in captured.out
    assert "003_klines" in captured.out


def test_run_clickhouse_no_migrations_prints_up_to_date(tmp_path: Path, capsys) -> None:
    plan = MigrationPlan(migrations=())

    fake_chc = MagicMock()
    fake_chc.get_client.return_value = MagicMock()

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"clickhouse_connect": fake_chc}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.clickhouse = _fake_settings_clickhouse()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_clickhouse(args)

    assert rc == 0
    assert "no migrations to apply" in capsys.readouterr().out


def test_run_clickhouse_dry_run(tmp_path: Path, capsys) -> None:
    plan = MigrationPlan(
        migrations=(
            Migration(
                prefix="001",
                name="001_init.sql",
                path=Path("001_init.sql"),
                sql="",
                checksum=_EMPTY_SUM,
            ),
        )
    )

    fake_chc = MagicMock()
    fake_chc.get_client.return_value = MagicMock()

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"clickhouse_connect": fake_chc}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.clickhouse = _fake_settings_clickhouse()
        fake_asyncio.run.return_value = plan

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=True,
        )
        rc = cli._run_clickhouse(args)

    assert rc == 0
    assert "dry-run complete" in capsys.readouterr().out


def test_run_clickhouse_migration_error_returns_1(tmp_path: Path) -> None:
    fake_chc = MagicMock()
    fake_chc.get_client.return_value = MagicMock()

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"clickhouse_connect": fake_chc}),
        patch("gr_db.cli.asyncio") as fake_asyncio,
    ):
        fake_settings.clickhouse = _fake_settings_clickhouse()
        fake_asyncio.run.side_effect = MigrationError("DDL failed")

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_clickhouse(args)

    assert rc == 1


def test_run_clickhouse_connect_failure_returns_2(tmp_path: Path) -> None:
    fake_chc = MagicMock()
    fake_chc.get_client.side_effect = RuntimeError("DNS resolution failed")

    with (
        patch.object(cli, "settings") as fake_settings,
        patch.dict("sys.modules", {"clickhouse_connect": fake_chc}),
    ):
        fake_settings.clickhouse = _fake_settings_clickhouse()

        args = argparse.Namespace(
            migrations_dir=tmp_path,
            clickhouse_dir=tmp_path,
            dry_run=False,
        )
        rc = cli._run_clickhouse(args)

    assert rc == 2


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_status_target_only(tmp_path: Path) -> None:
    """`status` target doesn't connect to either DB; it
    just prints the discovered sets."""
    (tmp_path / "001_init.sql").write_text("-- init", encoding="utf-8")
    clickhouse_dir = tmp_path / "clickhouse"
    clickhouse_dir.mkdir()

    rc = cli.main(
        ["status", "--migrations-dir", str(tmp_path), "--clickhouse-dir", str(clickhouse_dir)]
    )
    assert rc == 0


def test_main_postgres_only_runs_postgres(tmp_path: Path) -> None:
    """``--target pg`` 只跑 PostgreSQL，绝不实例化 ClickHouse 客户端。

    直接走 ``cli.main()``（不再手工复刻 dispatch 逻辑）—— 复刻出来的分支
    永远不会失败，测不到 main() 真实的分派。
    """
    with (
        patch.object(cli, "_run_postgres", return_value=0) as fake_pg,
        patch.object(cli, "_run_clickhouse") as fake_ch,
    ):
        rc = cli.main(
            ["migrate", "--target", "pg", "--migrations-dir", str(tmp_path)],
        )

    assert rc == 0
    assert fake_pg.call_count == 1
    assert fake_ch.call_count == 0


def test_main_clickhouse_only_runs_clickhouse(tmp_path: Path) -> None:
    """``--target ch`` 只跑 ClickHouse。"""
    with (
        patch.object(cli, "_run_postgres") as fake_pg,
        patch.object(cli, "_run_clickhouse", return_value=0) as fake_ch,
    ):
        rc = cli.main(
            ["migrate", "--target", "ch", "--clickhouse-dir", str(tmp_path)],
        )

    assert rc == 0
    assert fake_pg.call_count == 0
    assert fake_ch.call_count == 1


def test_main_all_target_runs_both(tmp_path: Path) -> None:
    """`all` target runs postgres THEN clickhouse (in order).
    A postgres failure aborts before clickhouse runs."""
    with (
        patch.object(cli, "_run_postgres", return_value=1) as fake_pg,
        patch.object(cli, "_run_clickhouse") as fake_ch,
    ):
        rc = cli.main(
            ["migrate", "--migrations-dir", str(tmp_path), "--clickhouse-dir", str(tmp_path)],
        )
    # Postgres returned 1 → main returns 1 immediately.
    assert rc == 1
    assert fake_pg.call_count == 1
    # Clickhouse was NEVER called (postgres failed first).
    assert fake_ch.call_count == 0


def test_main_all_target_propagates_clickhouse_rc(tmp_path: Path) -> None:
    """If postgres succeeds and clickhouse fails, main returns
    the clickhouse exit code."""
    with (
        patch.object(cli, "_run_postgres", return_value=0) as fake_pg,
        patch.object(cli, "_run_clickhouse", return_value=2) as fake_ch,
    ):
        rc = cli.main(
            ["migrate", "--migrations-dir", str(tmp_path), "--clickhouse-dir", str(tmp_path)],
        )
    assert rc == 2
    assert fake_pg.call_count == 1
    assert fake_ch.call_count == 1


def test_main_verbose_passes_through(tmp_path: Path) -> None:
    """`--verbose` triggers DEBUG-level logging via
    `_configure_logging(verbose=True)`."""
    with (
        patch.object(cli, "_configure_logging") as fake_cfg,
        patch.object(cli, "_run_postgres", return_value=0),
        patch.object(cli, "_run_clickhouse", return_value=0),
    ):
        cli.main(
            ["migrate", "-v", "--migrations-dir", str(tmp_path), "--clickhouse-dir", str(tmp_path)],
        )
    fake_cfg.assert_called_once_with(True)
