"""限流与重试工具。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import date, datetime
from typing import Any, TypeVar


T = TypeVar("T")


def sleep_s(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)


class PermanentError(RuntimeError):
    """确定性失败，重试没有意义（缺凭证、缺 SDK、参数非法等）。

    :func:`retry_call` 遇到它会立即抛出，不做退避。缺 token 这类问题重试 5 次
    要白等约 45 秒，而且真正的原因会被一串重试日志淹没。
    """


def retry_call(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = 5,
    backoff_base: float = 3.0,
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> T:
    """指数退避重试：等待 = backoff_base * 2^(attempt-1)。重试耗尽抛原异常。

    :class:`PermanentError` 不重试，直接抛出。
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except PermanentError:
            # 配置类错误重试多少次都是同样的结果，立刻抛给调用方。
            raise
        except Exception as exc:  # noqa: BLE001 - 供应商异常种类多，统一重试
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = backoff_base * (2 ** (attempt - 1))
            if logger:
                logger.warning(
                    "调用失败，第 %d/%d 次重试，%.1fs 后重试: %s",
                    attempt,
                    max_retries,
                    wait,
                    exc,
                )
            sleep_s(wait)
    assert last_exc is not None
    raise last_exc


# ---- 切块 ----
def chunk_list(items: Sequence[T], size: int) -> Iterator[list[T]]:
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def flatten_iter(it: Iterable[Iterable[T]]) -> list[T]:
    out: list[T] = []
    for sub in it:
        out.extend(sub)
    return out


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
    if start > end:
        return
    cur = start
    while cur <= end:
        chunk_end = min(next_int_date(cur, step_days - 1), end)
        yield cur, chunk_end
        cur = next_int_date(chunk_end, 1)
