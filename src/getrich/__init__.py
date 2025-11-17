# 版本信息
__version__ = "0.1.1"
__author__ = "GetRich Team"

# 从子模块导入常用类，方便用户使用

from .data.clickhouse.database import ClickHouseClient, DEFAULT_DB_CONFIG
from .data.clickhouse.pool import ClickHouseConnectionPool
from .data.clickhouse.jobs import DataImportJob
from .data.clickhouse.table import CodeInfoTable, MinBarTable, DayBarTable

__all__ = [
    'ClickHouseClient',
    'DEFAULT_DB_CONFIG',
    'ClickHouseConnectionPool',
    'DataImportJob',
    'CodeInfoTable',
    'MinBarTable',
    'DayBarTable',
]
