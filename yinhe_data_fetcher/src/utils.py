"""通用工具: 日期, 切块, parquet I/O."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TypeVar

import pandas as pd

T = TypeVar("T")


# -----------------------------------------------------------------------------
# 日期工具
# AmazingData 使用 8 位 int, 例: 20240530
# -----------------------------------------------------------------------------
def today_int() -> int:
    return int(date.today().strftime("%Y%m%d"))


def to_int_date(d: int | str | date | datetime | pd.Timestamp) -> int:
    if isinstance(d, int):
        return d
    if isinstance(d, str):
        s = d.replace("-", "").replace("/", "")
        return int(s[:8])
    if isinstance(d, (datetime, pd.Timestamp)):
        return int(d.strftime("%Y%m%d"))
    if isinstance(d, date):
        return int(d.strftime("%Y%m%d"))
    raise TypeError(f"Unsupported date type: {type(d)}")


def int_to_date(d: int) -> date:
    return datetime.strptime(str(int(d)), "%Y%m%d").date()


def next_int_date(d: int, days: int = 1) -> int:
    return to_int_date(int_to_date(d) + timedelta(days=days))


# -----------------------------------------------------------------------------
# 切块
# -----------------------------------------------------------------------------
def chunk_list(items: Sequence[T], size: int) -> Iterator[list[T]]:
    """把 list 切成大小为 size 的小块."""
    if size <= 0:
        raise ValueError(f"chunk size must be > 0, got {size}")
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def chunk_date_range(start: int, end: int, step_days: int) -> Iterator[tuple[int, int]]:
    """把 [start, end] (闭区间, int8 date) 切成不超过 step_days 的子区间."""
    if step_days <= 0:
        raise ValueError(f"step_days must be > 0, got {step_days}")
    if start > end:
        return
    cur = int_to_date(start)
    end_d = int_to_date(end)
    while cur <= end_d:
        chunk_end = min(cur + timedelta(days=step_days - 1), end_d)
        yield to_int_date(cur), to_int_date(chunk_end)
        cur = chunk_end + timedelta(days=1)


# -----------------------------------------------------------------------------
# Parquet I/O
# -----------------------------------------------------------------------------
def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(df: pd.DataFrame, path: Path, *, append: bool = False) -> None:
    """写 parquet; append 时会先读旧文件并按索引/列去重合并."""
    path = Path(path)
    ensure_dir(path.parent)
    if append and path.exists():
        old = pd.read_parquet(path)
        combined = pd.concat([old, df], axis=0)
        # 优先按索引去重, 否则按全字段
        if combined.index.name or isinstance(combined.index, pd.MultiIndex):
            combined = combined[~combined.index.duplicated(keep="last")]
        else:
            combined = combined.drop_duplicates(keep="last")
        combined.sort_index(inplace=True)
        combined.to_parquet(path, index=True)
    else:
        df.to_parquet(path, index=True)


def read_parquet_if_exists(path: Path) -> pd.DataFrame | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def last_index_date(df: pd.DataFrame | None) -> int | None:
    """返回 df.index 的最后一个日期 (int8 date); 若无返回 None."""
    if df is None or df.empty:
        return None
    idx = df.index
    try:
        last = idx.max()
    except Exception:
        return None
    try:
        return to_int_date(last)
    except Exception:
        try:
            return int(last)
        except Exception:
            return None


# -----------------------------------------------------------------------------
# 重试 / 限流
# -----------------------------------------------------------------------------
def sleep_s(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def retry_call(
    fn,
    *args,
    max_retries: int = 5,
    backoff_base: float = 3.0,
    logger=None,
    **kwargs,
):
    """指数退避重试. 最后一次失败会抛原异常."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == max_retries:
                break
            wait = backoff_base * (2 ** (attempt - 1))
            if logger:
                logger.warning(
                    "call %s failed (attempt %d/%d): %s; sleep %.1fs then retry",
                    getattr(fn, "__name__", str(fn)),
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def flatten_iter(it: Iterable[Iterable[T]]) -> list[T]:
    out: list[T] = []
    for x in it:
        out.extend(x)
    return out
