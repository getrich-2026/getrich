# 版本信息
__version__ = "0.1.1"
__author__ = "GetRich Team"

# 导出主要子模块
from . import apps, libs

# 常用功能快捷入口 (Shortcuts)
# 允许用户直接从顶层导入核心类，如: from getrich import ClickHouseClient
# from .libs.clickhouse import ClickHouseClient, ClickHouseConnectionPool

__all__ = [
    "apps",
    "libs",
    # "ClickHouseClient",
    # "ClickHouseConnectionPool",
]
