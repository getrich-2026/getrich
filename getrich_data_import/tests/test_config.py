from __future__ import annotations

from pathlib import Path

from getrich_data_import.common.config import Settings


def test_settings_loads_external_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
database_url = "postgresql+psycopg://u:p@localhost:5432/getrich"
provider = "yinhe"
batch_rows = 123

[yinhe]
data_dir = "./raw"

[parquet]
export_dir = "./pq"
""",
        encoding="utf-8",
    )

    settings = Settings.load(cfg)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.batch_rows == 123
    assert settings.yinhe.data_dir == tmp_path / "raw"
    assert settings.parquet.export_dir == tmp_path / "pq"


def test_default_yinhe_data_dir_is_data_root() -> None:
    settings = Settings.load()

    assert settings.yinhe.data_dir == Path("/data")


def test_insight_symbols_accept_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("GETRICH_IMPORT__INSIGHT_SYMBOLS", "000300.XSHG, IF2406.CCFX")

    settings = Settings.load()

    assert settings.insight.symbols == ("000300.XSHG", "IF2406.CCFX")


def test_insight_runtime_paths_accept_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("GETRICH_IMPORT__INSIGHT_RUNTIME_PATHS", "/a,/b")

    settings = Settings.load()

    assert settings.insight.runtime_paths == (Path("/a"), Path("/b"))


def test_quality_expected_minutes_accepts_env(monkeypatch) -> None:
    monkeypatch.setenv("GETRICH_IMPORT__QUALITY_EXPECTED_MINUTES_PER_DAY", "240")

    settings = Settings.load()

    assert settings.quality.expected_minutes_per_day == 240
