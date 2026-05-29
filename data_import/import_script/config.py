from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "yinhe_data_fetcher" / "data"
DEFAULT_SQL_DIR = Path(__file__).resolve().parents[1] / "sql_script_sample"
DEFAULT_SCHEMA_FILES = [
    "00_schemas.sql",
    "01_ref_tables.sql",
    "02_rq_instruments.sql",
    "03_ref_instruments_view.sql",
    "04_md_tables.sql",
]


@dataclass(frozen=True)
class ImportConfig:
    database_url: str
    data_dir: Path = DEFAULT_DATA_DIR
    sql_dir: Path = DEFAULT_SQL_DIR
    provider: str = "YINHE"
    batch_rows: int = 50_000
    timezone: str = "Asia/Shanghai"
    schema_files: list[str] = field(default_factory=lambda: list(DEFAULT_SCHEMA_FILES))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ImportConfig":
        raw: dict[str, Any] = {}
        base_dir = Path.cwd()
        if path:
            p = Path(path)
            if p.exists():
                base_dir = p.resolve().parent
                raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            else:
                raise FileNotFoundError(f"config not found: {p}")

        database_url = (
            raw.get("database_url")
            or os.getenv("GETRICH_DATABASE_URL")
            or os.getenv("DATABASE_URL")
        )
        if not database_url:
            raise ValueError(
                "database_url is required. Set it in config.yaml or DATABASE_URL."
            )

        return cls(
            database_url=str(database_url),
            data_dir=_resolve_path(raw.get("data_dir", DEFAULT_DATA_DIR), base_dir),
            sql_dir=_resolve_path(raw.get("sql_dir", DEFAULT_SQL_DIR), base_dir),
            provider=str(raw.get("provider", "YINHE")),
            batch_rows=int(raw.get("batch_rows", 50_000)),
            timezone=str(raw.get("timezone", "Asia/Shanghai")),
            schema_files=list(raw.get("schema_files") or DEFAULT_SCHEMA_FILES),
        )


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
