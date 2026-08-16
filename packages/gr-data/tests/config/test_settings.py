"""Tests for the ``WorkerConfig`` block in ``gr_data.config.settings``."""

from __future__ import annotations

import os

from gr_data.config.settings import ClickHouseConfig, WorkerConfig, make_pg_dsn


def test_from_env_defaults(monkeypatch: object) -> None:
    """Defaults: backend=inproc, broker=localhost, flower=localhost:5555."""
    # 必须显式清空环境：本仓根目录有真实 .env，且 find_project_root() 修好后
    # 会真的把它加载进 os.environ（见 DECISIONS.md D-003）。不清空的话这个用例
    # 测的是开发者本机配置，不是 dataclass 默认值。
    monkeypatch.setattr(os, "environ", {})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "inproc"
    assert cfg.broker_url == "redis://localhost:6379/0"
    assert cfg.result_backend == "redis://localhost:6379/0"
    assert cfg.flower_url == "http://localhost:5555"


def test_from_env_celery_backend(monkeypatch: object) -> None:
    """Switching to celery with a non-default broker URL is reflected."""
    monkeypatch.setattr(  # type: ignore[attr-defined]
        os,
        "environ",
        {
            "GETRICH_WORKER_BACKEND": "celery",
            "GETRICH_BROKER_URL": "redis://broker.internal:6379/3",
            "GETRICH_RESULT_BACKEND": "redis://broker.internal:6379/4",
        },
    )
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "celery"
    assert cfg.broker_url == "redis://broker.internal:6379/3"
    assert cfg.result_backend == "redis://broker.internal:6379/4"


def test_from_env_invalid_backend_falls_back(monkeypatch: object) -> None:
    """Unknown backend values fall back to ``inproc`` with a warning."""
    monkeypatch.setattr(os, "environ", {"GETRICH_WORKER_BACKEND": "rabbitmq"})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "inproc"


def test_from_env_backend_case_insensitive(monkeypatch: object) -> None:
    """``CELERY`` (uppercase) normalises to ``celery``."""
    monkeypatch.setattr(os, "environ", {"GETRICH_WORKER_BACKEND": "CELERY"})  # type: ignore[attr-defined]
    cfg = WorkerConfig.from_env(strict=False)
    assert cfg.backend == "celery"


def test_make_pg_dsn_with_password() -> None:
    """A populated password is included in the DSN."""

    class _Pg:
        host = "db.example.com"
        port = 5432
        user = "quant"
        password = "s3cr3t"
        database = "goldmine"

    dsn = make_pg_dsn(_Pg())  # type: ignore[arg-type]
    assert dsn == "postgresql://quant:s3cr3t@db.example.com:5432/goldmine"


def test_make_pg_dsn_without_password() -> None:
    """An empty password collapses the colon (avoids ``user:@host``)."""

    class _Pg:
        host = "db.example.com"
        port = 5432
        user = "quant"
        password = ""
        database = "goldmine"

    dsn = make_pg_dsn(_Pg())  # type: ignore[arg-type]
    assert dsn == "postgresql://quant@db.example.com:5432/goldmine"


# -------------------------------------------- ClickHouse 默认值回归（Round #1143）


def test_clickhouse_default_host_is_localhost(monkeypatch: object) -> None:
    """Regression for Round #1143: a developer's LAN IP (``192.168.1.60``)
    leaked into ``settings.py`` as the default ``CLICKHOUSE_HOST``.
    A fresh clone without an ``.env.local`` would then fail to
    connect with a confusing "connection reset" error. The default
    must be ``localhost`` to match ``.env.example`` and the
    ``docker-compose.yml`` service name.
    """
    # 同 test_from_env_defaults：必须隔离真实 .env 才能测到默认值。
    monkeypatch.setattr(os, "environ", {})  # type: ignore[attr-defined]
    cfg = ClickHouseConfig.from_env(strict=False)
    assert cfg.host == "localhost", (
        f"CLICKHOUSE_HOST default must be 'localhost' to match "
        f".env.example and docker-compose.yml; got {cfg.host!r}"
    )
    # Port + user defaults are also documented in .env.example.
    assert cfg.port == 8123
    assert cfg.user == "default"
    assert cfg.protocol == "http"
