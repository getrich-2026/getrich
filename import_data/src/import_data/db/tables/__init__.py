"""
ClickHouse 表操作模块

提供 ClickHouse 表的基类和具体实现。

主要类：
- MinBarTable: 分钟线数据表
- DayBarTable: 日线数据表
"""

from __future__ import annotations

from .bar import DayBarTable, MinBarTable

__all__ = [
    "MinBarTable",
    "DayBarTable",
]
