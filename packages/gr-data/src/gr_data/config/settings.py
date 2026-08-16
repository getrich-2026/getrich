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


def _is_workspace_root(path: Path) -> bool:
    """判断 ``path`` 是否是 uv workspace 根（含 ``[tool.uv.workspace]`` 的 pyproject.toml）。"""
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        return "[tool.uv.workspace]" in pyproject.read_text(encoding="utf-8")
    except OSError:
        return False


def find_project_root(start_path: Path | None = None) -> Path:
    """向上查找 workspace 根目录。

    查找顺序：

    1. ``GETRICH_ROOT`` 环境变量（显式覆盖，便于容器与 CI 固定路径）；
    2. 含 ``[tool.uv.workspace]`` 的 ``pyproject.toml`` —— **只有 workspace 根有这一段**；
    3. 退回到含 ``.git`` 的目录；
    4. 都找不到时用当前工作目录。

    第 2 条是关键：不能只找 ``pyproject.toml``，否则会先命中
    ``packages/gr-data/pyproject.toml`` 这类成员包，导致读不到根 ``.env``，
    回测 artifact 也会落到 ``packages/gr-data/tmp/artifacts``（见 DECISIONS.md D-003）。
    """
    override = os.environ.get("GETRICH_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    current = (start_path or Path(__file__)).resolve().parent
    candidates = [current, *current.parents]

    for path in candidates:
        if _is_workspace_root(path):
            return path
    for path in candidates:
        if (path / ".git").exists():
            return path

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

# --- PostgreSQL 配置 (前端业务库) ---
PG_HOST = 100.80.19.6
PG_PORT = 5432
PG_USER = quant
PG_PASSWORD = your_password_here
PG_DB = goldmine
# PG_POOL_MIN = 2
# PG_POOL_MAX = 20

# --- Web 服务配置 (FastAPI) ---
WEB_HOST = 0.0.0.0
WEB_PORT = 8000
WEB_CORS_ORIGINS = http://localhost:5173

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

    # Priority check
    if project_env_path.exists():
        logging.getLogger("settings").info(
            "Using .env from project directory: %s", project_env_path
        )
        return project_env_path

    if user_env_path.exists():
        return user_env_path

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
        # Default to localhost — matches .env.example and the
        # docker-compose.yml service name. The previous default of
        # "192.168.1.60" was a dev's personal LAN IP that leaked
        # into the committed code; a fresh clone without an
        # .env.local would then fail to connect to a non-existent
        # host with a confusing "connection reset" error.
        host = _get_env("CLICKHOUSE_HOST", "localhost")
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
class BacktestStorageConfig:
    """Backtest artifact storage Configuration.

    The artifact root is the on-disk directory that ``BacktestArtifact.uri``
    paths are allowed to resolve under. The binary download endpoint refuses
    any path that escapes this root (path-traversal protection).
    """

    artifact_dir: Path

    @classmethod
    def from_env(cls, project_root: Path, strict: bool) -> BacktestStorageConfig:
        raw = _get_env("BACKTEST_ARTIFACT_DIR", "tmp/artifacts")
        path = Path(raw) if raw else Path("tmp/artifacts")
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            _warn(f"Backtest artifact dir does not exist: {path}", strict)
        return cls(artifact_dir=path)


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
class PostgresConfig:
    """PostgreSQL Database Configuration (前端业务库)"""

    host: str
    port: int
    user: str
    password: str
    database: str
    min_size: int = 2
    max_size: int = 20

    @classmethod
    def from_env(cls, strict: bool) -> PostgresConfig:
        host = _get_env("PG_HOST", "100.80.19.6") or "100.80.19.6"
        port_str = _get_env("PG_PORT", "5432")
        user = _get_env("PG_USER", "quant") or "quant"
        password = _get_env("PG_PASSWORD", "") or ""
        database = _get_env("PG_DB", "goldmine") or "goldmine"

        if not password:
            _warn("PG_PASSWORD is not set", strict)

        try:
            port = int(port_str)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            _warn(f"Invalid PG_PORT: {port_str}", strict)
            port = 5432

        try:
            min_size = int(_get_env("PG_POOL_MIN", "2") or 2)
            max_size = int(_get_env("PG_POOL_MAX", "20") or 20)
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


@dataclass(frozen=True)
class WebConfig:
    """Web Service Configuration (FastAPI)"""

    host: str
    port: int
    cors_origins: tuple[str, ...]
    jwt_secret: str
    jwt_expire_minutes: int
    jwt_refresh_expire_hours: int
    csp_policy: str

    @classmethod
    def from_env(cls, strict: bool) -> WebConfig:
        host = _get_env("WEB_HOST", "0.0.0.0") or "0.0.0.0"
        port_str = _get_env("WEB_PORT", "8000")
        origins_str = _get_env("WEB_CORS_ORIGINS", "http://localhost:5173") or ""
        jwt_secret = (
            _get_env("JWT_SECRET", "getrich-dev-secret-change-in-prod")
            or "getrich-dev-secret-change-in-prod"
        )
        jwt_expire_str = _get_env("JWT_EXPIRE_MINUTES", "1440")  # default 24h
        jwt_refresh_expire_str = _get_env("JWT_REFRESH_EXPIRE_HOURS", "168")  # default 7d
        # Default CSP: tight, dev-friendly. Override via CSP_POLICY env to
        # deploy a stricter prod policy (e.g. drop 'unsafe-inline' once
        # the frontend is built without inline scripts/styles).
        csp_policy = (
            _get_env(
                "CSP_POLICY",
                # dev defaults: allow Vite's HMR + inline styles that the
                # shadcn/ui Tailwind layer uses; allow http://localhost/127.0.0.1
                # for the dev backend; deny framing entirely.
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' ws: wss: http://localhost:* http://127.0.0.1:*; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'",
            )
            or ""
        )

        try:
            port = int(port_str)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            _warn(f"Invalid WEB_PORT: {port_str}", strict)
            port = 8000

        try:
            jwt_expire_minutes = int(jwt_expire_str)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            jwt_expire_minutes = 1440

        try:
            jwt_refresh_expire_hours = int(jwt_refresh_expire_str)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            jwt_refresh_expire_hours = 168

        cors_origins = tuple(o.strip() for o in origins_str.split(",") if o.strip())

        return cls(
            host=host,
            port=port,
            cors_origins=cors_origins,
            jwt_secret=jwt_secret,
            jwt_expire_minutes=jwt_expire_minutes,
            jwt_refresh_expire_hours=jwt_refresh_expire_hours,
            csp_policy=csp_policy,
        )


@dataclass(frozen=True)
class WorkerConfig:
    """Backtest Worker Pool Configuration.

    P0: jobs run in-process via FastAPI BackgroundTasks
    (GETRICH_WORKER_BACKEND=inproc). P1+: jobs dispatched to a
    Celery worker pool backed by Redis
    (GETRICH_WORKER_BACKEND=celery).
    """

    backend: str  # 'inproc' or 'celery'
    broker_url: str  # Redis URL when backend=celery
    result_backend: str  # Redis URL for Celery results
    flower_url: str  # monitoring UI

    @classmethod
    def from_env(cls, strict: bool) -> WorkerConfig:
        backend = (_get_env("GETRICH_WORKER_BACKEND", "inproc") or "inproc").lower()
        if backend not in ("inproc", "celery"):
            _warn(f"Invalid GETRICH_WORKER_BACKEND={backend!r}, falling back to 'inproc'", strict)
            backend = "inproc"
        broker_url = (
            _get_env("GETRICH_BROKER_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0"
        )
        result_backend = _get_env("GETRICH_RESULT_BACKEND", broker_url) or broker_url
        flower_url = (
            _get_env("GETRICH_FLOWER_URL", "http://localhost:5555") or "http://localhost:5555"
        )
        return cls(
            backend=backend,
            broker_url=broker_url,
            result_backend=result_backend,
            flower_url=flower_url,
        )


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
    postgres: PostgresConfig
    web: WebConfig
    backtest_storage: BacktestStorageConfig
    worker: WorkerConfig

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
    pg_config = PostgresConfig.from_env(strict=strict_mode)
    web_config = WebConfig.from_env(strict=strict_mode)
    backtest_storage_config = BacktestStorageConfig.from_env(root, strict=strict_mode)
    worker_config = WorkerConfig.from_env(strict=strict_mode)

    return Settings(
        root=root,
        env=app_env or "dev",
        clickhouse=ch_config,
        duckdb=duck_config,
        logging=log_config,
        ricequant=rq_config,
        hdb=hdb_config,
        insight=insight_config,
        postgres=pg_config,
        web=web_config,
        backtest_storage=backtest_storage_config,
        worker=worker_config,
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


# ------------------------------------------------------------------------------
# 6. Helpers
# ------------------------------------------------------------------------------


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
