"""
配置模块入口。
提供全局配置单例 settings 及其相关的初始化函数。
"""

from .settings import (
    ClickHouseConfig,
    DuckDBConfig,
    LoggingConfig,
    Settings,
    load_settings,
    settings,
    setup_logging,
)

__all__ = [
    "settings",
    "load_settings",
    "setup_logging",
    "Settings",
    "ClickHouseConfig",
    "DuckDBConfig",
    "LoggingConfig",
]
