"""日志配置."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(level: str = "INFO", file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("yinhe_data_fetcher")
    logger.setLevel(level.upper())
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if file:
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    base = logging.getLogger("yinhe_data_fetcher")
    if name:
        return base.getChild(name)
    return base
