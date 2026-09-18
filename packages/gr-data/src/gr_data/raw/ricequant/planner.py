"""米筐特色指数的确定性分片；只消费显式日历快照，不连接 PG。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from gr_data.common.ricequant_specs import (
    DAILY_FIELDS,
    INDEX_DEFINITIONS,
    INDEX_SPECS,
    semantic_hash,
)
from gr_data.config.ricequant import DatasetOptions
from gr_data.raw.base import month_range


@dataclass(frozen=True)
class RequestSlice:
    dataset: str
    contract_version: str
    variant_id: str
    scope_hash: str
    calendar_hash: str
    evidence_hash: str
    start_date: str
    end_date: str
    codes: tuple[str, ...]
    fields: tuple[str, ...]
    trading_days: tuple[str, ...]
    not_applicable: bool = False

    def __post_init__(self) -> None:
        """反序列化也走同一边界，不能用 manifest 中的月份拼越界路径。"""
        if self.dataset not in INDEX_SPECS or self.contract_version != "v1":
            raise ValueError("未知米筐请求契约")
        for digest in (self.variant_id, self.scope_hash, self.calendar_hash, self.evidence_hash):
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("非法米筐请求摘要")
        start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        if start > end or self.start_date[:7] != self.end_date[:7]:
            raise ValueError("米筐请求须为同一自然月内的有效区间")
        if (
            not isinstance(self.codes, (list, tuple))
            or not self.codes
            or any(c not in INDEX_DEFINITIONS for c in self.codes)
        ):
            raise ValueError("未知米筐指数")
        if len(set(self.codes)) != len(self.codes):
            raise ValueError("重复米筐指数")
        if not isinstance(self.fields, (list, tuple)) or len(set(self.fields)) != len(self.fields):
            raise ValueError("非法米筐字段")
        if self.dataset == "rq_index_daily":
            if "close" not in self.fields or not set(self.fields) <= set(DAILY_FIELDS):
                raise ValueError("非法米筐日值字段")
        elif self.fields or len(self.codes) != 1 or start != end:
            raise ValueError("成分和权重须为单指数单日请求")
        if not isinstance(self.trading_days, (list, tuple)) or not self.trading_days:
            raise ValueError("请求缺交易日")
        days = [date.fromisoformat(d) for d in self.trading_days]
        if days != sorted(set(days)) or any(d < start or d > end for d in days):
            raise ValueError("非法请求交易日")
        expected_na = self.dataset != "rq_index_daily" and self.codes[0].startswith("VX")
        if type(self.not_applicable) is not bool or self.not_applicable != expected_na:
            raise ValueError("指数适用性标记不符")

    @property
    def request_id(self) -> str:
        return semantic_hash(asdict(self))

    @property
    def month(self) -> str:
        return self.start_date[:7]


def plan_slices(
    options: DatasetOptions,
    trading_days: tuple[date, ...],
    calendar_hash: str,
    *,
    mode: str,
    completed: set[str],
) -> list[RequestSlice]:
    """补缺片并回扫末尾交易日／末月；改变批大小不改变 variant。"""
    if mode not in {"init", "update"}:
        raise ValueError("未知米筐抓取模式")
    days = sorted(set(d for d in trading_days if options.start_date <= d <= options.end_date))
    scope = semantic_hash(
        {
            "codes": options.index_codes,
            "start": str(options.start_date),
            "end": str(options.end_date),
            "calendar": calendar_hash,
        }
    )
    replay_start = (
        days[-options.replay_trading_days]
        if len(days) >= options.replay_trading_days
        else options.start_date
    )
    result = []
    for month, first, last in month_range(options.start_date, options.end_date):
        month_days = [d for d in days if first <= d <= last]
        if not month_days:
            continue
        if options.name == "rq_index_daily":
            size = options.max_symbols_per_request
            units = [
                (first, last, options.index_codes[i : i + size], month_days)
                for i in range(0, len(options.index_codes), size)
            ]
        else:
            units = [(d, d, (code,), [d]) for d in month_days for code in options.index_codes]
        for begin, end, codes, unit_days in units:
            request = RequestSlice(
                options.name,
                options.contract_version,
                options.variant_id,
                scope,
                calendar_hash,
                options.evidence_hash,
                str(begin),
                str(end),
                codes,
                options.fields,
                tuple(str(d) for d in unit_days),
                options.name != "rq_index_daily" and codes[0].startswith("VX"),
            )
            if (
                mode == "init"
                or request.request_id not in completed
                or end >= replay_start
                or month == options.end_date.strftime("%Y-%m")
            ):
                result.append(request)
    return result


def split_slice(request: RequestSlice) -> tuple[RequestSlice, ...]:
    """范围过大时先二分交易日，再二分代码；单代码单日不再拆分。"""
    days = request.trading_days
    if len(days) > 1:
        middle = len(days) // 2
        boundary = days[middle - 1]
        following = str(date.fromisoformat(boundary) + timedelta(days=1))
        return (
            replace(request, end_date=boundary, trading_days=tuple(days[:middle])),
            replace(request, start_date=following, trading_days=tuple(days[middle:])),
        )
    if len(request.codes) > 1:
        middle = len(request.codes) // 2
        return (
            replace(request, codes=tuple(request.codes[:middle])),
            replace(request, codes=tuple(request.codes[middle:])),
        )
    return ()
