from __future__ import annotations

from pathlib import Path

from getrich_data_import.adapters.insight import InsightSource
from getrich_data_import.adapters.registry import get_history_source
from getrich_data_import.adapters.yinhe_parquet import YinheParquetSource
from getrich_data_import.common.config import Settings


def test_registry_builds_yinhe_source(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
database_url = "postgresql+psycopg://u:p@localhost:5432/getrich"
[yinhe]
data_dir = "{raw}"
""",
        encoding="utf-8",
    )
    settings = Settings.load(cfg)

    source = get_history_source("yinhe", settings)

    assert isinstance(source, YinheParquetSource)
    assert source.provider == "yinhe"


def test_registry_builds_insight_without_importing_sdk() -> None:
    settings = Settings.load()

    source = get_history_source("insight", settings)

    assert isinstance(source, InsightSource)
    assert source.provider == "insight"
