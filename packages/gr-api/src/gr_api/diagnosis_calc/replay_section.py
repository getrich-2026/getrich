"""从已验证的连续收盘净值计算假设回放历史指标；不重新建仓。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from math import fsum
from typing import Any

from gr_api.diagnosis_calc.history import benchmark_sensitivity, historical_volatility
from gr_api.diagnosis_calc.metrics import Window, degraded, ok, unavailable
from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult


def _drawdowns(points: list[ReplayPoint], window: Window) -> tuple[dict, dict]:
    """以统计窗口首个收盘为高点起算；并列最深低点取首次发生。"""
    n = len(points)
    actual = (points[0].day, points[-1].day) if points else None
    if n < 2:
        missing = unavailable(
            reason_code="history_insufficient",
            reason="统计区间内不足两个收盘净值。",
            window_target=window,
            window_actual=actual,
            sample_count=n,
        )
        return missing, dict(missing)
    high = peak = trough = 0
    worst = current = Decimal(0)
    for idx, point in enumerate(points):
        if point.nav >= points[high].nav:
            high = idx
        current = point.nav / points[high].nav - 1
        if current < worst:
            worst, peak, trough = current, high, idx
    recovery = (
        next((i for i in range(trough + 1, n) if points[i].nav >= points[peak].nav), None)
        if worst < 0
        else None
    )
    detail = {
        "value": float(worst),
        "peak_date": points[peak].day,
        "trough_date": points[trough].day,
        "recovery_date": points[recovery].day if recovery is not None else None,
        "duration_days": ((recovery if recovery is not None else n - 1) - peak) if worst < 0 else 0,
    }

    def metric(value: Any) -> dict:
        if n < 120:
            return degraded(
                value,
                method="historical_replay",
                reason_code="history_insufficient",
                reason="统计区间不足 120 个交易日，回撤可能低估。",
                sample_count=n,
                window_actual=actual,
                window_target=window,
            )
        return ok(
            value,
            method="historical_replay",
            sample_count=n,
            window_actual=actual,
            window_target=window,
        )

    return metric(detail), metric(float(current))


def history_section(
    result: ReplayResult, *, window: tuple[date, date], benchmark_returns: dict[date, float]
) -> dict[str, Any]:
    """基于税前未扣成本的假设回放生成 C 区。收益归属于后一交易日。

    window 仅限制统计；回撤高点从窗口内首个收盘算起。回放若在当日开盘或估值时
    中止，truncated_at 指向前一个可靠收盘。该日之后的统计不可用。
    """
    start, end = window
    if start > end:
        raise ValueError("Invalid statistics window")
    points = result.points
    if any(not p.nav.is_finite() or p.nav <= 0 or not 0 <= p.equity <= p.nav for p in points):
        raise ValueError("Invalid portfolio close valuation")
    if any(a.day >= b.day for a, b in zip(points, points[1:], strict=False)):
        raise ValueError("Replay dates must be ordered and unique")
    stopped = result.stopped_on is not None
    code = (
        "execution_undetermined"
        if result.reason == "execution_undetermined"
        else "replay_terminated"
    )
    reason = (
        f"回放在 {result.stopped_on} 中止，原因 {result.reason}，"
        f"受影响标的 {result.instrument_id}。"
    )
    if points:
        series = {
            "build_start": points[0].day,
            "dates": [p.day for p in points],
            "nav": [float(p.nav) for p in points],
            "stock_position": [float(p.equity / p.nav) for p in points],
            "unexecuted": [asdict(u) for u in result.unexecuted],
            "limiting_instrument_ids": [],
            "truncated_at": points[-1].day if stopped else None,
            "termination_reason": result.reason,
        }
        replay = (
            degraded(series, method="historical_replay", reason_code=code, reason=reason)
            if stopped
            else ok(series, method="historical_replay")
        )
    else:
        replay = unavailable(
            reason_code=code if stopped else "history_insufficient",
            reason=reason if stopped else "没有可靠的收盘净值。",
        )
    out = {"replay": replay}
    for field in (
        "return_attribution",
        "beta_vs_alpha",
        "risk_attribution",
        "historical_percentile",
    ):
        out[field] = unavailable(
            reason_code="feature_not_available", reason="该历史分析项尚未开放。"
        )
    observed = [p for p in points if start <= p.day <= end]
    returns = {
        b.day: float(b.nav / a.nav - 1)
        for a, b in zip(points, points[1:], strict=False)
        if start <= b.day <= end
    }
    n = len(returns)
    actual = (min(returns), max(returns)) if returns else None
    if stopped and (not points or end > points[-1].day):
        for field in (
            "replay_volatility",
            "portfolio_beta",
            "portfolio_benchmark_correlation",
            "max_drawdown",
            "current_drawdown",
            "var",
            "cvar",
        ):
            out[field] = unavailable(reason_code=code, reason=reason, window_target=window)
        return {"status": "ready", "value": out}
    out["max_drawdown"], out["current_drawdown"] = _drawdowns(observed, window)
    out["replay_volatility"] = historical_volatility(returns, window=window, min_samples=120)
    if benchmark_returns:
        sensitivity = benchmark_sensitivity(returns, benchmark_returns, window=window)
        out["portfolio_beta"], out["portfolio_benchmark_correlation"] = (
            sensitivity.beta,
            sensitivity.correlation,
        )
    else:
        for field in ("portfolio_beta", "portfolio_benchmark_correlation"):
            out[field] = unavailable(
                reason_code="benchmark_missing",
                reason="缺少指定全收益基准序列。",
                window_target=window,
                sample_count=0,
            )
    if n < 120:
        for field in ("var", "cvar"):
            out[field] = unavailable(
                reason_code="history_insufficient",
                reason="历史模拟至少需要 120 个完整日收益。",
                window_target=window,
                window_actual=actual,
                sample_count=n,
            )
    else:
        k = (n + 19) // 20
        tail = sorted(returns.values())[:k]
        for field, value in (("var", tail[-1]), ("cvar", fsum(tail) / k)):
            out[field] = ok(
                value,
                method=f"historical_replay_1d_95pct_k{k}",
                confidence="medium" if n < 250 else "high",
                window_target=window,
                window_actual=actual,
                sample_count=n,
            )
    return {"status": "ready", "value": out}
