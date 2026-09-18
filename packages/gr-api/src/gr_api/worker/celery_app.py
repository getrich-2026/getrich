"""Celery 命令行入口；应用实例持有本进程的配置。"""

from __future__ import annotations

from pathlib import Path

from celery.signals import setup_logging as celery_setup_logging
from gr_api.config import load_worker_settings
from gr_api.worker.factory import make_celery_app
from gr_api.worker.runtime import get_worker_settings
from gr_tools.config import setup_logging


@celery_setup_logging.connect
def configure_worker_logging(
    loglevel: int | None = None, logfile: str | None = None, **kwargs: object
) -> None:
    """exec 后的新进程初始化输出，保留命令行覆盖。"""
    setup_logging(
        get_worker_settings().logging, level=loglevel, file_path=Path(logfile) if logfile else None
    )


app = make_celery_app(load_worker_settings())
