"""Project logging helpers."""

from __future__ import annotations

import logging


class Logger:
    """Small compatibility wrapper around standard library logging."""

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
