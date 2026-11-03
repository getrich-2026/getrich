"""历史开市日空响应的有界重查；不改变数据完整性门禁。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import TypeVar

from gr_data.common.retry import sleep_s


T = TypeVar("T")
_recovered: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "empty_response_recoveries", default=None
)
EMPTY_RESPONSE_BACKOFF_SECONDS = (5, 15, 45)


class EmptyHistoricalResponseError(ValueError):
    """历史开市日初查及三次重查均为空，调用方必须停止发布。"""


@contextmanager
def capture_empty_response_recoveries() -> Generator[list[dict[str, object]], None, None]:
    """为一个采集批次收集成功恢复事件，供月度汇总使用。

    事件按查询逻辑次数计数，额外请求次数另存；ContextVar隔离并发任务，
    批次结束后不遗留全局计数。失败月份可保留尝试记录，但不能记为已验收。
    """
    events: list[dict[str, object]] = []
    token = _recovered.set(events)
    try:
        yield events
    finally:
        _recovered.reset(token)


def retry_empty_historical_response(
    result: T,
    query: Callable[[], T],
    *,
    is_empty: Callable[[T], bool],
    day: date,
    today: date,
    calendar_is_open: bool,
    logger: logging.Logger,
    context: Mapping[str, str],
) -> T:
    """仅开市、历史日、空结果同时成立时额外查询最多三次。

    首次调用由采集器完成；本函数只处理空表，不吞接口异常、不重试坏的非空
    结果。query沿用原有请求限速和异常重试，成功结果仍交原完整校验链处理。
    休市日、当天及未来日返回原结果，由原调用方保留跳过／待发布语义。
    """
    if not calendar_is_open or day >= today or not is_empty(result):
        return result
    for attempt, seconds in enumerate(EMPTY_RESPONSE_BACKOFF_SECONDS, start=1):
        logger.warning(
            "Empty historical response retry context=%s day=%s "
            "extra_attempt=%d/3 backoff_seconds=%d",
            dict(context),
            day,
            attempt,
            seconds,
        )
        sleep_s(seconds)
        result = query()
        if not is_empty(result):
            event: dict[str, object] = {
                **context,
                "date": day.isoformat(),
                "extra_queries": attempt,
            }
            events = _recovered.get()
            if events is not None:
                events.append(event)
            logger.info("Empty historical response recovered detail=%s", event)
            return result
    raise EmptyHistoricalResponseError(
        f"Unexplained empty historical response context={dict(context)} day={day} "
        "after 3 extra queries"
    )
