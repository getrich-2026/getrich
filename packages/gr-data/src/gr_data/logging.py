"""历史日志调用兼容入口。新模块直接使用 logging.getLogger(__name__)。"""

from __future__ import annotations

import logging
from pathlib import Path

from gr_tools.logging import configure_logging as _configure_logging


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: str | Path | None = None,
    json_format: bool = False,
    console: bool = True,
    filename: str = "gr_data.log",
) -> None:
    """兼容旧签名；新入口使用 gr_tools.config.setup_logging。"""
    _configure_logging(
        level,
        file_path=Path(log_dir) / filename if log_dir is not None else None,
        json_format=json_format,
        console=console,
    )


def get_logger(name: str) -> logging.Logger:
    """兼容旧名称规则，仅获取 logger，不配置输出。"""
    return logging.getLogger(name if "." in name else f"gr_data.{name}")


class Logger:
    """标准库 logging 的薄封装。

    保留这个类是为了兼容 ClickHouse 客户端里既有的 ``Logger(module_name=...)``
    调用点；新代码一律用 ``get_logger(__name__)``。

    这里直接用 ``logging.getLogger``，**不走** :func:`get_logger` —— 调用方传的是
    类名（如 ``"ClickHouseConnectionPool"``），是有意作为 logger 名字的，不能被
    加上 ``gr_data.`` 前缀。
    """

    def __init__(self, module_name: str) -> None:
        self._logger = logging.getLogger(module_name)

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)
