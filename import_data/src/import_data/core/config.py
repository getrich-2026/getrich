# Configuration module for import_data package
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


# ------------------------------------------------------------------------------
# 1. Compatibility Dataclasses
# ------------------------------------------------------------------------------


class DatabaseSettings:
    """PostgreSQL Ingestion Database Settings"""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        name: str,
        url: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.name = name
        self.url = url or f"postgresql://{user}:{password}@{host}:{port}/{name}"


class ClickHouseConfig:
    """ClickHouse Database Configuration"""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        protocol: str = "http",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.protocol = protocol


class PostgresConfig:
    """PostgreSQL Database Configuration (Frontend compatible)"""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        min_size: int = 2,
        max_size: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_size = min_size
        self.max_size = max_size


class RiceQuantConfig:
    """RiceQuant Data Source Configuration"""

    def __init__(self, enabled: bool, api_key: str) -> None:
        self.enabled = enabled
        self.api_key = api_key


class HdbConfig:
    """HDB Module Configuration"""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled


class RedisConfig:
    """Redis Configuration"""

    def __init__(self, host: str, port: int, db: int, password: str) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.password = password


class InsightConfig:
    """Insight SDK Configuration"""

    def __init__(
        self,
        enabled: bool,
        account: str,
        password: str,
        server: str,
        default_symbols: list,
    ) -> None:
        self.enabled = enabled
        self.account = account
        self.password = password
        self.server = server
        self.default_symbols = default_symbols


# ------------------------------------------------------------------------------
# 2. Main Pydantic Settings
# ------------------------------------------------------------------------------


# Discover the root .env file by scanning upwards
def _find_env_file() -> Path:
    current_dir = Path(__file__).resolve().parent
    for parent in [current_dir] + list(current_dir.parents):
        env_path = parent / ".env"
        if env_path.exists():
            return env_path
    # Fallback to absolute project parent
    return Path("/home/quant/project/getrich-database/.env")


class Settings(BaseSettings):
    """Unified Settings loaded from .env and config.yaml"""

    # Pydantic Settings configuration
    model_config = SettingsConfigDict(env_file=str(_find_env_file()), extra="ignore")

    # Core Database Settings (Prefix DB_)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "quant"
    db_password: str = "zedbi4-revSat-nepqik"
    db_name: str = "getrich"
    db_url: Optional[str] = None

    # ClickHouse Settings (Prefix CLICKHOUSE_)
    clickhouse_host: str = "192.168.1.60"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = "getrich"
    clickhouse_db: str = "default"
    clickhouse_protocol: str = "http"

    # RiceQuant Settings (Prefix RICEQUANT_)
    ricequant_enabled: bool = False
    ricequant_api_key: str = ""

    # HDB Settings (Prefix ENABLE_HDB / HDB_)
    enable_hdb: bool = False

    # Redis Settings (Prefix REDIS_)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # Insight SDK Settings (Prefix INSIGHT_)
    insight_enabled: bool = False
    insight_account: str = ""
    insight_password: str = ""
    insight_server: str = ""
    insight_default_symbols: list = []

    # PostgreSQL/PG Settings (Compatibility with getrich frontend db settings)
    pg_host: str = "100.80.19.6"
    pg_port: int = 5432
    pg_user: str = "quant"
    pg_password: str = "zedbi4-revSat-nepqik"
    pg_db: str = "getrich"
    pg_pool_min: int = 2
    pg_pool_max: int = 20

    # Runtime Switches (from config.yaml)
    fetcher_enabled: Dict[str, bool] = {}

    @property
    def db(self) -> DatabaseSettings:
        """获取 ingestion 数据库配置"""
        return DatabaseSettings(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_password,
            name=self.db_name,
            url=self.db_url,
        )

    @property
    def clickhouse(self) -> ClickHouseConfig:
        """获取 ClickHouse 数据库配置"""
        return ClickHouseConfig(
            host=self.clickhouse_host,
            port=self.clickhouse_port,
            user=self.clickhouse_user,
            password=self.clickhouse_password,
            database=self.clickhouse_db,
            protocol=self.clickhouse_protocol,
        )

    @property
    def postgres(self) -> PostgresConfig:
        """获取 PostgreSQL 数据库配置（兼容 getrich 前端）"""
        return PostgresConfig(
            host=self.pg_host,
            port=self.pg_port,
            user=self.pg_user,
            password=self.pg_password,
            database=self.pg_db,
            min_size=self.pg_pool_min,
            max_size=self.pg_pool_max,
        )

    @property
    def ricequant(self) -> RiceQuantConfig:
        """获取 RiceQuant 接口配置"""
        return RiceQuantConfig(
            enabled=self.ricequant_enabled, api_key=self.ricequant_api_key
        )

    @property
    def hdb(self) -> HdbConfig:
        """获取 HDB 接口配置"""
        return HdbConfig(enabled=self.enable_hdb)

    @property
    def redis(self) -> RedisConfig:
        """获取 Redis 配置"""
        return RedisConfig(
            host=self.redis_host,
            port=self.redis_port,
            db=self.redis_db,
            password=self.redis_password,
        )

    @property
    def insight(self) -> InsightConfig:
        """获取 Insight SDK 配置"""
        return InsightConfig(
            enabled=self.insight_enabled,
            account=self.insight_account,
            password=self.insight_password,
            server=self.insight_server,
            default_symbols=self.insight_default_symbols,
        )

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path = "config.yaml") -> Settings:
        """从 yaml 加载并合并环境变量配置"""
        path = Path(yaml_path)
        # 寻找正确的 config.yaml 路径（如果是从 import_data 内部运行）
        if not path.exists():
            import_data_root = Path(__file__).resolve().parents[3] / "import_data"
            if (import_data_root / yaml_path).exists():
                path = import_data_root / yaml_path

        yaml_data = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        return cls(**yaml_data)


# 全局单例
settings = Settings.load_from_yaml()
