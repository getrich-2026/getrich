from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from statistics import stdev

import pytest
from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult, Unfilled
from gr_api.diagnosis_calc.replay_section import BenchmarkSeries, history_section
from gr_api.schemas.diagnosis_response import HistorySection, SectionResult
from gr_api.services import diagnosis_presentation as view


D = Decimal
START = date(2020, 1, 1)


def _result(values: list[Decimal]) -> ReplayResult:
    return ReplayResult(
        tuple(ReplayPoint(START + timedelta(days=i), v, D(0), D(0)) for i, v in enumerate(values)),
        None,
        None,
        None,
    )


def _section(result: ReplayResult, start: int, end: int, reference: dict | None = None) -> dict:
    out = history_section(
        result,
        window=(START + timedelta(days=start), START + timedelta(days=end)),
        benchmark_returns=reference or {},
    )
    SectionResult[HistorySection].model_validate(out)
    return out["value"]


def test_exact_order_tail_and_portfolio_beta_on_close_returns() -> None:
    observations = [D(i) / 1000 for i in range(-60, 60)]
    nav = [D("0.8")]
    for simple_return in observations:
        nav.append(nav[-1] * (1 + simple_return))
    result = _result(nav)
    bench = {p.day: float(r) / 2 for p, r in zip(result.points[1:], observations, strict=True)}
    metrics = _section(result, 0, 120, bench)
    assert metrics["var"]["sample_count"] == 120
    assert metrics["var"]["confidence"] == "medium"
    assert metrics["var"]["value"] == pytest.approx(-0.055)
    assert metrics["cvar"]["value"] == pytest.approx(-0.0575)
    assert metrics["portfolio_beta"]["value"] == pytest.approx(2)
    assert metrics["portfolio_benchmark_correlation"]["value"] == pytest.approx(1)
    assert metrics["replay_volatility"]["value"] == pytest.approx(
        stdev(map(float, observations)) * 252**0.5
    )
    assert _section(result, 0, 119, bench)["var"]["status"] == "unavailable"


def test_selected_window_resets_only_drawdown_peak_and_preserves_series() -> None:
    result = _result(list(map(D, ["5", "2", "1", "2", "1.5"])))
    metrics = _section(result, 1, 4)
    detail = metrics["max_drawdown"]
    assert detail["status"] == "degraded"
    assert detail["value"] == {
        "value": -0.5,
        "peak_date": START + timedelta(days=1),
        "trough_date": START + timedelta(days=2),
        "recovery_date": START + timedelta(days=3),
        "duration_days": 2,
    }
    assert metrics["current_drawdown"]["value"] == -0.25
    assert metrics["replay"]["value"]["nav"] == [5, 2, 1, 2, 1.5]
    assert metrics["portfolio_beta"]["reason_code"] == "benchmark_missing"


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("execution_undetermined", "execution_undetermined"),
        ("delisted_no_terminal_value", "replay_terminated"),
    ],
)
def test_truncation_only_invalidates_statistics_past_reliable_date(reason: str, code: str) -> None:
    result = replace(
        _result([D(1), D(".9")]),
        stopped_on=START + timedelta(days=2),
        reason=reason,
        instrument_id=9,
    )
    truncated = _section(result, 0, 2)
    assert truncated["replay"]["value"]["truncated_at"] == result.points[-1].day
    assert truncated["replay"]["value"]["termination_reason"] == reason
    assert truncated["max_drawdown"]["reason_code"] == code
    assert _section(result, 0, 1)["max_drawdown"]["value"]["value"] == -0.1
    empty = replace(result, points=())
    assert _section(empty, 0, 2)["replay"]["reason_code"] == code


def test_reserved_cash_reduces_stock_position_and_unfilled_is_preserved() -> None:
    result = ReplayResult(
        (ReplayPoint(START, D(".6"), D(".3"), D(".1")),),
        None,
        None,
        None,
        (Unfilled(4, D(".3"), "limit_up_at_open", 3),),
    )
    value = _section(result, 0, 0)["replay"]["value"]
    assert value["stock_position"] == [0.6]
    assert value["unexecuted"][0]["waiting_days"] == 3


def test_period_comparison_fixed_two_day_example_excludes_start_day_return() -> None:
    """B3 固定样例：1 -> 1.02 -> 1.0404，基准后两日各涨 1%，首日大涨 50% 不得混入。"""
    days = [date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 24)]  # 跨周末
    result = ReplayResult(
        tuple(
            ReplayPoint(d, v, D(0), D(0))
            for d, v in zip(days, [D("1"), D("1.02"), D("1.0404")], strict=True)
        ),
        None,
        None,
        None,
    )
    bench_base = BenchmarkSeries(
        status="ok",
        symbol="H00300.CSI",
        name="300收益",
        version="v-300",
        returns={days[0]: 0.0, days[1]: 0.01, days[2]: 0.01},
    )
    bench_pre_jump = BenchmarkSeries(
        status="ok",
        symbol="H00300.CSI",
        name="300收益",
        version="v-300",
        returns={days[0]: 0.50, days[1]: 0.01, days[2]: 0.01},
    )
    sec1 = history_section(
        result, window=(days[0], days[-1]), benchmark=bench_base, trading_days=days
    )
    sec2 = history_section(
        result, window=(days[0], days[-1]), benchmark=bench_pre_jump, trading_days=days
    )
    SectionResult[HistorySection].model_validate(sec1)
    SectionResult[HistorySection].model_validate(sec2)

    pc1 = sec1["value"]["period_comparison"]
    pc2 = sec2["value"]["period_comparison"]
    assert pc1["status"] == "ok"
    assert pc1["window_actual"] == {"start": days[0], "end": days[-1]}
    assert pc1["sample_count"] == 2
    assert pc1["value"]["portfolio_simple_return"] == pytest.approx(0.0404, abs=1e-12)
    assert pc1["value"]["benchmark_simple_return"] == pytest.approx(0.0201, abs=1e-12)
    assert pc1["value"]["return_difference"] == pytest.approx(0.0203, abs=1e-12)
    assert pc1["value"]["benchmark_symbol"] == "H00300.CSI"
    assert pc1["value"]["benchmark_name"] == "300收益"
    assert pc1["value"]["benchmark_version"] == "v-300"
    assert pc2["value"] == pc1["value"]

    # 切换基准不改变组合净值序列，仅改变基准累计收益与差值
    bench_alt = BenchmarkSeries(
        status="ok",
        symbol="H00905.CSI",
        name="500收益",
        version="v-500",
        returns={days[1]: -0.02, days[2]: 0.0},
    )
    sec_alt = history_section(
        result, window=(days[0], days[-1]), benchmark=bench_alt, trading_days=days
    )
    assert sec_alt["value"]["replay"]["value"]["nav"] == sec1["value"]["replay"]["value"]["nav"]
    pc_alt = sec_alt["value"]["period_comparison"]
    assert pc_alt["value"]["benchmark_simple_return"] == pytest.approx(-0.02, abs=1e-12)
    assert pc_alt["value"]["return_difference"] == pytest.approx(0.0604, abs=1e-12)
    assert pc_alt["value"]["benchmark_name"] == "500收益"


def test_period_comparison_missing_day_validation_failure_negative_zero_and_truncation() -> None:
    """B3 边界：缺中间开市日、基准版本失配、未选基准、负/零收益、单点与截断。"""
    days = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    result = ReplayResult(
        tuple(
            ReplayPoint(d, v, D(0), D(0))
            for d, v in zip(days, [D("1.00"), D("0.95"), D("0.95")], strict=True)
        ),
        None,
        None,
        None,
    )

    # 缺中间开市日：不可用时省略 window_actual，sample_count 为已匹配数 1
    missing_mid = BenchmarkSeries(
        status="ok",
        symbol="H00300.CSI",
        name="300收益",
        version="v-300",
        returns={days[2]: 0.0},
    )
    sec_mid = history_section(
        result, window=(days[0], days[-1]), benchmark=missing_mid, trading_days=days
    )
    pc_mid = sec_mid["value"]["period_comparison"]
    assert pc_mid["status"] == "unavailable"
    assert pc_mid["reason_code"] == "history_insufficient"
    assert pc_mid["sample_count"] == 1
    assert pc_mid.get("window_actual") is None
    assert "2026-11-19" in pc_mid["reason"]

    # 版本未通过校验：data_not_validated，sample_count=0
    bad_ver = BenchmarkSeries(
        status="data_not_validated",
        symbol="H00300.CSI",
        name="300收益",
        version="bad-v",
        reason="整版哈希不匹配。",
    )
    sec_bad = history_section(
        result, window=(days[0], days[-1]), benchmark=bad_ver, trading_days=days
    )
    assert sec_bad["value"]["period_comparison"]["reason_code"] == "data_not_validated"
    assert sec_bad["value"]["period_comparison"]["sample_count"] == 0
    # 独立组合净值与回撤仍可用
    assert sec_bad["value"]["max_drawdown"]["status"] == "degraded"

    # 未选基准：benchmark_missing，sample_count=0
    sec_none = history_section(
        result,
        window=(days[0], days[-1]),
        benchmark=BenchmarkSeries(status="benchmark_missing"),
        trading_days=days,
    )
    assert sec_none["value"]["period_comparison"]["reason_code"] == "benchmark_missing"
    assert sec_none["value"]["period_comparison"]["sample_count"] == 0

    # 负收益与零收益
    zero_bench = BenchmarkSeries(
        status="ok",
        symbol="H00300.CSI",
        name="300收益",
        version="v-300",
        returns={days[1]: 0.0, days[2]: 0.0},
    )
    sec_neg = history_section(
        result, window=(days[0], days[-1]), benchmark=zero_bench, trading_days=days
    )
    assert sec_neg["value"]["period_comparison"]["value"][
        "portfolio_simple_return"
    ] == pytest.approx(-0.05)
    assert sec_neg["value"]["period_comparison"]["value"][
        "benchmark_simple_return"
    ] == pytest.approx(0.0)
    assert sec_neg["value"]["period_comparison"]["value"]["return_difference"] == pytest.approx(
        -0.05
    )

    # 仅一个可靠收盘点
    sec_one = history_section(
        result, window=(days[0], days[0]), benchmark=zero_bench, trading_days=[days[0]]
    )
    assert sec_one["value"]["period_comparison"]["status"] == "unavailable"
    assert sec_one["value"]["period_comparison"]["reason_code"] == "history_insufficient"
    assert sec_one["value"]["period_comparison"]["sample_count"] == 0

    # 越过截断日
    truncated = replace(
        result,
        points=result.points[:2],
        stopped_on=days[2],
        reason="delisted_no_terminal_value",
        instrument_id=33582,
    )
    sec_trunc = history_section(
        truncated, window=(days[0], days[2]), benchmark=zero_bench, trading_days=days
    )
    assert sec_trunc["value"]["period_comparison"]["status"] == "unavailable"
    assert sec_trunc["value"]["period_comparison"]["reason_code"] == "replay_terminated"


def test_four_day_drawdown_verification_and_report_text_blocks() -> None:
    """B3 回撤验算：1.00, 1.10, 0.88, 1.10 恢复与未恢复路径，以及零回撤与 7.5 兼容。"""
    days = [date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)]
    result = ReplayResult(
        tuple(
            ReplayPoint(d, v, D(0), D(0))
            for d, v in zip(days, [D("1.00"), D("1.10"), D("0.88"), D("1.10")], strict=True)
        ),
        None,
        None,
        None,
    )
    bench = BenchmarkSeries(
        status="ok",
        symbol="H00300.CSI",
        name="300收益",
        version="v-300",
        returns={days[1]: 0.01, days[2]: -0.02, days[3]: 0.03},
    )

    # 完整四日：峰 d2，谷 d3，最大回撤 -20%，恢复 d4，持续 2 个交易日间隔
    sec_full = history_section(
        result, window=(days[0], days[3]), benchmark=bench, trading_days=days
    )
    dd_full = sec_full["value"]["max_drawdown"]["value"]
    assert dd_full == {
        "value": pytest.approx(-0.2),
        "peak_date": days[1],
        "trough_date": days[2],
        "recovery_date": days[3],
        "duration_days": 2,
    }
    blocks_full = view._history_blocks(
        sec_full["value"], {"start": days[0].isoformat(), "end": days[3].isoformat()}
    )
    texts_full = [b["text"] for b in blocks_full if b["type"] == "text"]
    assert any("这篮子股票的假设历史回放" in t for t in texts_full)
    assert any("恢复日 2026-11-20" in t and "持续 2 个交易日间隔" in t for t in texts_full)
    assert any("300收益" in t and "共 3 个交易日收益" in t for t in texts_full)

    # 窗口止于第三日：尚未恢复，持续 1 个交易日间隔
    sec_unrec = history_section(
        result, window=(days[0], days[2]), benchmark=bench, trading_days=days[:3]
    )
    dd_unrec = sec_unrec["value"]["max_drawdown"]["value"]
    assert dd_unrec["recovery_date"] is None
    assert dd_unrec["duration_days"] == 1
    blocks_unrec = view._history_blocks(
        sec_unrec["value"], {"start": days[0].isoformat(), "end": days[2].isoformat()}
    )
    texts_unrec = [b["text"] for b in blocks_unrec if b["type"] == "text"]
    assert any("截至 2026-11-19 尚未恢复" in t and "持续 1 个交易日间隔" in t for t in texts_unrec)

    # 零回撤路径
    rising = ReplayResult(
        tuple(
            ReplayPoint(d, v, D(0), D(0))
            for d, v in zip(days[:3], [D("1.00"), D("1.05"), D("1.10")], strict=True)
        ),
        None,
        None,
        None,
    )
    sec_zero = history_section(
        rising, window=(days[0], days[2]), benchmark=bench, trading_days=days[:3]
    )
    blocks_zero = view._history_blocks(
        sec_zero["value"], {"start": days[0].isoformat(), "end": days[2].isoformat()}
    )
    assert any("窗口内无回撤" in b["text"] for b in blocks_zero if b["type"] == "text")

    # 兼容旧 7.5 快照（无 period_comparison 键）
    legacy_value = {k: v for k, v in sec_full["value"].items() if k != "period_comparison"}
    HistorySection.model_validate(legacy_value)
    legacy_blocks = view._history_blocks(
        legacy_value, {"start": days[0].isoformat(), "end": days[3].isoformat()}
    )
    cards = next(b["items"] for b in legacy_blocks if b["type"] == "metric_cards")
    assert not any(c["metric_id"].startswith("period_") for c in cards)
