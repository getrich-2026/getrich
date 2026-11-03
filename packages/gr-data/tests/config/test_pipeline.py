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


def test_raw_root_missing_raises_instead_of_falling_back(tmp_path):
    """环境变量与本机 config.yaml 都没配置时直接报错，不退回任何默认目录（D-028）。"""
    import pytest
    from gr_data.config.pipeline import Config
    from gr_tools.config import Environment, SettingsError

    config = Config({}, Environment(root=tmp_path, values={}))

    with pytest.raises(SettingsError, match="RAW_PARQUET_ROOT"):
        _ = config.raw_root


def test_raw_root_uses_local_config_yaml_when_env_unset(tmp_path):
    from gr_data.config.pipeline import Config
    from gr_tools.config import Environment

    config = Config({"paths": {"raw_root": " /tmp/local-raw "}}, Environment(tmp_path, {}))

    assert str(config.raw_root) == "/tmp/local-raw"


def test_packaged_example_config_provides_no_raw_root(tmp_path):
    """随包发布的 config.example.yaml 不能再提供可用的机器路径。"""
    from pathlib import Path

    import pytest
    from gr_tools.config import Environment, SettingsError

    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    config = load_config(example, environment=Environment(root=tmp_path, values={}))

    with pytest.raises(SettingsError):
        _ = config.raw_root
