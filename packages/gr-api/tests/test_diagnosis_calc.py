"""持仓诊断纯计算模块：手算案例覆盖 PA-02、PA-04～PA-07、PA-13 与 §7.8 量化。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from gr_api.diagnosis_calc.coverage import apply_exposure_coverage
from gr_api.diagnosis_calc.exposure import (
    CalcHolding,
    IndustryAssignment,
    Valuation,
    band_key,
    compute_exposure,
    mktcap_bucket,
    pb_bucket,
    topn,
)
from gr_api.diagnosis_calc.weights import (
    WEIGHT_UNITS,
    InputRow,
    NoCalculableHoldingsError,
    normalize_plan,
    quantize_weights,
)
from gr_api.schemas.diagnosis_response import ExposureMetrics, PlanInputSummary


AS_OF = date(2026, 10, 29)
PARAMS = {"mktcap_bands_yi": [100, 500, 1000, 3000], "pb_bands": [1, 2, 4, 8]}


def _inst(iid: int, symbol: str | None = None) -> dict[str, object]:
    return {"instrument_id": iid, "symbol": symbol or f"60000{iid}.SH", "name": f"股票{iid}"}


def _row(idx: int, symbol: str, weight: str | None, iid: int | None) -> InputRow:
    return InputRow(
        input_index=idx,
        input_symbol=symbol,
        input_weight=None if weight is None else Decimal(weight),
        normalized_symbol=symbol,
        instrument=None if iid is None else _inst(iid, symbol),
    )


# ---------------------------------------------------------------- 量化与规范化


def test_quantize_weights_sums_exactly_and_breaks_ties_by_smallest_id() -> None:
    units = quantize_weights({3: Decimal(1), 1: Decimal(1), 2: Decimal(1)})
    assert sum(units.values()) == WEIGHT_UNITS
    # 1/3 → 33333333，残差 1 补给并列最大中 id 最小者
    assert units == {1: 33_333_334, 2: 33_333_333, 3: 33_333_333}


def test_quantize_weights_is_input_order_independent() -> None:
    a = quantize_weights({1: Decimal("0.7"), 2: Decimal("0.2"), 3: Decimal("0.1")})
    b = quantize_weights({3: Decimal("0.1"), 2: Decimal("0.2"), 1: Decimal("0.7")})
    assert a == b


def test_quantize_weights_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="positive"):
        quantize_weights({1: Decimal(0)})


def test_equal_weight_dedupes_before_splitting() -> None:
    """[A, A, B] 得到 A/B 各 50%，重复行回显合并关系。"""
    plan = normalize_plan(
        [
            _row(0, "600001.SH", None, 1),
            _row(1, "600001.SH", None, 1),
            _row(2, "600002.SH", None, 2),
        ]
    )
    PlanInputSummary.model_validate(plan.summary)
    assert plan.weight_mode == "equal"
    assert [h["status"] for h in plan.summary["holdings"]] == ["resolved", "duplicate", "resolved"]
    assert plan.summary["holdings"][1]["merged_into_input_index"] == 0
    assert [h["input_share"] for h in plan.summary["calculation_holdings"]] == [0.5, 0.5]
    assert plan.quantized == {1: 50_000_000, 2: 50_000_000}


def test_equal_weight_unknown_code_keeps_its_share_in_the_denominator() -> None:
    plan = normalize_plan([_row(0, "600001.SH", None, 1), _row(1, "BAD", None, None)])
    summary = plan.summary
    assert summary["resolved_weight"] == pytest.approx(0.5)
    assert summary["unresolved_weight"] == pytest.approx(0.5)
    assert summary["normalized_within_resolved_subset"] is True
    assert summary["calculation_holdings"][0]["calculation_weight"] == 1.0


def test_explicit_weights_use_raw_total_and_merge_aliases_by_instrument() -> None:
    """不同别名解析到同一 instrument_id 也算重复；份额按原始总和计算后再合并。"""
    rows = [
        _row(0, "000022.SZ", "30", 9),
        _row(1, "001872.SZ", "20", 9),
        _row(2, "BAD", "50", None),
    ]
    plan = normalize_plan(rows)
    assert [h["status"] for h in plan.summary["holdings"]] == [
        "resolved",
        "duplicate",
        "unresolved",
    ]
    assert plan.summary["calculation_holdings"][0]["input_share"] == pytest.approx(0.5)
    assert plan.summary["resolved_weight"] == pytest.approx(0.5)
    assert plan.quantized == {9: WEIGHT_UNITS}


def test_zero_and_quantized_to_zero_weights_are_echoed_but_not_counted() -> None:
    rows = [
        _row(0, "600001.SH", "1", 1),
        _row(1, "600002.SH", "0", 2),
        _row(2, "600003.SH", "0.000000001", 3),
    ]
    plan = normalize_plan(rows)
    PlanInputSummary.model_validate(plan.summary)
    assert [h["status"] for h in plan.summary["holdings"]] == [
        "resolved",
        "zero_weight",
        "zero_weight",
    ]
    assert [h["instrument_id"] for h in plan.summary["calculation_holdings"]] == [1]
    assert plan.quantized == {1: WEIGHT_UNITS}
    # 极小权重仍属已识别份额，不得被记成未识别
    assert plan.summary["unresolved_weight"] == 0
    assert plan.summary["normalized_within_resolved_subset"] is False


def test_plan_without_resolved_positive_holdings_is_rejected() -> None:
    with pytest.raises(NoCalculableHoldingsError):
        normalize_plan([_row(0, "BAD", "1", None), _row(1, "600001.SH", "0", 1)])


def test_full_resolution_has_exactly_zero_unresolved_share() -> None:
    """三等分的除法尾数不能让「全部识别」显示成存在未识别份额。"""
    plan = normalize_plan([_row(i, f"60000{i}.SH", "1", i) for i in range(1, 4)])
    assert plan.summary["unresolved_weight"] == 0
    assert plan.summary["resolved_weight"] == 1.0


# ---------------------------------------------------------------- TopN 与分档


def test_topn_returns_one_three_five_and_reports_actual_count() -> None:
    items = topn([Decimal("0.5"), Decimal("0.3"), Decimal("0.2")])
    assert items == [
        {"n": 1, "actual_count": 1, "weight": 0.5},
        {"n": 3, "actual_count": 3, "weight": 1.0},
        {"n": 5, "actual_count": 3, "weight": 1.0},
    ]


def test_topn_with_input_shares_excludes_unknown_share() -> None:
    items = topn([Decimal("0.4"), Decimal("0.1")])
    assert items[-1]["weight"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("99.99"), "lt_100"),
        (Decimal(100), "100_500"),  # 边界归较高档
        (Decimal(2999), "1000_3000"),
        (Decimal(3000), "ge_3000"),
    ],
)
def test_band_key_puts_boundaries_into_higher_band(value: Decimal, expected: str) -> None:
    assert band_key(value, [100, 500, 1000, 3000]) == expected


def test_band_key_rejects_unsorted_bands() -> None:
    with pytest.raises(ValueError, match="increasing"):
        band_key(Decimal(1), [2, 1])


def test_mktcap_converts_yuan_to_yi_once_and_separates_invalid() -> None:
    bands = [100, 500, 1000, 3000]
    assert mktcap_bucket(Decimal("5e10"), bands) == "500_1000"  # 500 亿元
    for invalid in (None, Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")):
        assert mktcap_bucket(invalid, bands) == "missing_or_invalid"


def test_pb_separates_non_positive_from_missing() -> None:
    bands = [1, 2, 4, 8]
    assert pb_bucket(Decimal("-0.5"), bands) == "non_positive"
    assert pb_bucket(Decimal(0), bands) == "non_positive"
    assert pb_bucket(None, bands) == "missing_or_invalid"
    assert pb_bucket(Decimal("NaN"), bands) == "missing_or_invalid"
    assert pb_bucket(Decimal(8), bands) == "ge_8"


# ---------------------------------------------------------------- 模块 A 计算


def _holdings(*pairs: tuple[int, str]) -> list[CalcHolding]:
    return [CalcHolding(instrument_id=i, weight=Decimal(w)) for i, w in pairs]


def test_exposure_scalars_on_concentrated_pair() -> None:
    metrics, _ = compute_exposure(
        _holdings((1, "0.8"), (2, "0.2")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme=None,
        industry={},
        category={},
        valuation={},
    )
    ExposureMetrics.model_validate(metrics)
    assert metrics["hhi"]["value"] == pytest.approx(0.68)
    assert metrics["l1_count"]["value"] == 2
    assert metrics["l2_effective_count"]["value"] == pytest.approx(1 / 0.68)


def test_unvalidated_industry_scheme_makes_industry_unavailable_not_empty() -> None:
    metrics, facts = compute_exposure(
        _holdings((1, "1")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme=None,
        industry={},
        category={},
        valuation={},
    )
    assert metrics["industry_distribution"]["reason_code"] == "data_not_validated"
    assert "value" not in metrics["max_industry"]
    assert "industry" not in facts["coverage"]


def test_industry_missing_bucket_is_kept_and_max_industry_ignores_it() -> None:
    metrics, facts = compute_exposure(
        _holdings((1, "0.3"), (2, "0.3"), (3, "0.4")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme="sw2021",
        industry={
            1: IndustryAssignment("801780", "银行"),
            2: IndustryAssignment("801780", "银行"),
        },
        category={},
        valuation={},
    )
    ExposureMetrics.model_validate(metrics)
    assert metrics["industry_distribution"]["value"] == {"801780": 0.6, "unclassified": 0.4}
    assert metrics["max_industry"]["value"] == {
        "industry_code": "801780",
        "industry_name": "银行",
        "weight": 0.6,
    }
    assert facts["coverage"]["industry"] == pytest.approx(0.6)
    assert facts["missing"]["industry"] == [3]


def test_valuation_buckets_lag_and_instrument_facts() -> None:
    valuation = {
        1: Valuation(AS_OF, Decimal("2e11"), Decimal("1.5")),  # 2000 亿元
        2: Valuation(date(2026, 10, 20), Decimal("5e9"), Decimal("-1")),  # 停牌滞后，50 亿元
    }
    metrics, facts = compute_exposure(
        _holdings((1, "0.5"), (2, "0.25"), (3, "0.25")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme=None,
        industry={},
        category={},
        valuation=valuation,
    )
    ExposureMetrics.model_validate(metrics)
    cap = metrics["mktcap_distribution"]["value"]
    assert cap["1000_3000"] == 0.5
    assert cap["lt_100"] == 0.25
    assert cap["missing_or_invalid"] == 0.25
    assert sum(cap.values()) == pytest.approx(1.0)
    pb = metrics["pb_distribution"]["value"]
    assert pb["1_2"] == 0.5
    assert pb["non_positive"] == 0.25
    assert facts["valuation_lagged"] == [2]
    assert facts["coverage"]["mktcap"] == pytest.approx(0.75)
    instrument = metrics["instrument_facts"]["value"]
    assert instrument["1"]["total_mv_yi"] == {
        "status": "ok",
        "value": 2000.0,
        "method": "exact",
        "confidence": "high",
    }
    assert instrument["2"]["pb"]["status"] == "degraded"
    assert instrument["2"]["pb"]["value"] == -1.0  # 非正值原值展示
    assert instrument["3"]["valuation_date"] is None
    assert instrument["3"]["total_mv_yi"]["status"] == "unavailable"
    assert instrument["1"]["roe"]["reason_code"] == "data_not_validated"


def test_exposure_rejects_empty_holdings() -> None:
    with pytest.raises(ValueError, match="at least one"):
        compute_exposure(
            [],
            as_of=AS_OF,
            params=PARAMS,
            industry_scheme=None,
            industry={},
            category={},
            valuation={},
        )


# ---------------------------------------------------------------- PA-13 覆盖率


def _cached_payload() -> tuple[dict, dict]:
    return compute_exposure(
        _holdings((1, "1")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme="sw2021",
        industry={1: IndustryAssignment("801780", "银行")},
        category={1: {"market": "cn_a", "asset_category": "equity"}},
        valuation={1: Valuation(AS_OF, Decimal("2e11"), Decimal("1.5"))},
    )


def test_cache_purity_example_two_requests_share_payload_but_not_status() -> None:
    """§7.8 验收例：A=100 与 A=50+UNKNOWN=50 复用同一载体，状态和 TopN 各自判定。"""
    metrics, facts = _cached_payload()
    frozen = repr(metrics)

    full = apply_exposure_coverage(
        metrics,
        calculation_holdings=[{"input_share": 1.0}],
        resolved_weight=1.0,
        facts=facts,
        params={},
    )
    half = apply_exposure_coverage(
        metrics,
        calculation_holdings=[{"input_share": 0.5}],
        resolved_weight=0.5,
        facts=facts,
        params={},
    )

    assert repr(metrics) == frozen  # 共享对象不被改写
    assert full["topn"]["value"][0]["weight"] == 1.0
    assert half["topn"]["status"] == "unavailable"
    assert half["hhi"]["status"] == "unavailable"
    # 带缺失档的分布只降级，不判不可用
    assert half["industry_distribution"]["status"] == "degraded"
    assert half["mktcap_distribution"]["value"]["1000_3000"] == 1.0
    assert full["hhi"]["status"] == "ok"


def test_coverage_between_thresholds_degrades_and_keeps_value() -> None:
    metrics, facts = _cached_payload()
    result = apply_exposure_coverage(
        metrics,
        calculation_holdings=[{"input_share": 0.9}],
        resolved_weight=0.9,
        facts=facts,
        params={},
    )
    assert result["topn"]["status"] == "degraded"
    assert result["topn"]["value"][0]["weight"] == pytest.approx(0.9)
    assert result["l1_count"]["status"] == "degraded"


def test_coverage_uses_metric_specific_data_coverage() -> None:
    """未识别为 0 但子集内 30% 缺行业：行业降级，HHI 不受影响。"""
    metrics, facts = compute_exposure(
        _holdings((1, "0.7"), (2, "0.3")),
        as_of=AS_OF,
        params=PARAMS,
        industry_scheme="sw2021",
        industry={1: IndustryAssignment("801780", "银行")},
        category={},
        valuation={},
    )
    result = apply_exposure_coverage(
        metrics,
        calculation_holdings=[{"input_share": 0.7}, {"input_share": 0.3}],
        resolved_weight=1.0,
        facts=facts,
        params={},
    )
    assert result["hhi"]["status"] == "ok"
    assert result["industry_distribution"]["status"] == "degraded"
    # 资产类别全部缺失：一般指标阈值，判为不可用
    assert result["market_distribution"]["status"] == "unavailable"


def test_coverage_respects_spec_version_thresholds() -> None:
    metrics, facts = _cached_payload()
    params = {
        "coverage_thresholds": {"_default": {"degraded": 0.7, "unavailable": 0.4}},
        "coverage_groups": {"_default": ["hhi"]},
    }
    result = apply_exposure_coverage(
        metrics,
        calculation_holdings=[{"input_share": 0.5}],
        resolved_weight=0.5,
        facts=facts,
        params=params,
    )
    assert result["hhi"]["status"] == "degraded"
    # 不在任何分组中的指标不套阈值
    assert result["l1_count"]["status"] == "ok"
