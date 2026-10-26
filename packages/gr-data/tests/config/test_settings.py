"""数据连接模型与 DSN 行为回归。"""

from __future__ import annotations

import os

import pytest
from gr_data.config.settings import (
    ClickHouseConfig,
    HdbConfig,
    InsightConfig,
    RiceQuantConfig,
    make_pg_dsn,
)
from gr_tools.config import SettingsError


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


def test_invalid_ricequant_enabled_rejects_configuration() -> None:
    with pytest.raises(SettingsError, match="RICEQUANT_ENABLED") as error:
        RiceQuantConfig.from_env(strict=False, environ={"RICEQUANT_ENABLED": "tru"})
    assert "tru" not in str(error.value)


def test_invalid_hdb_enabled_rejects_configuration() -> None:
    with pytest.raises(SettingsError, match="ENABLE_HDB") as error:
        HdbConfig.from_env(environ={"ENABLE_HDB": "tru"})
    assert "tru" not in str(error.value)


def test_invalid_insight_enabled_rejects_configuration() -> None:
    with pytest.raises(SettingsError, match="ENABLE_INSIGHT") as error:
        InsightConfig.from_env(strict=False, environ={"ENABLE_INSIGHT": "tru"})
    assert "tru" not in str(error.value)
