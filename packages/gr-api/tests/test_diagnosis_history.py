"""历史统计纯计算：收益掩码（D-023）、PA-09 历史相关性与 PA-20 个股历史波动率。"""

from __future__ import annotations

import itertools
import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from gr_api.diagnosis_calc.history import (
    DailyObservation,
    correlation_view,
    daily_returns,
    historical_volatility,
    trading_status,
)
from gr_api.diagnosis_calc.sections import risk_section, structure_section
from gr_api.schemas.diagnosis_response import RiskSection, StructureSection
from gr_data.common.trading_status import resolve_trading_status


D0 = date(2026, 1, 5)
CAL = [D0 + timedelta(days=i) for i in range(8)]  # 测试用连续开市日
FLAGS = ("has_bar", "covered", "full_suspend", "intraday_suspend", "resumed")


def _obs(status: str = "NORMAL", price: str | None = "10") -> DailyObservation:
    return DailyObservation(status=status, adj_close=None if price is None else Decimal(price))


# ---------------------------------------------------------------- D-023 状态


def test_trading_status_matches_gr_data_for_every_flag_combination() -> None:
    combos = list(itertools.product([False, True], repeat=len(FLAGS)))
    expected = resolve_trading_status(pd.DataFrame(combos, columns=list(FLAGS)))
    actual = [trading_status(**dict(zip(FLAGS, combo, strict=True))) for combo in combos]
    assert actual == list(expected)


# ---------------------------------------------------------------- 日收益掩码


def test_returns_use_previous_trading_day_price_at_window_start() -> None:
    obs = {CAL[0]: _obs(price="10"), CAL[1]: _obs(price="11"), CAL[2]: _obs(price="9.9")}
    returns = daily_returns(CAL[:3], obs, window=(CAL[1], CAL[2]))
    assert returns == pytest.approx({CAL[1]: 0.1, CAL[2]: -0.1})


def test_full_suspension_and_resumption_return_are_excluded() -> None:
    obs = {
        CAL[0]: _obs(price="10"),
        CAL[1]: _obs(status="HALTED", price=None),
        CAL[2]: _obs(status="HALTED", price=None),
        CAL[3]: _obs(price="13"),  # 复牌：相对停牌前价的累计变化不能当单日收益
        CAL[4]: _obs(price="13.13"),
    }
    returns = daily_returns(CAL[:5], obs, window=(CAL[1], CAL[4]))
    assert returns == pytest.approx({CAL[4]: 0.01})


def test_intraday_halt_day_is_kept_in_sample() -> None:
    obs = {CAL[0]: _obs(price="10"), CAL[1]: _obs(status="INTRADAY_HALTED", price="10.5")}
    assert daily_returns(CAL[:2], obs, window=(CAL[1], CAL[1])) == pytest.approx({CAL[1]: 0.05})


@pytest.mark.parametrize(
    "gap",
    [
        _obs(status="UNKNOWN", price="10"),  # 状态未知
        _obs(price=None),  # 有状态但无价格
        _obs(price="0"),
        _obs(price="NaN"),
    ],
)
def test_gaps_break_the_chain_without_filling(gap: DailyObservation) -> None:
    obs = {CAL[0]: _obs(), CAL[1]: gap, CAL[2]: _obs(price="12")}
    assert daily_returns(CAL[:3], obs, window=(CAL[1], CAL[2])) == {}


def test_missing_calendar_day_is_a_gap_not_a_merge() -> None:
    obs = {CAL[0]: _obs(price="10"), CAL[2]: _obs(price="12")}  # CAL[1] 缺行
    assert daily_returns(CAL[:3], obs, window=(CAL[1], CAL[2])) == {}


def test_returns_outside_window_are_ignored() -> None:
    obs = {d: _obs(price=str(10 + i)) for i, d in enumerate(CAL)}
    returns = daily_returns(CAL, obs, window=(CAL[3], CAL[4]))
    assert sorted(returns) == [CAL[3], CAL[4]]


# ---------------------------------------------------------------- PA-20 波动率


def _series(values: list[float], start: date = D0) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_historical_volatility_uses_sample_std_and_sqrt_252() -> None:
    rng = np.random.default_rng(20261031)
    values = rng.normal(0, 0.02, 130).tolist()
    window = (D0, D0 + timedelta(days=200))
    metric = historical_volatility(_series(values), window=window, min_samples=120)
    assert metric["status"] == "ok"
    assert metric["value"] == pytest.approx(np.std(values, ddof=1) * math.sqrt(252))
    assert metric["sample_count"] == 130
    assert metric["window_actual"] == {"start": D0, "end": D0 + timedelta(days=129)}
    assert metric["window_target"] == {"start": window[0], "end": window[1]}


def test_historical_volatility_needs_120_samples_and_echoes_count() -> None:
    metric = historical_volatility(_series([0.01] * 119), window=(D0, D0), min_samples=120)
    assert metric["status"] == "unavailable"
    assert metric["reason_code"] == "history_insufficient"
    assert metric["sample_count"] == 119
    assert "value" not in metric


def test_constant_returns_give_zero_volatility_not_unavailable() -> None:
    metric = historical_volatility(_series([0.003] * 120), window=(D0, D0), min_samples=120)
    assert metric["status"] == "ok"
    assert metric["value"] == 0.0


# ---------------------------------------------------------------- PA-09 相关性


def _random(seed: int, n: int = 150) -> list[float]:
    return np.random.default_rng(seed).normal(0, 0.02, n).tolist()


def test_correlation_matrix_average_and_pairs_on_common_dates() -> None:
    a = _random(1)
    b = [2 * x for x in a]  # 与 a 完全正相关
    c = [-x for x in a]  # 与 a 完全负相关，不按绝对值计入高相关
    view = correlation_view(
        {3: _series(c), 1: _series(a), 2: _series(b)},
        window=(D0, D0 + timedelta(days=200)),
        min_samples=120,
        high_threshold=0.7,
    )
    matrix = view.matrix["value"]
    assert matrix["instrument_ids"] == [1, 2, 3]
    assert np.allclose(matrix["matrix"], [[1, 1, -1], [1, 1, -1], [-1, -1, 1]])
    assert view.average["value"] == pytest.approx((1 - 1 - 1) / 3)
    assert view.high_pairs["value"] == [
        {"left_instrument_id": 1, "right_instrument_id": 2, "correlation": pytest.approx(1.0)}
    ]
    assert view.matrix["sample_count"] == 150
    StructureSection.model_validate(structure_section(view, single_instrument=False))


def test_threshold_is_strict() -> None:
    a = _random(2)
    view = correlation_view(
        {1: _series(a), 2: _series(a)}, window=(D0, D0), min_samples=120, high_threshold=1.0
    )
    assert view.high_pairs["value"] == []


def test_whole_matrix_aligns_on_dates_common_to_all_holdings() -> None:
    a, b = _random(3), _random(4)
    short = _series(_random(5, 125), start=D0 + timedelta(days=30))  # 只覆盖后 125 日中的部分
    view = correlation_view(
        {1: _series(a), 2: _series(b), 3: short},
        window=(D0, D0 + timedelta(days=200)),
        min_samples=120,
        high_threshold=0.7,
    )
    assert view.matrix["sample_count"] == 120  # 第 30～149 日
    assert view.matrix["window_actual"]["start"] == D0 + timedelta(days=30)


def test_insufficient_common_samples_make_the_whole_view_unavailable() -> None:
    view = correlation_view(
        {1: _series(_random(6, 119)), 2: _series(_random(7, 119))},
        window=(D0, D0),
        min_samples=120,
        high_threshold=0.7,
    )
    for metric in (view.matrix, view.average, view.high_pairs):
        assert metric["reason_code"] == "history_insufficient"
        assert metric["sample_count"] == 119


def test_zero_variance_stock_is_excluded_and_disclosed_not_filled() -> None:
    a, b = _random(8), _random(9)
    view = correlation_view(
        {1: _series(a), 2: _series(b), 3: _series([0.0] * 150)},
        window=(D0, D0),
        min_samples=120,
        high_threshold=0.7,
    )
    assert view.excluded_zero_variance == [3]
    assert view.matrix["status"] == "degraded"
    assert view.matrix["reason_code"] == "zero_variance"
    assert view.matrix["value"]["instrument_ids"] == [1, 2]


def test_only_one_stock_with_variance_is_unavailable() -> None:
    view = correlation_view(
        {1: _series(_random(10)), 2: _series([0.0] * 150)},
        window=(D0, D0),
        min_samples=120,
        high_threshold=0.7,
    )
    assert view.matrix["reason_code"] == "zero_variance"


def test_single_instrument_is_not_applicable_including_model_view() -> None:
    view = correlation_view(
        {1: _series(_random(11))}, window=(D0, D0), min_samples=120, high_threshold=0.7
    )
    assert view.matrix["reason_code"] == "not_applicable"
    section = structure_section(view, single_instrument=True)
    assert section["avg_pairwise_correlation"]["by_method"]["forward"]["reason_code"] == (
        "not_applicable"
    )
    StructureSection.model_validate(section)


def test_risk_section_keeps_model_and_beta_unavailable_with_reasons() -> None:
    vol = historical_volatility(_series(_random(12)), window=(D0, D0), min_samples=120)
    section = risk_section([1], {1: vol})
    RiskSection.model_validate(section)
    row = section["instrument_betas"]["value"][0]
    assert row["historical_volatility"]["status"] == "ok"
    assert row["beta"]["reason_code"] == "benchmark_missing"
    assert section["volatility"]["by_method"]["forward"]["reason_code"] == "data_not_validated"
    assert section["l3_effective_count"]["reason_code"] == "data_not_validated"
