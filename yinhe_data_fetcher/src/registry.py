"""Fetcher 注册表.

把 src/fetchers/impl/ 下的具体类登记到这里. registry 的 key 就是每个
类的 ``NAME`` 常量 - 同时也是 data/ 子目录名 + config.yaml 里的开关 key,
三者完全一致.

新增 fetcher:
    1. 在 src/fetchers/impl/xxx.py 实现类 (继承 FullReplace / Incremental / Kline).
    2. 在 src/fetchers/impl/__init__.py 里 import.
    3. 把类加到下面 REGISTRY_CLASSES 列表 (顺序决定执行顺序).
    4. 在 config.yaml 的 fetchers 节点加一行 <NAME>: { enabled: true }.
"""

from __future__ import annotations

from typing import Type

from .fetchers.base import BaseFetcher
from .fetchers.impl import (
    BackwardFactorFetcher,
    CalendarFetcher,
    HistCodeListFetcher,
    KlineDayFetcher,
    KlineMin1Fetcher,
    KlineMin5Fetcher,
)

REGISTRY_CLASSES: list[Type[BaseFetcher]] = [
    CalendarFetcher,
    HistCodeListFetcher,
    BackwardFactorFetcher,
    KlineDayFetcher,
    KlineMin5Fetcher,
    KlineMin1Fetcher,
]

REGISTRY: dict[str, Type[BaseFetcher]] = {}
for _cls in REGISTRY_CLASSES:
    if not _cls.NAME:
        raise ValueError(f"{_cls.__name__}.NAME is empty")
    if _cls.NAME in REGISTRY:
        raise ValueError(
            f"duplicate fetcher NAME {_cls.NAME!r} "
            f"({_cls.__name__} vs {REGISTRY[_cls.NAME].__name__})"
        )
    REGISTRY[_cls.NAME] = _cls


def resolve(name: str) -> Type[BaseFetcher]:
    try:
        return REGISTRY[name]
    except KeyError as e:
        raise KeyError(
            f"Unknown fetcher {name!r}. Known: {sorted(REGISTRY)}"
        ) from e


def all_names() -> list[str]:
    return list(REGISTRY.keys())
