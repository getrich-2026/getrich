"""具体 fetcher 实现 - 每个文件一个 class.

要新增一个数据源:
    1. 在本目录下新建 xxx.py, 继承 FullReplaceFetcher / IncrementalFetcher / KlineFetcher
    2. 在本 __init__.py 里 import 进来
    3. 在 src/registry.py 的 REGISTRY_CLASSES 列表里追加
    4. 在 config.yaml 的 fetchers 节点下加开关
"""

from .backward_factor import BackwardFactorFetcher
from .calendar import CalendarFetcher
from .hist_code_list import HistCodeListFetcher
from .kline_day import KlineDayFetcher
from .kline_min1 import KlineMin1Fetcher
from .kline_min5 import KlineMin5Fetcher

__all__ = [
    "CalendarFetcher",
    "HistCodeListFetcher",
    "BackwardFactorFetcher",
    "KlineDayFetcher",
    "KlineMin5Fetcher",
    "KlineMin1Fetcher",
]
