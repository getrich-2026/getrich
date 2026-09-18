"""API 与 worker 按角色组装配置；导入不加载环境。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from gr_data.config import PostgresConfig, load_postgres
from gr_tools.config import Environment, LoggingConfig, load_environment, warn_config


@dataclass(frozen=True)
class BacktestStorageConfig:
    """Backtest artifact storage Configuration.

    The artifact root is the on-disk directory that ``BacktestArtifact.uri``
    paths are allowed to resolve under. The binary download endpoint refuses
    any path that escapes this root (path-traversal protection).
    """

    artifact_dir: Path

    @classmethod
    def from_env(
        cls, project_root: Path, strict: bool, environ: Mapping[str, str] | None = None
    ) -> BacktestStorageConfig:
        source = os.environ if environ is None else environ
        raw = source.get("BACKTEST_ARTIFACT_DIR", "tmp/artifacts")
        path = Path(raw) if raw else Path("tmp/artifacts")
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            warn_config(f"Backtest artifact dir does not exist: {path}", strict)
        return cls(artifact_dir=path)


@dataclass(frozen=True)
class WebConfig:
    """Web Service Configuration (FastAPI)"""

    host: str
    port: int
    cors_origins: tuple[str, ...]
    jwt_secret: str = field(repr=False)
    jwt_expire_minutes: int
    jwt_refresh_expire_hours: int
    csp_policy: str

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> WebConfig:
        source = os.environ if environ is None else environ
        host = source.get("WEB_HOST", "0.0.0.0") or "0.0.0.0"
        port_str = source.get("WEB_PORT", "8000")
        origins_str = source.get("WEB_CORS_ORIGINS", "http://localhost:5173") or ""
        jwt_secret = (
            source.get("JWT_SECRET", "getrich-dev-secret-change-in-prod")
            or "getrich-dev-secret-change-in-prod"
        )
        jwt_expire_str = source.get("JWT_EXPIRE_MINUTES", "1440")  # default 24h
        jwt_refresh_expire_str = source.get("JWT_REFRESH_EXPIRE_HOURS", "168")  # default 7d
        # Default CSP: tight, dev-friendly. Override via CSP_POLICY env to
        # deploy a stricter prod policy (e.g. drop 'unsafe-inline' once
        # the frontend is built without inline scripts/styles).
        csp_policy = (
            source.get(
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
            warn_config("Invalid WEB_PORT", strict)
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
    broker_url: str = field(repr=False)
    result_backend: str = field(repr=False)
    flower_url: str = field(repr=False)

    @classmethod
    def from_env(cls, strict: bool, environ: Mapping[str, str] | None = None) -> WorkerConfig:
        source = os.environ if environ is None else environ
        backend = (source.get("GETRICH_WORKER_BACKEND", "inproc") or "inproc").lower()
        if backend not in ("inproc", "celery"):
            warn_config("Invalid GETRICH_WORKER_BACKEND; falling back to inproc", strict)
            backend = "inproc"
        broker_url = (
            source.get("GETRICH_BROKER_URL", "redis://localhost:6379/0")
            or "redis://localhost:6379/0"
        )
        result_backend = source.get("GETRICH_RESULT_BACKEND", broker_url) or broker_url
        flower_url = (
            source.get("GETRICH_FLOWER_URL", "http://localhost:5555") or "http://localhost:5555"
        )
        return cls(
            backend=backend,
            broker_url=broker_url,
            result_backend=result_backend,
            flower_url=flower_url,
        )


@dataclass(frozen=True)
class WorkerSettings:
    """后台任务运行配置，不含 Web 或供应商模型。"""

    root: Path
    logging: LoggingConfig
    postgres: PostgresConfig
    worker: WorkerConfig
    backtest_storage: BacktestStorageConfig


@dataclass(frozen=True)
class ApiSettings(WorkerSettings):
    """API 应用实例配置，供请求与后台任务显式使用。"""

    env: str
    web: WebConfig
    admin_user_ids: frozenset[str] = frozenset()
    payment_webhook_secret: str = field(default="", repr=False)

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


def load_worker_settings(environment: Environment | None = None) -> WorkerSettings:
    """从一个环境快照组装 worker 需要的模型。"""
    env = environment if environment is not None else load_environment()
    return WorkerSettings(
        root=env.root,
        logging=LoggingConfig.from_env(env.root, env.values),
        postgres=load_postgres(env),
        worker=WorkerConfig.from_env(env.strict, env.values),
        backtest_storage=BacktestStorageConfig.from_env(env.root, env.strict, env.values),
    )


def load_api_settings(environment: Environment | None = None) -> ApiSettings:
    """应用创建时加载；不缓存成跨应用全局单例。"""
    env = environment if environment is not None else load_environment()
    common = load_worker_settings(env)
    return ApiSettings(
        root=common.root,
        logging=common.logging,
        postgres=common.postgres,
        worker=common.worker,
        backtest_storage=common.backtest_storage,
        env=env.values.get("APP_ENV", "dev"),
        payment_webhook_secret=env.values.get("PAYMENT_WEBHOOK_SECRET", ""),
        web=WebConfig.from_env(env.strict, env.values),
        admin_user_ids=frozenset(
            x.strip() for x in env.values.get("GETRICH_ADMIN_USER_IDS", "").split(",") if x.strip()
        ),
    )
