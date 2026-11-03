"""期货缺失休市日的四证据推导；只生成内存结果，不修改供应商raw。"""

from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import pandas as pd

from gr_data.common.parquet import read_parquet_strict
from gr_data.common.paths import RawPaths
from gr_data.raw.tushare.asset_rules import OPTION_SUFFIXES
from gr_data.raw.tushare.context import FUTURE_EXCHANGES


FUTURE_CLOSED_DAY_RULE = "tushare_future_calendar_inferred_closed_v1"


@dataclass
class FutureCalendarCompletion:
    """保留供应商行、补全验证区间的内存日历及逐日证据。"""

    frame: pd.DataFrame
    inferred: list[dict[str, Any]]


class FutureCalendarGapError(ValueError):
    """一次收集全部不可推导日期，供采集边界完整报告。"""

    def __init__(self, exchange: str, failures: list[dict[str, Any]]) -> None:
        self.failures = failures
        super().__init__(
            f"Incomplete trading calendar exchange={exchange} "
            f"unresolved_days={[r['date'] for r in failures]}"
        )


def calendar_dates(frame: pd.DataFrame) -> pd.Series:
    """严格解析供应商日期，不让缺失／非法日期被解释为休市。"""
    values = pd.to_datetime(frame["cal_date"].astype(str), format="%Y%m%d", errors="raise")
    if values.isna().any():
        raise ValueError("Missing calendar date")
    return values.dt.date


def future_calendar_start(paths: RawPaths, exchange: str, first: date) -> date:
    """已上市合约前不补交易所日历；无上市日期时保持请求起点。"""
    frame = read_parquet_strict(paths.dataset_file("tushare", "instruments", "future"))
    if frame is None or "list_date" not in frame:
        return first
    selected = frame.loc[frame["exchange"].eq(exchange), "list_date"].dropna()
    selected = selected.loc[~selected.astype(str).isin(["", "0", "00000000"])]
    if selected.empty:
        return first
    days = pd.to_datetime(selected.astype(str), format="%Y%m%d", errors="raise").dt.date
    return max(first, min(days))


def _raw_bar_evidence(paths: RawPaths, days: set[date], exchange: str) -> dict[str, Any]:
    """扫描所有正式月分区，任何行情行（含零成交）都否决推导。

    未生成月分区仅表示现有raw不存在记录，不宣称该月已采完；将此事实单列
    入证据。峰值内存为一个分区的两列，复杂度O(raw总行数)。
    """
    counts: dict[date, int] = {}
    inventory = []
    directory = paths.dataset_dir("tushare", "fut_daily")
    for path in sorted(directory.glob("*.parquet")):
        if not re.fullmatch(r"\d{4}-\d{2}\.parquet", path.name):
            continue
        frame = pd.read_parquet(path, columns=["ts_code", "trade_date"])
        dates = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="raise")
        if dates.isna().any():
            raise ValueError(f"Invalid raw futures date file={path.name}")
        selected = dates.dt.date.isin(days)
        codes = frame["ts_code"].astype("string")
        suffixes = codes.str.rsplit(".", n=1).str[-1]
        if (selected & ~suffixes.isin([OPTION_SUFFIXES[e] for e in FUTURE_EXCHANGES])).any():
            raise ValueError(f"Unknown raw futures exchange file={path.name}")
        selected &= codes.str.rsplit(".", n=1).str[-1].eq(OPTION_SUFFIXES[exchange])
        for day, count in dates.loc[selected].dt.date.value_counts().items():
            key = cast(date, day)
            counts[key] = counts.get(key, 0) + int(count)
        inventory.append(
            {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    digest = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    return {"counts": counts, "files_scanned": len(inventory), "inventory_sha256": digest}


def complete_future_calendar(
    paths: RawPaths,
    exchange: str,
    first: date,
    last: date,
    *,
    frame: pd.DataFrame | None = None,
) -> FutureCalendarCompletion:
    """仅四项全部通过时补休市行；已有供应商行始终保留。

    最近开市日必须取原始期货日历，不能借已推导行串联；不使用上交所开市日
    代替期货开市日。缺上交所记录、任意原始行情、断链、无两侧邻点均停止。
    """
    # 延迟导入避免参考采集器与共享规则形成模块初始化循环。
    from gr_data.raw.tushare.fetchers.reference import read_open_days, require_calendar_range

    if exchange not in FUTURE_EXCHANGES:
        raise ValueError(f"Unknown future calendar exchange={exchange}")
    path = paths.dataset_file("tushare", "future_calendar", exchange)
    raw = read_parquet_strict(path) if frame is None else frame.copy()
    if raw is None:
        raise ValueError(f"Missing future_calendar[{exchange}]")
    opens = read_open_days(raw, exchange)
    dates = calendar_dates(raw)
    missing = sorted(set(pd.date_range(first, last).date) - set(dates)) if first <= last else []
    if not missing:
        return FutureCalendarCompletion(raw.copy(), [])
    sse_path = paths.dataset_file("tushare", "calendar", "SSE")
    sse = read_parquet_strict(sse_path)
    sse_flags = {}
    if sse is not None:
        read_open_days(sse, "SSE")
        sse_flags = dict(zip(calendar_dates(sse), pd.to_numeric(sse["is_open"]), strict=True))
    bars = _raw_bar_evidence(paths, set(missing), exchange)
    pretrade = dict(
        zip(dates, raw.get("pretrade_date", pd.Series(None, index=raw.index)), strict=True)
    )
    evidence: list[dict[str, Any]] = []
    failures = []
    additions = []
    source_sha = hashlib.sha256(raw.to_json(orient="split", date_format="iso").encode()).hexdigest()
    sse_sha = hashlib.sha256(sse_path.read_bytes()).hexdigest() if sse is not None else None
    for day in missing:
        index = bisect_left(opens, day)
        previous = opens[index - 1] if index else None
        following = opens[index] if index < len(opens) else None
        value = pretrade.get(following)
        parsed = pd.to_datetime(str(value), format="%Y%m%d", errors="coerce")
        linked = (
            previous is not None
            and following is not None
            and not pd.isna(parsed)
            and parsed.date() == previous
        )
        count = bars["counts"].get(day, 0)
        checks = {
            "supplier_row_absent": {"passed": True, "source_rows": 0},
            "sse_closed": {
                "passed": sse_flags.get(day) == 0,
                "record_present": day in sse_flags,
                "is_open": None if day not in sse_flags else int(sse_flags[day]),
            },
            "no_raw_fut_daily": {
                "passed": count == 0,
                "rows": count,
                "files_scanned": bars["files_scanned"],
                "inventory_sha256": bars["inventory_sha256"],
                "month_partition_present": paths.dataset_file(
                    "tushare", "fut_daily", day.strftime("%Y-%m")
                ).exists(),
                "scope": "all existing raw monthly partitions; not a month-completion claim",
            },
            "supplier_open_day_chain": {
                "passed": bool(linked),
                "previous_open": str(previous) if previous else None,
                "next_open": str(following) if following else None,
                "next_pretrade_date": str(parsed.date()) if not pd.isna(parsed) else None,
            },
        }
        detail = {
            "exchange": exchange,
            "date": str(day),
            "rule": FUTURE_CLOSED_DAY_RULE,
            "is_open": False,
            "has_night": False,
            "evidence": checks,
            "supplier_calendar_semantic_sha256": source_sha,
            "sse_calendar_sha256": sse_sha,
        }
        if not all(item["passed"] for item in checks.values()):
            failures.append(detail)
            continue
        assert previous is not None
        evidence.append(detail)
        additions.append(
            {
                "exchange": exchange,
                "cal_date": day.strftime("%Y%m%d"),
                "is_open": 0,
                "pretrade_date": previous.strftime("%Y%m%d"),
            }
        )
    if failures:
        raise FutureCalendarGapError(exchange, failures)
    completed = pd.concat([raw, pd.DataFrame(additions)], ignore_index=True)
    require_calendar_range(completed, first, last, exchange)
    return FutureCalendarCompletion(completed, evidence)
