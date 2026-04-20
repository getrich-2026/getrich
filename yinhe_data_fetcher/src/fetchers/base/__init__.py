"""Fetcher 抽象基类 (ABC).

只放 "可复用的父类框架", 不包含具体接口实现.
具体实现见 ``src/fetchers/impl/``.

继承关系:

    BaseFetcher
    ├── FullReplaceFetcher       # 全量覆盖
    └── IncrementalFetcher       # 按 last_date 增量追加
        └── KlineFetcher         # K 线抽象基类 (日线/分钟线等共享逻辑)
"""

from .base import BaseFetcher, FetchMode
from .full_replace import FullReplaceFetcher
from .incremental import IncrementalFetcher
from .kline import KlineFetcher

__all__ = [
    "BaseFetcher",
    "FetchMode",
    "FullReplaceFetcher",
    "IncrementalFetcher",
    "KlineFetcher",
]
