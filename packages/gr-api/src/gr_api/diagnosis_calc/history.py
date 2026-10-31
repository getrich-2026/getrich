"""历史统计：日简单收益、历史相关性视图（PA-09）与个股历史年化波动率（PA-20）。

收益口径：``simple_return_t = adj_close_t / adj_close_{t-1} - 1``，``adj_close = close ×
adj_factor``（Tushare 复权因子原值，分红与拆并股由因子衔接）。只在相邻两个开市日都可交易
且都有价格时计一个收益：全天停牌日、跨停牌的复牌收益和状态未知的缺口都剔除，不补值、
不跨缺口把多日变化当单日收益。日内停牌（INTRADAY_HALTED）当日有真实收盘价，计入样本
（2026-10-31 用户确认）。相关性与波动率是两套掩码，互不复用剔除日期。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, TypedDict

import numpy as np
from gr_api.diagnosis_calc.metrics import Window, degraded, ok, unavailable


#: 有真实收盘价、可计收益的 D-023 日级状态。
TRADABLE_STATUSES = frozenset({"NORMAL", "INTRADAY_HALTED"})

ANNUALIZATION_DAYS = 252
METHOD = "historical"


def trading_status(
    *,
    has_bar: bool,
    covered: bool,
    full_suspend: bool,
    intraday_suspend: bool,
    resumed: bool,
) -> str:
    """D-023 日级四态，与 ``gr_data.common.trading_status.resolve_trading_status`` 逐值一致。

    缺停复牌采集覆盖、证据冲突或无 bar 且无停牌事件时为 UNKNOWN，不推断为停牌。
    一致性由 ``test_diagnosis_history.py`` 对全部 32 种组合守卫；改规则须两边同步。
    """
    if not covered:
        return "UNKNOWN"
    if has_bar and not full_suspend and not intraday_suspend:
        return "NORMAL"
    if has_bar and intraday_suspend and not full_suspend:
        return "INTRADAY_HALTED"
    if not has_bar and full_suspend and not intraday_suspend and not resumed:
        return "HALTED"
    return "UNKNOWN"


@dataclass(frozen=True)
class DailyObservation:
    """一只股票在一个开市日的观测；无 bar 时 ``adj_close`` 为 None。"""

    status: str  # NORMAL / INTRADAY_HALTED / HALTED / UNKNOWN（D-023）
    adj_close: Decimal | None


def daily_returns(
    calendar: Sequence[date],
    observations: Mapping[date, DailyObservation],
    *,
    window: Window,
) -> dict[date, float]:
    """返回 ``window`` 内的有效日简单收益（键为收益所属的后一交易日）。

    Args:
        calendar: 该股所在交易所的开市日，升序且须连续完整（含 window 起点前一个开市日）。
        observations: 按开市日索引的观测；上市前的日子不应出现。缺少某日即视为缺口。
        window: 收益观测区间闭区间；区间起点的收益用前一开市日价格，不向区间外扩展。

    Returns:
        日期 → 简单收益（小数）。价格非正或非有限的日子按缺口处理。

    Complexity:
        O(len(calendar))。
    """
    out: dict[date, float] = {}
    start, end = window
    for prev_day, day in zip(calendar, calendar[1:], strict=False):
        if day < start or day > end:
            continue
        prev, cur = observations.get(prev_day), observations.get(day)
        if prev is None or cur is None:
            continue
        if prev.status not in TRADABLE_STATUSES or cur.status not in TRADABLE_STATUSES:
            continue
        if not _valid_price(prev.adj_close) or not _valid_price(cur.adj_close):
            continue
        assert prev.adj_close is not None and cur.adj_close is not None
        out[day] = float(cur.adj_close / prev.adj_close) - 1.0
    return out


def _valid_price(price: Decimal | None) -> bool:
    return price is not None and price.is_finite() and price > 0


def _window_of(days: Sequence[date]) -> Window | None:
    return (min(days), max(days)) if days else None


@dataclass(frozen=True)
class _Sample:
    """目标窗口、实际样本起止与样本数；ok／degraded／unavailable 三态都回显。"""

    window_target: Window
    window_actual: Window | None
    sample_count: int

    def kwargs(self) -> _SampleKwargs:
        return {
            "window_target": self.window_target,
            "window_actual": self.window_actual,
            "sample_count": self.sample_count,
        }


class _SampleKwargs(TypedDict):
    window_target: Window
    window_actual: Window | None
    sample_count: int


def historical_volatility(
    returns: Mapping[date, float], *, window: Window, min_samples: int
) -> dict[str, Any]:
    """PA-20：样本标准差（N−1）× √252；至少 ``min_samples`` 个有效日收益，零波动为 0。"""
    days = sorted(returns)
    n = len(days)
    sample = _Sample(window, _window_of(days), n)
    if n < min_samples:
        return unavailable(
            reason_code="history_insufficient",
            reason=f"有效日收益 {n} 个，少于 {min_samples} 个，历史波动率不可用。",
            **sample.kwargs(),
        )
    values = np.fromiter((returns[d] for d in days), dtype=float, count=n)
    if float(values.max()) == float(values.min()):
        return ok(0.0, method=METHOD, **sample.kwargs())
    vol = float(values.std(ddof=1)) * math.sqrt(ANNUALIZATION_DAYS)
    return ok(vol, method=METHOD, confidence="high", **sample.kwargs())


@dataclass(frozen=True)
class CorrelationView:
    """历史相关性视图：矩阵、平均两两相关与高相关持仓对共用同一组共同样本。"""

    matrix: dict[str, Any]
    average: dict[str, Any]
    high_pairs: dict[str, Any]
    excluded_zero_variance: list[int]


def correlation_view(
    returns: Mapping[int, Mapping[date, float]],
    *,
    window: Window,
    min_samples: int,
    high_threshold: float,
) -> CorrelationView:
    """PA-09 历史相关性：整张矩阵按共同有效日期对齐，至少 ``min_samples`` 个共同样本。

    平均两两相关对不同股票对简单平均（不含对角线、不按权重）；高相关持仓对严格大于
    ``high_threshold``，每对只计一次，不取绝对值。零方差股票无法定义相关性，从矩阵中
    排除并以 degraded 披露，不补 0。

    Args:
        returns: instrument_id → 该股在 window 内的有效日收益。
        window: 目标统计区间，回显为 window_target。
        min_samples: 最少共同有效日收益数（一期 120）。
        high_threshold: 高相关阈值（一期 0.7）。
    """
    ids = sorted(returns)
    if len(ids) < 2:
        na = unavailable(reason_code="not_applicable", reason="单只股票不适用两两相关性。")
        return CorrelationView(dict(na), dict(na), dict(na), [])

    common = sorted(set.intersection(*(set(returns[i]) for i in ids)))
    n = len(common)
    sample = _Sample(window, _window_of(common), n)
    if n < min_samples:
        na = unavailable(
            reason_code="history_insufficient",
            reason=(
                f"全部持仓的共同有效交易日收益 {n} 个，少于 {min_samples} 个，历史相关性不可用。"
            ),
            **sample.kwargs(),
        )
        return CorrelationView(dict(na), dict(na), dict(na), [])

    data = np.array([[returns[i][d] for i in ids] for d in common], dtype=float)
    stds = data.std(axis=0, ddof=1)
    keep = [k for k, s in enumerate(stds) if np.isfinite(s) and s > 0]
    excluded = [ids[k] for k in range(len(ids)) if k not in keep]
    if len(keep) < 2:
        na = unavailable(
            reason_code="zero_variance",
            reason="可计算相关性的股票不足两只（其余在共同样本内收益恒定）。",
            **sample.kwargs(),
        )
        return CorrelationView(dict(na), dict(na), dict(na), excluded)

    kept_ids = [ids[k] for k in keep]
    corr = np.corrcoef(data[:, keep], rowvar=False)
    corr = np.clip((corr + corr.T) / 2, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    upper = [
        (kept_ids[a], kept_ids[b], float(corr[a, b]))
        for a in range(len(kept_ids))
        for b in range(a + 1, len(kept_ids))
    ]
    average = sum(c for _, _, c in upper) / len(upper)
    pairs = [
        {"left_instrument_id": left, "right_instrument_id": right, "correlation": c}
        for left, right, c in sorted(upper, key=lambda p: (-p[2], p[0], p[1]))
        if c > high_threshold
    ]
    matrix = {"instrument_ids": kept_ids, "matrix": corr.tolist()}

    if excluded:
        reason = f"{len(excluded)} 只股票在共同样本内收益恒定，无法定义相关性，已从矩阵中排除。"

        def make(value: Any) -> dict[str, Any]:
            return degraded(
                value, reason_code="zero_variance", reason=reason, method=METHOD, **sample.kwargs()
            )
    else:

        def make(value: Any) -> dict[str, Any]:
            return ok(value, method=METHOD, **sample.kwargs())

    return CorrelationView(make(matrix), make(average), make(pairs), excluded)
