"""raw 层基类。

raw 层职责：调用供应商 SDK 抓取数据，原样落 parquet 到 /opt/raw_parquet，**不做归一化**。
归一化在 ingest 层完成（见 docs/layers/raw.md）。

Fetcher 通过依赖注入接收一个「client」对象（封装 SDK 调用），便于测试时注入 Fake。
"""

from __future__ import annotations

import abc
import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from gr_data.common.paths import RawPaths
from gr_data.logging import get_logger


@dataclass
class RawContext:
    """raw fetcher 运行上下文。"""

    paths: RawPaths
    rate_limit: dict[str, Any] = field(default_factory=dict)
    start_date: int | None = None  # 全局 int8 下限

    @property
    def sleep_between_requests(self) -> float:
        return float(self.rate_limit.get("sleep_between_requests_sec", 1.5))

    @property
    def max_retries(self) -> int:
        return int(self.rate_limit.get("max_retries", 5))

    @property
    def backoff_base(self) -> float:
        return float(self.rate_limit.get("retry_backoff_base_sec", 3.0))


class BaseFetcher(abc.ABC):
    """所有 raw fetcher 的基类。

    子类约定：
    - ``PROVIDER`` / ``DATASET``：归属 provider 与数据集名（决定落盘目录）。
    - ``fetch(mode)``：执行抓取，mode ∈ {'init', 'update'}。
    """

    PROVIDER: str = ""
    DATASET: str = ""

    def __init__(self, client: Any, ctx: RawContext):
        self.client = client
        self.ctx = ctx
        self.log = get_logger(f"raw.{self.PROVIDER}.{self.DATASET}")

    @property
    def paths(self) -> RawPaths:
        return self.ctx.paths

    @abc.abstractmethod
    def fetch(self, mode: str = "update") -> int:
        """执行抓取，返回写入的文件/分片数量。"""
        raise NotImplementedError


def month_range(start: date, end: date) -> list[tuple[str, date, date]]:
    """产出 [(YYYY-MM, 月初, 月末), ...]，闭区间按自然月切分。

    首月起点与末月终点分别夹到 start / end，避免越界抓取。

    放在这里而不是某个 provider 下面：tushare 与 datayes 都按自然月分区落盘，
    两份实现迟早会漂移（一边修了边界、另一边没修），而这种漂移只会表现为
    「某个月的数据少了几天」，没有任何报错。
    """
    out: list[tuple[str, date, date]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        last_day = _calendar.monthrange(y, m)[1]
        first = max(date(y, m, 1), start)
        last = min(date(y, m, last_day), end)
        out.append((f"{y:04d}-{m:02d}", first, last))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
