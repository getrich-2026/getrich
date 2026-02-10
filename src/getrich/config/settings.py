"""
Settings module for GetRich quantitative research system.

Design goals:
- Single source of truth.
- Zero external dependencies (dotenv is optional).
- Typed configs with validation.
- Singleton pattern for easy import.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Optional: Load dotenv if available
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]


# ------------------------------------------------------------------------------
# 1. Project Root Discovery
# ------------------------------------------------------------------------------


def find_project_root(
    start_path: Path | None = None, markers: tuple[str, ...] = ("pyproject.toml", ".env", ".git")
) -> Path:
    """
    Recursively search for project root based on marker files.
    Defaults to current working directory if not found (safer fallback).
    """
    current = (start_path or Path(__file__)).resolve().parent

    # Cap depth to prevent infinite loops in weird verify configurations
    for _ in range(10):
        if any((current / marker).exists() for marker in markers):
            return current
        if current.parent == current:
            break
        current = current.parent

    # Fallback to current working directory if root not explicitly found
    return Path.cwd()


def get_user_config_dir() -> Path:
    """
    获取用户配置目录路径（跨平台）。

    所有平台统一使用: ~/.config/getrich
    """
    base = Path.home() / ".config"
    return base / "getrich"


def _get_default_env_content() -> str:
    """返回默认 .env 文件内容。"""
    return """# GetRich Configuration File
# 此文件已自动创建，请根据实际需要修改配置值

# --- 应用配置 (Application Configuration) ---
APP_ENV = dev  # 'dev', 'prod', 'research'
STRICT_MODE = false

ENABLE_INSIGHT = false  # 是否启用 Insight 功能
INSIGHT_USER = your_user_here  # Insight 用户名
INSIGHT_PASSWORD = your_password_here  # Insight 密码

# --- 数据库配置 (Database Configuration) ---
ENABLE_HDB = false  # 是否启用 HDB 模块

CLICKHOUSE_HOST = localhost
CLICKHOUSE_PORT = 8123
CLICKHOUSE_USER = default
CLICKHOUSE_PASSWORD = your_password_here
CLICKHOUSE_DB = default
CLICKHOUSE_PROTOCOL = http

# --- RiceQuant 配置 ---
# RICEQUANT_ENABLED = false
# RICEQUANT_API_KEY = your_api_key_here

# --- 日志配置 (Logging Configuration) ---
# LOG_LEVEL = INFO
"""


def find_or_create_env_file() -> Path:
    """
    查找或创建 .env 配置文件。

    优先级:
    1. 用户配置目录
    2. 项目根目录（向后兼容）

    如果都不存在，则在用户配置目录创建默认配置。
    """
    # 用户配置目录
    user_config_dir = get_user_config_dir()
    user_env_path = user_config_dir / ".env"

    # 项目根目录
    project_root = find_project_root()
    project_env_path = project_root / ".env"

    # 优先级检查
    if user_env_path.exists():
        return user_env_path

    if project_env_path.exists():
        logging.getLogger("settings").info(
            "Using .env from project directory: %s\nConsider moving it to user config: %s",
            project_env_path,
            user_env_path,
        )
        return project_env_path

    # 都不存在，创建默认配置
    user_config_dir.mkdir(parents=True, exist_ok=True)

    # 从 .env.example 复制或创建默认配置
    example_path = project_root / ".env.example"
    if example_path.exists():
        import shutil

        shutil.copy(example_path, user_env_path)
    else:
        # 创建最小默认配置
        default_content = _get_default_env_content()
        user_env_path.write_text(default_content, encoding="utf-8")

    logging.getLogger("settings").warning(
        "Created default .env file at: %s\nPlease review and update the configuration values.",
        user_env_path,
    )

    return user_env_path


# ------------------------------------------------------------------------------
# 2. Helper Functions
# ------------------------------------------------------------------------------


class SettingsError(RuntimeError):
    """Configuration specific error."""


def _get_env(key: str, default: Any = None, legacy_keys: tuple[str, ...] = ()) -> str | None:
    """Helper to fetch env vars with legacy fallback support."""
    if key in os.environ:
        return os.environ[key]

    for legacy in legacy_keys:
        if legacy in os.environ:
            return os.environ[legacy]

    return str(default) if default is not None else None


def _parse_bool(value: str | None) -> bool:
    """Robust boolean parsing."""
    if not value:
        return False
    return value.lower() in ("true", "1", "yes", "on")


def _warn(msg: str, strict: bool) -> None:
    if strict:
        raise SettingsError(msg)
    # Use a specific logger to avoid polluting root logger before config
    logging.getLogger("settings").warning("[Config] %s", msg)


# ------------------------------------------------------------------------------
# 3. Configuration Classes (Dataclasses)
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClickHouseConfig:
    """ClickHouse Database Configuration"""

    host: str
    port: int
    user: str
    password: str
    database: str
    protocol: str = "http"

    @classmethod
    def from_env(cls, strict: bool) -> ClickHouseConfig:
        host = _get_env("CLICKHOUSE_HOST", "192.168.1.60")
        port_str = _get_env("CLICKHOUSE_PORT", "8123")
        user = _get_env("CLICKHOUSE_USER", "default")
        password = _get_env("CLICKHOUSE_PASSWORD", "getrich")
        database = _get_env("CLICKHOUSE_DB", "default")
        protocol = _get_env("CLICKHOUSE_PROTOCOL", "http")

        # Validation logic
        if not host:
            _warn("ClickHouse host is not set", strict)

        try:
            port = int(port_str)  # type: ignore
        except (TypeError, ValueError):
            _warn(f"Invalid ClickHouse port: {port_str}", strict)
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
    def from_env(cls, project_root: Path, strict: bool) -> DuckDBConfig:
        db_path = _get_env("DUCKDB_PATH", ":memory:")
        pq_root_str = _get_env("DUCKDB_PARQUET_ROOT")

        pq_root = None
        if pq_root_str:
            pq_path = Path(pq_root_str)
            if not pq_path.is_absolute():
                pq_path = project_root / pq_path

            if not pq_path.exists():
                _warn(f"DuckDB parquet root does not exist: {pq_path}", strict)
            pq_root = pq_path

        return cls(path=db_path or ":memory:", parquet_root=pq_root)


@dataclass(frozen=True)
class LoggingConfig:
    """Logging Configuration"""

    level: str
    format: str
    file_path: Path | None

    @classmethod
    def from_env(cls, project_root: Path) -> LoggingConfig:
        level = _get_env("LOG_LEVEL", "INFO")
        fmt = _get_env("LOG_FMT", "[%(asctime)s][%(name)s][%(levelname)s] %(message)s")
        file_str = _get_env("LOG_FILE")

        file_path = None
        if file_str:
            p = Path(file_str)
            file_path = p if p.is_absolute() else project_root / p

        return cls(level=(level or "INFO").upper(), format=fmt or "", file_path=file_path)


@dataclass(frozen=True)
class RiceQuantConfig:
    """RiceQuant Data Source Configuration"""

    enabled: bool
    api_key: str

    @classmethod
    def from_env(cls, strict: bool) -> RiceQuantConfig:
        enabled = _parse_bool(_get_env("RICEQUANT_ENABLED", "false"))
        api_key = _get_env("RICEQUANT_API_KEY", "")
        if enabled and not api_key:
            _warn("RiceQuant API key is not set", strict)

        return cls(enabled=enabled, api_key=api_key or "")


@dataclass(frozen=True)
class HdbConfig:
    """HDB Module Configuration"""

    enabled: bool

    @classmethod
    def from_env(cls) -> HdbConfig:
        enabled = _parse_bool(_get_env("ENABLE_HDB", "false"))
        return cls(enabled=enabled)


@dataclass(frozen=True)
class InsightConfig:
    """Insight Module Configuration"""

    enabled: bool
    user: str
    password: str

    @classmethod
    def from_env(cls, strict: bool) -> InsightConfig:
        enabled = _parse_bool(_get_env("ENABLE_INSIGHT", "false"))
        user = _get_env("INSIGHT_USER", "")
        password = _get_env("INSIGHT_PASSWORD", "")

        if enabled and not user:
            _warn("Insight user is not set", strict)
        if enabled and not password:
            _warn("Insight password is not set", strict)

        return cls(enabled=enabled, user=user or "", password=password or "")


@dataclass(frozen=True)
class Settings:
    """Global Settings Container"""

    root: Path
    env: str  # 'dev', 'prod', 'research'
    clickhouse: ClickHouseConfig
    duckdb: DuckDBConfig
    logging: LoggingConfig
    ricequant: RiceQuantConfig
    hdb: HdbConfig
    insight: InsightConfig

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    def to_dict(self) -> dict[str, Any]:
        """Serialize config for logging or display."""
        return asdict(self)


# ------------------------------------------------------------------------------
# 4. Initialization Logic
# ------------------------------------------------------------------------------


def load_settings(env_file: str | None = None) -> Settings:
    """
    Main entry point to load settings.
    Auto-detects or creates .env file in user config directory.
    """
    root = find_project_root()

    # Load .env file
    if load_dotenv is not None:
        target_env = Path(env_file) if env_file else find_or_create_env_file()

        if target_env.exists():
            load_dotenv(dotenv_path=target_env, override=True)

    # Determine mode
    app_env = _get_env("APP_ENV", "dev")
    # Strict mode enabled in production or CI to fail fast on bad configs
    strict_mode = _parse_bool(_get_env("STRICT_MODE", "false")) or (app_env == "prod")

    # Load sub-configs
    ch_config = ClickHouseConfig.from_env(strict=strict_mode)
    duck_config = DuckDBConfig.from_env(root, strict=strict_mode)
    log_config = LoggingConfig.from_env(root)
    rq_config = RiceQuantConfig.from_env(strict=strict_mode)
    hdb_config = HdbConfig.from_env()
    insight_config = InsightConfig.from_env(strict=strict_mode)

    return Settings(
        root=root,
        env=app_env or "dev",
        clickhouse=ch_config,
        duckdb=duck_config,
        logging=log_config,
        ricequant=rq_config,
        hdb=hdb_config,
        insight=insight_config,
    )


def setup_logging(settings: Settings) -> None:
    """
    Applies the logging configuration globally.
    Call this at the very start of your application entrypoint.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if settings.logging.file_path:
        settings.logging.file_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(settings.logging.file_path, encoding="utf-8"))

    logging.basicConfig(
        level=settings.logging.level, format=settings.logging.format, handlers=handlers, force=True
    )


# ------------------------------------------------------------------------------
# 5. Singleton Instance
# ------------------------------------------------------------------------------

# Automatic loading on import.
# This allows `from settings import settings` in other files.
# For lazy loading, you could remove this and let the user call load_settings().
settings = load_settings()
