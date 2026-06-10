from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "defaults.toml"
DEFAULT_EXAMPLE_CONFIG_PATH = CONFIG_DIR / "defaults.example.toml"


@dataclass(frozen=True)
class YinheSettings:
    data_dir: Path


@dataclass(frozen=True)
class InsightSettings:
    runtime_paths: tuple[Path, ...] = ()
    env_file: Path | None = None
    staging_dir: Path = Path("~/data/insight")
    username_env: str = "INSIGHT_USER"
    password_env: str = "INSIGHT_PASSWORD"
    login_required: bool = True
    batch_size: int = 300
    default_start_date: date | None = None
    default_end_date: date | None = None
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParquetSettings:
    export_dir: Path


@dataclass(frozen=True)
class QualitySettings:
    fail_on_error: bool = True
    price_jump_warn_pct: float = 0.2
    expected_minutes_per_day: int | None = None


@dataclass(frozen=True)
class Settings:
    database_url: str
    provider: str
    timezone: str
    batch_rows: int
    yinhe: YinheSettings
    insight: InsightSettings
    parquet: ParquetSettings
    quality: QualitySettings
    sql_dir: Path

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Settings":
        paths = [_default_config_path()]
        if config_path:
            paths.append(Path(config_path).expanduser())

        raw: dict[str, Any] = {}
        base_dir = DEFAULT_CONFIG_PATH.parent
        for path in paths:
            if not path.exists():
                if path == DEFAULT_CONFIG_PATH:
                    continue
                raise FileNotFoundError(f"config not found: {path}")
            base_dir = path.resolve().parent
            raw = _deep_merge(raw, tomllib.loads(path.read_text(encoding="utf-8")))

        raw = _apply_env(raw)
        project_dir = Path(__file__).resolve().parents[3]
        sql_dir = project_dir / "sql" / "init" / "backend"

        database_url = str(raw.get("database_url") or "")
        if not database_url:
            raise ValueError("database_url is required")

        yinhe_raw = raw.get("yinhe") or {}
        insight_raw = raw.get("insight") or {}
        parquet_raw = raw.get("parquet") or {}
        quality_raw = raw.get("quality") or {}
        runtime_paths = _parse_paths(
            insight_raw.get("runtime_paths", insight_raw.get("runtime_path", [])),
            base_dir,
        )
        env_file = str(insight_raw.get("env_file") or "").strip()

        return cls(
            database_url=database_url,
            provider=str(raw.get("provider", "yinhe")).lower(),
            timezone=str(raw.get("timezone", "Asia/Shanghai")),
            batch_rows=int(raw.get("batch_rows", 50_000)),
            yinhe=YinheSettings(
                data_dir=_resolve_path(
                    yinhe_raw.get("data_dir", "../yinhe_data_fetcher/data"), base_dir
                ),
            ),
            insight=InsightSettings(
                runtime_paths=runtime_paths,
                env_file=_resolve_path(env_file, base_dir) if env_file else None,
                staging_dir=_resolve_path(
                    insight_raw.get("staging_dir", "~/data/insight"), base_dir
                ),
                username_env=str(insight_raw.get("username_env", "INSIGHT_USER")),
                password_env=str(insight_raw.get("password_env", "INSIGHT_PASSWORD")),
                login_required=bool(insight_raw.get("login_required", True)),
                batch_size=int(insight_raw.get("batch_size", 300)),
                default_start_date=_parse_optional_date(
                    insight_raw.get("default_start_date")
                ),
                default_end_date=_parse_optional_date(
                    insight_raw.get("default_end_date")
                ),
                symbols=_parse_symbols(insight_raw.get("symbols", [])),
            ),
            parquet=ParquetSettings(
                export_dir=_resolve_path(
                    parquet_raw.get("export_dir", "/data/parquet/getrich"), base_dir
                ),
            ),
            quality=QualitySettings(
                fail_on_error=bool(quality_raw.get("fail_on_error", True)),
                price_jump_warn_pct=float(quality_raw.get("price_jump_warn_pct", 0.2)),
                expected_minutes_per_day=_parse_optional_int(
                    quality_raw.get("expected_minutes_per_day")
                ),
            ),
            sql_dir=sql_dir,
        )


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _default_config_path() -> Path:
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return DEFAULT_EXAMPLE_CONFIG_PATH


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    mappings = {
        "GETRICH_IMPORT__DATABASE_URL": ("database_url",),
        "GETRICH_IMPORT__PROVIDER": ("provider",),
        "GETRICH_IMPORT__TIMEZONE": ("timezone",),
        "GETRICH_IMPORT__BATCH_ROWS": ("batch_rows",),
        "GETRICH_IMPORT__YINHE_DATA_DIR": ("yinhe", "data_dir"),
        "GETRICH_IMPORT__INSIGHT_RUNTIME_PATH": ("insight", "runtime_path"),
        "GETRICH_IMPORT__INSIGHT_RUNTIME_PATHS": ("insight", "runtime_paths"),
        "GETRICH_IMPORT__INSIGHT_ENV_FILE": ("insight", "env_file"),
        "GETRICH_IMPORT__INSIGHT_STAGING_DIR": ("insight", "staging_dir"),
        "GETRICH_IMPORT__INSIGHT_USERNAME_ENV": ("insight", "username_env"),
        "GETRICH_IMPORT__INSIGHT_PASSWORD_ENV": ("insight", "password_env"),
        "GETRICH_IMPORT__INSIGHT_LOGIN_REQUIRED": ("insight", "login_required"),
        "GETRICH_IMPORT__INSIGHT_BATCH_SIZE": ("insight", "batch_size"),
        "GETRICH_IMPORT__INSIGHT_DEFAULT_START_DATE": ("insight", "default_start_date"),
        "GETRICH_IMPORT__INSIGHT_DEFAULT_END_DATE": ("insight", "default_end_date"),
        "GETRICH_IMPORT__INSIGHT_SYMBOLS": ("insight", "symbols"),
        "GETRICH_IMPORT__PARQUET_EXPORT_DIR": ("parquet", "export_dir"),
        "GETRICH_IMPORT__QUALITY_FAIL_ON_ERROR": ("quality", "fail_on_error"),
        "GETRICH_IMPORT__QUALITY_PRICE_JUMP_WARN_PCT": (
            "quality",
            "price_jump_warn_pct",
        ),
        "GETRICH_IMPORT__QUALITY_EXPECTED_MINUTES_PER_DAY": (
            "quality",
            "expected_minutes_per_day",
        ),
    }
    for env_name, path in mappings.items():
        if env_name not in os.environ:
            continue
        cursor = out
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce_env(os.environ[env_name])
    return out


def _coerce_env(value: str) -> object:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _parse_optional_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_symbols(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)  # type: ignore[arg-type]
    return tuple(str(part).strip() for part in parts if str(part).strip())


def _parse_paths(value: object, base_dir: Path) -> tuple[Path, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        parts = value.split(",") if "," in value else [value]
    else:
        parts = list(value)  # type: ignore[arg-type]
    return tuple(
        _resolve_path(str(part).strip(), base_dir)
        for part in parts
        if str(part).strip()
    )
