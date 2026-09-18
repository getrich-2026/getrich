"""数据层配置模型；导入不加载环境文件或创建全量单例。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from gr_tools.config import (
    Environment,
    find_project_root as find_project_root,
    parse_bool,
    warn_config,
)


@dataclass(frozen=True)
class ClickHouseConfig:
    """ClickHouse Database Configuration"""

    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    protocol: str = "http"

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> ClickHouseConfig:
        source = os.environ if environ is None else environ
        # Default to localhost — matches .env.example and the
        # docker-compose.yml service name. The previous default of
        # "192.168.1.60" was a dev's personal LAN IP that leaked
        # into the committed code; a fresh clone without an
        # .env.local would then fail to connect to a non-existent
        # host with a confusing "connection reset" error.
        host = source.get("CLICKHOUSE_HOST", "localhost")
        port_str = source.get("CLICKHOUSE_PORT", "8123")
        user = source.get("CLICKHOUSE_USER", "default")
        password = source.get("CLICKHOUSE_PASSWORD", "getrich")
        database = source.get("CLICKHOUSE_DB", "default")
        protocol = source.get("CLICKHOUSE_PROTOCOL", "http")

        # Validation logic
        if not host:
            warn_config("ClickHouse host is not set", strict)

        try:
            port = int(port_str)  # type: ignore
        except (TypeError, ValueError):
            warn_config("Invalid CLICKHOUSE_PORT", strict)
            port = 8123

        return cls(
            host=host or "",
            port=port,
            user=user or "",
            password=password or "",
            database=database or "",
            protocol=protocol or "http",
        )


@dataclass(frozen=True)
class DuckDBConfig:
    """DuckDB Configuration"""

    path: str
    parquet_root: Path | None

    @classmethod
    def from_env(
        cls, project_root: Path, strict: bool, environ: Mapping[str, str] | None = None
    ) -> DuckDBConfig:
        source = os.environ if environ is None else environ
        db_path = source.get("DUCKDB_PATH", ":memory:")
        pq_root_str = source.get("DUCKDB_PARQUET_ROOT")

        pq_root = None
        if pq_root_str:
            pq_path = Path(pq_root_str)
            if not pq_path.is_absolute():
                pq_path = project_root / pq_path

            if not pq_path.exists():
                warn_config(f"DuckDB parquet root does not exist: {pq_path}", strict)
            pq_root = pq_path

        return cls(path=db_path or ":memory:", parquet_root=pq_root)


@dataclass(frozen=True)
class RiceQuantConfig:
    """RiceQuant Data Source Configuration"""

    enabled: bool
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> RiceQuantConfig:
        source = os.environ if environ is None else environ
        enabled = parse_bool(source.get("RICEQUANT_ENABLED", "false"))
        api_key = source.get("RICEQUANT_API_KEY", "")
        if enabled and not api_key:
            warn_config("RiceQuant API key is not set", strict)

        return cls(enabled=enabled, api_key=api_key or "")


@dataclass(frozen=True)
class HdbConfig:
    """HDB Module Configuration"""

    enabled: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> HdbConfig:
        source = os.environ if environ is None else environ
        enabled = parse_bool(source.get("ENABLE_HDB", "false"))
        return cls(enabled=enabled)


@dataclass(frozen=True)
class InsightConfig:
    """Insight Module Configuration"""

    enabled: bool
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> InsightConfig:
        source = os.environ if environ is None else environ
        enabled = parse_bool(source.get("ENABLE_INSIGHT", "false"))
        user = source.get("INSIGHT_USER", "")
        password = source.get("INSIGHT_PASSWORD", "")

        if enabled and not user:
            warn_config("Insight user is not set", strict)
        if enabled and not password:
            warn_config("Insight password is not set", strict)

        return cls(enabled=enabled, user=user or "", password=password or "")


@dataclass(frozen=True)
class PostgresConfig:
    """PostgreSQL Database Configuration (前端业务库)"""

    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    min_size: int = 2
    max_size: int = 20

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> PostgresConfig:
        source = os.environ if environ is None else environ
        # 默认值必须是「本机可用」的中性值，与 .env.example 对齐。
        # 这里原先写死的是某台机器的内网 IP（100.80.19.6）和库名 goldmine，
        # 新克隆在没有 .env 时会去连别人的主机，报一个和真实原因无关的
        # 连接错误。同类问题见 ClickHouseConfig 的 host 默认值。
        host = source.get("PG_HOST", "localhost") or "localhost"
        port_str = source.get("PG_PORT", "5432")
        user = source.get("PG_USER", "quant") or "quant"
        password = source.get("PG_PASSWORD", "") or ""
        database = source.get("PG_DB", "getrich") or "getrich"

        if not password:
            warn_config("PG_PASSWORD is not set", strict)

        try:
            port = int(port_str)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            warn_config("Invalid PG_PORT", strict)
            port = 5432

        try:
            min_size = int(source.get("PG_POOL_MIN", "2") or 2)
            max_size = int(source.get("PG_POOL_MAX", "20") or 20)
        except (TypeError, ValueError):
            min_size, max_size = 2, 20

        return cls(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            min_size=min_size,
            max_size=max_size,
        )


def load_postgres(environment: Environment) -> PostgresConfig:
    """仅在使用 PostgreSQL 时解析并校验其配置。"""
    return PostgresConfig.from_env(environment.strict, environment.values)


def load_clickhouse(environment: Environment) -> ClickHouseConfig:
    """仅在使用 ClickHouse 时解析并校验其配置。"""
    return ClickHouseConfig.from_env(environment.strict, environment.values)


def make_pg_dsn(postgres: PostgresConfig) -> str:
    """Build a libpq DSN string for synchronous psycopg connections.

    Used by the worker pool's ``sync_is_cancelled_status`` probe, which
    runs in a thread / worker process and needs a short-lived sync
    connection rather than the async pool that ``PgBacktestJobStore``
    borrows from. Mirrors the async pool's connection parameters so a
    probe on a different connection observes the same writes.

    Parameters
    ----------
    postgres : PostgresConfig
        The application's Postgres config dataclass.

    Returns
    -------
    str
        A libpq-style DSN, e.g.
        ``postgresql://quant:s3cr3t@100.80.19.6:5432/goldmine``.
    """
    password = f":{postgres.password}" if postgres.password else ""
    user = postgres.user or "postgres"
    return f"postgresql://{user}{password}@{postgres.host}:{postgres.port}/{postgres.database}"
