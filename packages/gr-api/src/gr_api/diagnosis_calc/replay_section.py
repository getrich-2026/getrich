"""从已验证的连续收盘净值计算假设回放历史指标；不重新建仓。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from math import fsum, isfinite
from typing import Any, Literal

from gr_api.diagnosis_calc.history import benchmark_sensitivity, historical_volatility
from gr_api.diagnosis_calc.metrics import Window, degraded, ok, unavailable
from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult


@dataclass(frozen=True)
class BenchmarkSeries:
    """纯计算层接收的已冻结全收益基准状态与日收益映射。"""

    status: Literal["ok", "benchmark_missing", "data_not_validated"]
    symbol: str | None = None
    name: str | None = None
    version: str | None = None
    returns: Mapping[date, float] = field(default_factory=dict)
    reason: str | None = None


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


def _period_comparison(
    observed: list[ReplayPoint],
    *,
    window: Window,
    benchmark: BenchmarkSeries,
    trading_days: Sequence[date] | None,
) -> dict[str, Any]:
    """计算统计区间首末收盘之间的组合与全收益基准累计简单收益差（仅取 S < d <= E）。"""
    if len(observed) < 2:
        return unavailable(
            reason_code="history_insufficient",
            reason="统计区间内不足两个可靠收盘净值，无法计算同期累计收益对照。",
            window_target=window,
            sample_count=0,
        )
    if benchmark.status == "benchmark_missing":
        return unavailable(
            reason_code="benchmark_missing",
            reason=benchmark.reason or "未选择或缺少已准入的全收益基准。",
            window_target=window,
            sample_count=0,
        )
    if benchmark.status == "data_not_validated":
        return unavailable(
            reason_code="data_not_validated",
            reason=benchmark.reason or "已绑定的全收益基准版本无法验证。",
            window_target=window,
            sample_count=0,
        )

    start_close = observed[0].day
    end_close = observed[-1].day
    if trading_days is not None:
        required_days = sorted({d for d in trading_days if start_close < d <= end_close})
    else:
        required_days = [p.day for p in observed[1:]]

    if not required_days:
        return unavailable(
            reason_code="history_insufficient",
            reason="统计区间内缺少完整交易日收益区间。",
            window_target=window,
            sample_count=0,
        )

    observed_days = {p.day for p in observed}
    missing_portfolio = [d for d in required_days if d not in observed_days]
    if missing_portfolio:
        sample = "、".join(d.isoformat() for d in missing_portfolio[:5])
        suffix = "等" if len(missing_portfolio) > 5 else ""
        return unavailable(
            reason_code="history_insufficient",
            reason=(
                f"组合净值在统计区间内缺失 {len(missing_portfolio)} 个交易日收盘"
                f"（{sample}{suffix}），无法计算同期累计收益对照。"
            ),
            window_target=window,
            sample_count=len(required_days) - len(missing_portfolio),
        )

    bench_returns = benchmark.returns
    valid_days = [
        d
        for d in required_days
        if d in bench_returns and isfinite(bench_returns[d]) and bench_returns[d] >= -1.0
    ]
    missing_bench = [d for d in required_days if d not in valid_days]
    if missing_bench:
        sample = "、".join(d.isoformat() for d in missing_bench[:5])
        suffix = "等" if len(missing_bench) > 5 else ""
        return unavailable(
            reason_code="history_insufficient",
            reason=(
                f"所选全收益基准在统计区间内缺失 {len(missing_bench)} 个交易日收益"
                f"（{sample}{suffix}），无法计算同期累计收益对照。"
            ),
            window_target=window,
            sample_count=len(valid_days),
        )

    portfolio_ret = observed[-1].nav / observed[0].nav - Decimal(1)
    bench_factor = Decimal(1)
    for day in required_days:
        bench_factor *= Decimal(1) + Decimal(str(bench_returns[day]))
    benchmark_ret = bench_factor - Decimal(1)
    diff = portfolio_ret - benchmark_ret
    symbol = benchmark.symbol or "BENCHMARK"
    name = benchmark.name or symbol
    version = benchmark.version or "unversioned"
    return ok(
        {
            "portfolio_simple_return": float(portfolio_ret),
            "benchmark_simple_return": float(benchmark_ret),
            "return_difference": float(diff),
            "benchmark_symbol": symbol,
            "benchmark_name": name,
            "benchmark_version": version,
        },
        method="historical_replay_period_comparison",
        window_target=window,
        window_actual=(start_close, end_close),
        sample_count=len(required_days),
    )


def history_section(
    result: ReplayResult,
    *,
    window: tuple[date, date],
    benchmark_returns: dict[date, float] | None = None,
    benchmark: BenchmarkSeries | None = None,
    trading_days: Sequence[date] | None = None,
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

    if benchmark is None:
        if benchmark_returns:
            effective_benchmark = BenchmarkSeries(
                status="ok",
                symbol="BENCHMARK",
                name="全收益基准",
                version="unversioned",
                returns=benchmark_returns,
            )
        else:
            effective_benchmark = BenchmarkSeries(status="benchmark_missing")
    else:
        effective_benchmark = benchmark

    effective_returns = (
        dict(effective_benchmark.returns) if effective_benchmark.status == "ok" else {}
    )

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
    for field_name in (
        "return_attribution",
        "beta_vs_alpha",
        "risk_attribution",
        "historical_percentile",
    ):
        out[field_name] = unavailable(
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
        for field_name in (
            "replay_volatility",
            "portfolio_beta",
            "portfolio_benchmark_correlation",
            "max_drawdown",
            "current_drawdown",
            "var",
            "cvar",
            "period_comparison",
        ):
            out[field_name] = unavailable(reason_code=code, reason=reason, window_target=window)
        return {"status": "ready", "value": out}
    out["max_drawdown"], out["current_drawdown"] = _drawdowns(observed, window)
    out["replay_volatility"] = historical_volatility(returns, window=window, min_samples=120)
    out["period_comparison"] = _period_comparison(
        observed,
        window=window,
        benchmark=effective_benchmark,
        trading_days=trading_days,
    )
    if effective_returns:
        sensitivity = benchmark_sensitivity(returns, effective_returns, window=window)
        out["portfolio_beta"], out["portfolio_benchmark_correlation"] = (
            sensitivity.beta,
            sensitivity.correlation,
        )
    else:
        for field_name in ("portfolio_beta", "portfolio_benchmark_correlation"):
            out[field_name] = unavailable(
                reason_code="benchmark_missing",
                reason="缺少指定全收益基准序列。",
                window_target=window,
                sample_count=0,
            )
    if n < 120:
        for field_name in ("var", "cvar"):
            out[field_name] = unavailable(
                reason_code="history_insufficient",
                reason="历史模拟至少需要 120 个完整日收益。",
                window_target=window,
                window_actual=actual,
                sample_count=n,
            )
    else:
        k = (n + 19) // 20
        tail = sorted(returns.values())[:k]
        for field_name, value in (("var", tail[-1]), ("cvar", fsum(tail) / k)):
            out[field_name] = ok(
                value,
                method=f"historical_replay_1d_95pct_k{k}",
                confidence="medium" if n < 250 else "high",
                window_target=window,
                window_actual=actual,
                sample_count=n,
            )
    return {"status": "ready", "value": out}
