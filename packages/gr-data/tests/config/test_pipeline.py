"""YAML、日志与数据连接共享显式环境快照。"""

from __future__ import annotations

from gr_data.cli import _pg
from gr_data.config.pipeline import load_config
from gr_tools.config import load_environment


def test_pipeline_interpolation_and_database_use_same_snapshot(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "PG_HOST=chosen-db\nPG_PASSWORD=fixture-secret\n"
        "RAW_PARQUET_ROOT=/tmp/chosen-raw\nTOKEN=fixture-token\n"
        "CLICKHOUSE_PORT=bad\nSTRICT_MODE=true\nGR_DATA_STATEMENT_TIMEOUT_MS=2345\n"
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "providers:\n  demo:\n    token_env: TOKEN\n    host: ${PG_HOST}\n"
        "paths:\n  raw_root: /tmp/ignored\n"
    )
    env = load_environment(root=tmp_path, environ={})
    monkeypatch.setenv("PG_HOST", "different-db")
    config = load_config(config_file, environment=env)
    assert config.get("providers", "demo", "host") == "chosen-db"
    assert config.get("providers", "demo", "token") == "fixture-token"
    assert str(config.raw_root) == "/tmp/chosen-raw"
    assert _pg(config).host == "chosen-db"
    assert _pg(config).statement_timeout_ms == 2345
    assert "fixture-secret" not in repr(config)
    assert "fixture-token" not in repr(config)
