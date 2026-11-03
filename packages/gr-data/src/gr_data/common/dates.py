"""供应商 YYYYMMDD 日期转换、闭区间分块与索引水位。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pandas as pd


# ---- int8 日期工具（与银河 SDK 的 int 日期对齐）----
def today_int() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


def to_int_date(d: int | str | date | datetime) -> int:
    if isinstance(d, int):
        return d
    if isinstance(d, str):
        return int(d.replace("-", "")[:8])
    if isinstance(d, datetime):
        return int(d.strftime("%Y%m%d"))
    if isinstance(d, date):
        return int(d.strftime("%Y%m%d"))
    raise TypeError(f"无法转换为 int8 日期: {d!r}")


def int_to_date(d: int) -> date:
    s = str(int(d))
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def next_int_date(d: int, days: int = 1) -> int:
    from datetime import timedelta

    return to_int_date(int_to_date(d) + timedelta(days=days))


def chunk_date_range(start: int, end: int, step_days: int) -> Iterator[tuple[int, int]]:
    """把闭区间 [start, end]（int8）按 step_days 切块。"""
    if step_days <= 0:
        raise ValueError("step_days must be > 0")
    if start > end:
        return
    cur = start
    while cur <= end:
        chunk_end = min(next_int_date(cur, step_days - 1), end)
        yield cur, chunk_end
        cur = next_int_date(chunk_end, 1)


def last_index_date(df: pd.DataFrame | None) -> int | None:
    """取索引最大值并转 int8（K 线水位用）。"""
    if df is None or df.empty:
        return None
    try:
        mx = df.index.max()
    except (TypeError, ValueError):
        return None
    if hasattr(mx, "strftime"):
        return int(mx.strftime("%Y%m%d"))
    try:
        return int(mx)
    except (TypeError, ValueError):
        return None
