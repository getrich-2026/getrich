"""日志入口配置回归测试。"""

from __future__ import annotations

import logging


def test_settings_adapter_respects_exact_filename_and_format(tmp_path, monkeypatch) -> None:
    """回归 gr-data CLI 忽略 LOG_FILE basename 与 LOG_FMT 的问题。"""
    from types import SimpleNamespace

    from gr_tools.config import LoggingConfig, setup_logging

    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)
    path = tmp_path / "chosen.log"
    cfg = SimpleNamespace(logging=LoggingConfig(format="%(message)s", file_path=path))
    try:
        setup_logging(cfg.logging)
        logging.getLogger("gr_data.example").warning("exact-output")
        assert path.read_text().strip() == "exact-output"
        assert not (tmp_path / "gr_data.log").exists()
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
