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
    load_dotenv = None


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


def _warn(msg: str, strict: bool):
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
        host = _get_env("CLICKHOUSE_HOST", "127.0.0.1")
        port_str = _get_env("CLICKHOUSE_PORT", "8123")
        user = _get_env("CLICKHOUSE_USER", "default")
        password = _get_env("CLICKHOUSE_PASSWORD", "")
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
class Settings:
    """Global Settings Container"""

    root: Path
    env: str  # 'dev', 'prod', 'research'
    clickhouse: ClickHouseConfig
    duckdb: DuckDBConfig
    logging: LoggingConfig

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
    Auto-detects project root and loads .env file.
    """
    root = find_project_root()

    # Load .env file
    if load_dotenv:
        target_env = Path(env_file) if env_file else root / ".env"
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

    return Settings(
        root=root,
        env=app_env or "dev",
        clickhouse=ch_config,
        duckdb=duck_config,
        logging=log_config,
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
