"""进程日志的输出、重配与结构化上下文回归。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from gr_tools.config import LoggingConfig
from gr_tools.logging import configure_logging


@pytest.fixture
def isolated_logging(monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)
    yield root
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()


def test_packages_share_output_and_reconfigure_closes_files(tmp_path, isolated_logging):
    output = tmp_path / "custom.log"
    configure_logging(file_path=output, console=False, text_format="%(name)s:%(message)s")
    old = next(h for h in isolated_logging.handlers if isinstance(h, logging.FileHandler))
    for name in ("gr_data.ingest.example", "gr_tools.io", "gr_api.services.example"):
        logging.getLogger(name).warning("first")
    configure_logging(file_path=output, console=False, text_format="%(name)s:%(message)s")
    assert old.stream is None
    logging.getLogger("gr_data.ingest.example").warning("second")
    assert len(output.read_text().splitlines()) == 4
    assert sum(h.name == "getrich.output" for h in isolated_logging.handlers) == 1


def test_reconfigure_preserves_host_handler(tmp_path, isolated_logging):
    host = logging.NullHandler()
    isolated_logging.addHandler(host)
    host_handlers = isolated_logging.handlers[:]
    configure_logging(file_path=tmp_path / "one.log", console=False)
    configure_logging(file_path=tmp_path / "two.log", console=False)
    assert host in isolated_logging.handlers
    assert all(h in isolated_logging.handlers for h in host_handlers)
    assert sum(h.name == "getrich.output" for h in isolated_logging.handlers) == 1


def test_json_preserves_context_and_exception_without_core_override(tmp_path, isolated_logging):
    output = tmp_path / "events.json"
    configure_logging(file_path=output, json_format=True, console=False)
    try:
        raise ValueError("example failure")
    except ValueError:
        logging.getLogger("gr_data.example").exception(
            "failed",
            extra={"context": {"provider": "example", "msg": "spoof"}, "dataset": "bars"},
        )
    payload = json.loads(output.read_text())
    assert payload["msg"] == "failed"
    assert payload["provider"] == "example"
    assert payload["dataset"] == "bars"
    assert payload["request_id"] == "-"
    assert "ValueError: example failure" in payload["exc"]


def test_failed_reconfigure_preserves_output(tmp_path, isolated_logging):
    configure_logging(file_path=tmp_path / "original.log", console=False)
    handlers = isolated_logging.handlers[:]
    with pytest.raises(IsADirectoryError):
        configure_logging(file_path=tmp_path)
    assert isolated_logging.handlers == handlers


def test_env_configuration_uses_exact_file_and_validates(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_JSON", "true")
    monkeypatch.setenv("LOG_FILE", "logs/worker-custom.log")
    monkeypatch.setenv("LOG_FMT", "%(message)s")
    cfg = LoggingConfig.from_env(tmp_path)
    assert cfg.file_path == tmp_path / "logs/worker-custom.log"
    assert cfg.level == "DEBUG"
    assert cfg.json_format
    monkeypatch.setenv("LOG_LEVEL", "invalid")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        LoggingConfig.from_env(Path.cwd())
