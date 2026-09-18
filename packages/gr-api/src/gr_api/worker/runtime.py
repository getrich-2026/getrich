"""运行中的 Celery 应用配置访问；导入本模块不加载环境。"""

from __future__ import annotations

from celery import current_app
from gr_api.config import WorkerSettings, load_worker_settings


def get_worker_settings() -> WorkerSettings:
    """复用当前 Celery 应用快照；显式独立运行任务时按需初始化。"""
    config = getattr(current_app, "getrich_settings", None)
    if config is None:
        config = load_worker_settings()
        current_app.getrich_settings = config
    return config
