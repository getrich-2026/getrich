"""Fetcher 模块.

目录:
    base/   抽象基类 (BaseFetcher / FullReplaceFetcher / IncrementalFetcher / KlineFetcher)
    impl/   具体数据源实现 (一个文件一个 class)
"""

from .base import (
    BaseFetcher,
    FetchMode,
    FullReplaceFetcher,
    IncrementalFetcher,
    KlineFetcher,
)

__all__ = [
    "BaseFetcher",
    "FetchMode",
    "FullReplaceFetcher",
    "IncrementalFetcher",
    "KlineFetcher",
]
