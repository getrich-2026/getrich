"""
RiceQuant 认证模块
从 settings 读取配置并初始化 rqdatac 连接
"""

from __future__ import annotations

import logging

import rqdatac as rq

from getrich.config.settings import settings

logger = logging.getLogger(__name__)


def init_rq() -> None:
    """
    初始化 RiceQuant 连接

    Raises:
        RuntimeError: 当 RiceQuant 未启用或 API Key 未配置时
        Exception: rq.init() 连接失败时
    """
    if not settings.ricequant.enabled:
        raise RuntimeError("RiceQuant is disabled in settings (RICEQUANT_ENABLED=false)")

    api_key = settings.ricequant.api_key
    if not api_key:
        raise RuntimeError("RiceQuant API key is not configured (RICEQUANT_API_KEY is empty)")

    try:
        rq.init(api_key)
        logger.info("RiceQuant connection initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize RiceQuant: %s", e)
        raise
