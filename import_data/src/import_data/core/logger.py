# Logger module for import_data package
# All code & config keys in English, comments/explanations in Chinese.
from __future__ import annotations

import logging
import sys
from typing import Any


class Logger:
    """
    轻量级的标准 Python 日志包装器，用于替代原先对外部 lntools 包的依赖。
    """

    def __init__(self, module_name: str) -> None:
        """
        初始化 Logger。

        Args:
            module_name: 模块名称。
        """
        self._logger = logging.getLogger(module_name)

        # 如果当前 Logger 没有 Handler，且未配置过 root logger，则添加控制台 Handler
        if not self._logger.handlers and not logging.getLogger().handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志。"""
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """记录 INFO 级别日志。"""
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """记录 WARNING 级别日志。"""
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """记录 ERROR 级别日志。"""
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """记录 EXCEPTION 级别日志并附带堆栈。"""
        self._logger.exception(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """通用日志记录接口。"""
        self._logger.log(level, msg, *args, **kwargs)
