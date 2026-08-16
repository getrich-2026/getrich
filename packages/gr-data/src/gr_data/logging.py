"""结构化日志。

全项目统一入口：`get_logger(name)`。禁止使用 print 做运行日志（见 CLAUDE.md 铁律）。
日志同时可写控制台与文件；支持人读文本或 JSON 行两种格式。

通过 ``configure_logging(...)`` 在程序入口配置一次，之后各模块用
``get_logger(__name__)`` 获取 logger。未显式配置时使用安全默认值（INFO+控制台）。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any


_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """单行 JSON 格式，便于日志采集。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # 附加结构化字段（logger.info("...", extra={"context": {...}})）
        ctx = getattr(record, "context", None)
        if isinstance(ctx, dict):
            payload.update(ctx)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_TEXT_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str | Path | None = None,
    json_format: bool = False,
    console: bool = True,
    filename: str = "gr_data.log",
) -> None:
    """配置根 logger。多次调用以最后一次为准。"""
    global _CONFIGURED
    root = logging.getLogger("gr_data")
    root.handlers.clear()
    root.setLevel(level.upper())
    root.propagate = False

    formatter: logging.Formatter = _JsonFormatter() if json_format else logging.Formatter(_TEXT_FMT)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    if log_dir is not None:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(d / filename, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取 logger。未配置时给安全默认值。

    传 ``__name__``（含点的模块路径）时原样使用；传 ``"cli"`` 这类裸名字时
    补上 ``gr_data.`` 前缀。本模块被 gr-backtest / gr-api / gr-signal 共用，
    所以不能无条件把别的包的 logger 名塞进 ``gr_data.`` 命名空间。
    """
    if not _CONFIGURED:
        configure_logging()
    if "." not in name:
        name = f"gr_data.{name}"
    return logging.getLogger(name)


class Logger:
    """标准库 logging 的薄封装。

    保留这个类是为了兼容 ClickHouse 客户端里既有的 ``Logger(module_name=...)``
    调用点；新代码一律用 ``get_logger(__name__)``。

    这里直接用 ``logging.getLogger``，**不走** :func:`get_logger` —— 调用方传的是
    类名（如 ``"ClickHouseConnectionPool"``），是有意作为 logger 名字的，不能被
    加上 ``gr_data.`` 前缀。
    """

    def __init__(self, module_name: str) -> None:
        if not _CONFIGURED:
            configure_logging()
        self._logger = logging.getLogger(module_name)

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)
