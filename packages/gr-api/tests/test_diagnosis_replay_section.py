from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from statistics import stdev

import pytest
from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult, Unfilled
from gr_api.diagnosis_calc.replay_section import history_section
from gr_api.schemas.diagnosis_response import HistorySection, SectionResult


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
