"""批次 A（A1–A2）持仓仓位与风险贡献份额对照纯函数单测。"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import pytest
from gr_api.diagnosis_calc.exposure import UNCLASSIFIED
from gr_api.diagnosis_calc.holding_risk import compute_holding_risk_comparison
from gr_api.diagnosis_calc.metrics import degraded, ok, unavailable
from gr_api.diagnosis_calc.weights import InputRow, normalize_plan


ADMITTED = frozenset({"volatility", "risk_contribution_ratio"})


def _make_instrument(iid: int, symbol: str, name: str) -> dict[str, Any]:
    return {"instrument_id": iid, "symbol": symbol, "name": name}


def _make_fact(
    industry_code: str | None,
    industry_name: str | None = None,
) -> dict[str, Any]:
    return {
        "industry_code": industry_code,
        "industry_name": industry_name,
        "total_mv_yi": ok(1000.0, method="daily_basic"),
        "pb": ok(2.5, method="daily_basic"),
        "valuation_date": "2026-11-24",
        "roe": ok(0.15, method="fina_indicator"),
        "roe_report_year": 2025,
        "roe_ann_date": "2026-04-01",
    }


def _make_section_a(
    facts: dict[str, dict[str, Any]],
    dist: dict[str, float],
    *,
    industry_labels: dict[str, str] | None = None,
    dist_metric: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "ready",
        "value": {
            "industry_labels": industry_labels or {},
            "industry_distribution": dist_metric or ok(dist, method="exposure"),
            "instrument_facts": ok(facts, method="exposure"),
        },
    }


def _make_section_b(
    ratios: dict[str, float] | None,
    *,
    ratio_metric: dict[str, Any] | None = None,
    calibrated: bool = False,
    model_coverage_status: str | None = "complete",
    annual_variance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if ratio_metric is None:
        assert ratios is not None
        if calibrated:
            ratio_metric = ok(ratios, method="forward")
        else:
            ratio_metric = degraded(
                ratios,
                method="forward",
                reason_code="not_calibrated",
                reason="模型尚未完成全区间校准。",
                confidence="low",
            )
    coverage: dict[str, Any] | None = None
    if model_coverage_status is not None:
        coverage = {
            "status": model_coverage_status,
            "scope_type": "security_universe",
            "total_count": len(ratios or {}),
            "covered_count": len(ratios or {}) if model_coverage_status == "complete" else 0,
            "total_weight": "1",
            "covered_weight": "1" if model_coverage_status == "complete" else "0",
            "missing": [],
            "metrics": ["risk_contribution_ratio"],
            "reason": None if model_coverage_status == "complete" else "部分持仓缺模型输入",
        }
    return {
        "status": "ready",
        "value": {
            "model_id": "rq_v2",
            "model_date": "2026-11-24",
            "model_run_id": "run-001",
            "calibrated": calibrated,
            "model_coverage": coverage,
            "annual_variance": annual_variance or ok(0.04, method="forward"),
            "risk_contribution_ratio": ratio_metric,
        },
    }


def test_three_stock_signed_acceptance_example() -> None:
    """计划 §2 验收样例：10%/55%/35% vs 24%/80%/-4%，前两只同行业。"""
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("10"), "600519.SH", _make_instrument(1, "600519.SH", "甲股")
            ),
            InputRow(
                1, "600036.SH", Decimal("55"), "600036.SH", _make_instrument(2, "600036.SH", "乙股")
            ),
            InputRow(
                2, "000333.SZ", Decimal("35"), "000333.SZ", _make_instrument(3, "000333.SZ", "丙股")
            ),
        ]
    )
    section_a = _make_section_a(
        facts={
            "1": _make_fact("801120.SI", "食品饮料"),
            "2": _make_fact("801120.SI", "食品饮料"),
            "3": _make_fact("801110.SI", "家用电器"),
        },
        dist={"801120.SI": 0.65, "801110.SI": 0.35},
        industry_labels={"801120.SI": "食品饮料", "801110.SI": "家用电器"},
    )
    section_b = _make_section_b({"1": 0.24, "2": 0.80, "3": -0.04}, calibrated=False)

    res = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=section_a,
        section_b=section_b,
        declared_metrics=ADMITTED,
    )

    assert res["stocks"]["status"] == "degraded"
    assert res["stocks"]["reason_code"] == "not_calibrated"
    assert res["industries"]["status"] == "degraded"
    assert res["quantized_zero_count"] == 0
    assert res["quantized_zero_weight"] == "0"

    stocks = res["stocks"]["value"]
    assert [r["symbol"] for r in stocks] == ["600036.SH", "600519.SH", "000333.SZ"]
    assert stocks[0]["risk_share_minus_weight"] == pytest.approx(0.25)
    assert stocks[1]["risk_share_minus_weight"] == pytest.approx(0.14)
    assert stocks[2]["risk_share_minus_weight"] == pytest.approx(-0.39)
    assert sum(r["capital_weight"] for r in stocks) == pytest.approx(1.0)
    assert sum(r["risk_share"] for r in stocks) == pytest.approx(1.0)
    assert sum(r["risk_share_minus_weight"] for r in stocks) == pytest.approx(0.0)

    industries = res["industries"]["value"]
    assert [r["industry_code"] for r in industries] == ["801120.SI", "801110.SI"]
    assert industries[0]["capital_weight"] == pytest.approx(0.65)
    assert industries[0]["risk_share"] == pytest.approx(1.04)
    assert industries[0]["risk_share_minus_weight"] == pytest.approx(0.39)
    assert industries[1]["risk_share_minus_weight"] == pytest.approx(-0.39)
    assert sum(r["risk_share_minus_weight"] for r in industries) == pytest.approx(0.0)
    assert "乙股" in res["headline"]
    assert "高出仓位 25.0 个百分点" in res["headline"]


def test_single_stock_all_equal_and_negative_contribution_headlines() -> None:
    single = normalize_plan(
        [
            InputRow(
                0,
                "600519.SH",
                Decimal("1"),
                "600519.SH",
                _make_instrument(1, "600519.SH", "贵州茅台"),
            )
        ]
    )
    res_single = compute_holding_risk_comparison(
        plan_input=single.summary,
        section_a=_make_section_a({"1": _make_fact("801120.SI", "食品饮料")}, {"801120.SI": 1.0}),
        section_b=_make_section_b({"1": 1.0}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_single["stocks"]["status"] == "ok"
    assert "唯一有效持仓" in res_single["headline"]
    assert "高出仓位" not in res_single["headline"]

    pair = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("50"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600036.SH", Decimal("50"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    res_equal = compute_holding_risk_comparison(
        plan_input=pair.summary,
        section_a=_make_section_a(
            {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")}, {"A": 0.5, "B": 0.5}
        ),
        section_b=_make_section_b({"1": 0.5, "2": 0.5}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_equal["headline"] == "本方案各持仓的风险贡献份额与模型采用的资金权重基本一致。"
    assert [r["symbol"] for r in res_equal["stocks"]["value"]] == ["600036.SH", "600519.SH"]
    assert [r["industry_code"] for r in res_equal["industries"]["value"]] == ["A", "B"]

    # 单股负贡献且全组合份额合计 100%（1.20 与 -0.20）正常保留负值
    res_hedge = compute_holding_risk_comparison(
        plan_input=pair.summary,
        section_a=_make_section_a(
            {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")}, {"A": 0.5, "B": 0.5}
        ),
        section_b=_make_section_b({"1": 1.2, "2": -0.2}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_hedge["stocks"]["status"] == "ok"
    assert res_hedge["stocks"]["value"][0]["risk_share"] == pytest.approx(1.2)
    assert res_hedge["stocks"]["value"][1]["risk_share"] == pytest.approx(-0.2)
    assert res_hedge["stocks"]["value"][1]["risk_share_minus_weight"] == pytest.approx(-0.7)


def test_duplicate_holdings_155x3_vs_1071_matches_snapshot_quantization_and_rejects_tamper() -> (
    None
):
    """审核回归：同股三笔 155 与另一股 1071（和 1536）必须通过核验；篡改 1 个单位仍被拒绝。"""
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("155"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600519.SH", Decimal("155"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                2, "600519.SH", Decimal("155"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                3, "600036.SH", Decimal("1071"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    w1 = plan.summary["calculation_holdings"][0]["calculation_weight"]
    w2 = plan.summary["calculation_holdings"][1]["calculation_weight"]
    sec_a = _make_section_a(
        {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")},
        {"A": w1, "B": w2},
    )
    sec_b = _make_section_b({"1": 0.45, "2": 0.55}, calibrated=True)

    res = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res["stocks"]["status"] == "ok"
    assert res["industries"]["status"] == "ok"
    by_sym = {r["symbol"]: r for r in res["stocks"]["value"]}
    assert by_sym["600519.SH"]["capital_weight"] == pytest.approx(w1, abs=1e-12)
    assert by_sym["600036.SH"]["capital_weight"] == pytest.approx(w2, abs=1e-12)

    # 真实篡改冻结权重 1 个 1e-8 单位必须被拒绝
    tampered = {
        **plan.summary,
        "calculation_holdings": [
            {**plan.summary["calculation_holdings"][0], "calculation_weight": w1 + 1e-8},
            {**plan.summary["calculation_holdings"][1], "calculation_weight": w2 - 1e-8},
        ],
    }
    res_tampered = compute_holding_risk_comparison(
        plan_input=tampered,
        section_a=sec_a,
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res_tampered["stocks"]["status"] == "unavailable"
    assert res_tampered["stocks"]["reason_code"] == "data_not_validated"
    assert res_tampered["industries"]["status"] == "unavailable"


def test_duplicate_and_zero_weight_rows_merged_per_instrument() -> None:
    """同一证券出现零权重行和重复正权重行，合并后不掩盖非零持仓。"""
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("0"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600519.SH", Decimal("30"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                2, "600519.SH", Decimal("20"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                3, "600036.SH", Decimal("50"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    res = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")}, {"A": 0.5, "B": 0.5}
        ),
        section_b=_make_section_b({"1": 0.6, "2": 0.4}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res["stocks"]["status"] == "ok"
    assert res["quantized_zero_count"] == 0
    assert [r["symbol"] for r in res["stocks"]["value"]] == ["600519.SH", "600036.SH"]


def test_tiny_positive_weight_quantized_to_zero_is_disclosed_not_fabricated() -> None:
    """计划 §2 舍入样例：0.999999999 与 0.000000001 -> 模型仓位 1 与 0。"""
    plan = normalize_plan(
        [
            InputRow(
                0,
                "600519.SH",
                Decimal("0.999999999"),
                "600519.SH",
                _make_instrument(1, "600519.SH", "甲"),
            ),
            InputRow(
                1,
                "600036.SH",
                Decimal("0.000000001"),
                "600036.SH",
                _make_instrument(2, "600036.SH", "乙"),
            ),
        ]
    )
    res = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a({"1": _make_fact("A", "甲业")}, {"A": 1.0}),
        section_b=_make_section_b({"1": 1.0}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res["stocks"]["status"] == "ok"
    assert len(res["stocks"]["value"]) == 1
    assert res["stocks"]["value"][0]["instrument_id"] == 1
    assert res["stocks"]["value"][0]["capital_weight"] == 1.0
    assert res["quantized_zero_count"] == 1
    assert res["quantized_zero_weight"] == "0.000000001"


def test_equal_weight_three_way_tie_residual_assignment() -> None:
    """最大权重并列（3 只等权）的尾差归 instrument_id 最小者，核验通过。"""
    plan = normalize_plan(
        [
            InputRow(0, "600519.SH", None, "600519.SH", _make_instrument(30, "600519.SH", "丙")),
            InputRow(1, "600036.SH", None, "600036.SH", _make_instrument(10, "600036.SH", "甲")),
            InputRow(2, "000333.SZ", None, "000333.SZ", _make_instrument(20, "000333.SZ", "乙")),
        ]
    )
    res = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            {
                "10": _make_fact("A", "甲业"),
                "20": _make_fact("B", "乙业"),
                "30": _make_fact("C", "丙业"),
            },
            {"A": 0.33333334, "B": 0.33333333, "C": 0.33333333},
        ),
        section_b=_make_section_b({"10": 0.5, "20": 0.3, "30": 0.2}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res["stocks"]["status"] == "ok"
    by_id = {r["instrument_id"]: r for r in res["stocks"]["value"]}
    assert by_id[10]["capital_weight"] == pytest.approx(0.33333334, abs=1e-12)
    assert by_id[20]["capital_weight"] == pytest.approx(0.33333333, abs=1e-12)
    assert by_id[30]["capital_weight"] == pytest.approx(0.33333333, abs=1e-12)


def test_missing_evidence_or_non_conserving_risk_shares_blocked() -> None:
    """缺少准入清单、缺少 model_coverage 或风险份额合计偏离 100% 时一律停算。"""
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("50"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600036.SH", Decimal("50"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    sec_a = _make_section_a(
        {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")}, {"A": 0.5, "B": 0.5}
    )

    # 1. 缺 declared_metrics（None）
    res_no_decl = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b({"1": 0.6, "2": 0.4}, calibrated=True),
        declared_metrics=None,
    )
    assert res_no_decl["stocks"]["status"] == "unavailable"
    assert res_no_decl["stocks"]["reason_code"] == "feature_not_available"
    assert res_no_decl["headline"] is None

    # 2. 缺 model_coverage（None）
    res_no_cov = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b(
            {"1": 0.6, "2": 0.4}, calibrated=True, model_coverage_status=None
        ),
        declared_metrics=ADMITTED,
    )
    assert res_no_cov["stocks"]["status"] == "unavailable"
    assert res_no_cov["stocks"]["reason_code"] == "coverage_below_threshold"

    # 3. 风险份额合计 0.4 + 0.3 = 0.70（偏离 100%）
    res_bad_sum = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b({"1": 0.4, "2": 0.3}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_bad_sum["stocks"]["status"] == "unavailable"
    assert res_bad_sum["stocks"]["reason_code"] == "data_not_validated"
    assert res_bad_sum["industries"]["status"] == "unavailable"
    assert res_bad_sum["headline"] is None


def test_missing_valid_stock_or_tiny_unresolved_weight_blocks_comparison() -> None:
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("60"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600036.SH", Decimal("40"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    res_missing = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            {"1": _make_fact("A", "甲业"), "2": _make_fact("B", "乙业")}, {"A": 0.6, "B": 0.4}
        ),
        section_b=_make_section_b({"1": 1.0}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_missing["stocks"]["status"] == "unavailable"
    assert res_missing["stocks"]["reason_code"] == "data_not_validated"
    assert res_missing["industries"]["status"] == "unavailable"

    plan_unresolved = normalize_plan(
        [
            InputRow(
                0,
                "600519.SH",
                Decimal("0.999999999"),
                "600519.SH",
                _make_instrument(1, "600519.SH", "甲"),
            ),
            InputRow(1, "999999.SH", Decimal("0.000000001"), "999999.SH", None),
        ]
    )
    res_unresolved = compute_holding_risk_comparison(
        plan_input=plan_unresolved.summary,
        section_a=_make_section_a({"1": _make_fact("A", "甲业")}, {"A": 1.0}),
        section_b=_make_section_b({"1": 1.0}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_unresolved["stocks"]["status"] == "unavailable"
    assert res_unresolved["stocks"]["reason_code"] == "coverage_below_threshold"


def test_zero_variance_non_finite_and_unadmitted_metric_block() -> None:
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("1"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            )
        ]
    )
    sec_a = _make_section_a({"1": _make_fact("A", "甲业")}, {"A": 1.0})

    res_unadmitted = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b({"1": 1.0}, calibrated=True),
        declared_metrics={"volatility"},
    )
    assert res_unadmitted["stocks"]["status"] == "unavailable"
    assert res_unadmitted["stocks"]["reason_code"] == "feature_not_available"

    res_zero_var = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b(
            None,
            ratio_metric=unavailable(reason_code="zero_variance", reason="组合模型方差为零。"),
        ),
        declared_metrics=ADMITTED,
    )
    assert res_zero_var["stocks"]["status"] == "unavailable"
    assert res_zero_var["stocks"]["reason_code"] == "zero_variance"

    res_nan = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=sec_a,
        section_b=_make_section_b({"1": math.nan}, calibrated=True),
        declared_metrics=ADMITTED,
    )
    assert res_nan["stocks"]["status"] == "unavailable"
    assert res_nan["stocks"]["reason_code"] == "data_not_validated"


def test_industry_legacy_snapshot_partial_and_all_unclassified() -> None:
    """验证旧快照缺 industry_code、当日部分未分类、整组均未分类及体系不可用四种情况。"""
    plan = normalize_plan(
        [
            InputRow(
                0, "600519.SH", Decimal("60"), "600519.SH", _make_instrument(1, "600519.SH", "甲")
            ),
            InputRow(
                1, "600036.SH", Decimal("40"), "600036.SH", _make_instrument(2, "600036.SH", "乙")
            ),
        ]
    )
    sec_b = _make_section_b({"1": 0.7, "2": 0.3}, calibrated=True)

    # 1. 旧快照（<7.2）：冻结分布有已分类正权重，但逐股事实补出 industry_code=None
    #    -> 行业不可用，逐股照常可用
    res_legacy = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            facts={"1": _make_fact(None), "2": _make_fact(None)},
            dist={"801120.SI": 0.6, "801780.SI": 0.4},
        ),
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res_legacy["stocks"]["status"] == "ok"
    assert res_legacy["industries"]["status"] == "unavailable"
    assert res_legacy["industries"]["reason_code"] == "data_not_validated"

    # 2. 当日部分未分类：冻结分布与逐股重建一致 -> 正常输出并列明未分类桶
    res_partial = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            facts={"1": _make_fact("801120.SI", "食品饮料"), "2": _make_fact(None)},
            dist={"801120.SI": 0.6, UNCLASSIFIED: 0.4},
        ),
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res_partial["industries"]["status"] == "ok"
    ind_by_code = {r["industry_code"]: r for r in res_partial["industries"]["value"]}
    assert ind_by_code["801120.SI"]["risk_share_minus_weight"] == pytest.approx(0.1)
    assert ind_by_code[UNCLASSIFIED]["industry_name"] == "未分类"
    assert ind_by_code[UNCLASSIFIED]["capital_weight"] == pytest.approx(0.4)
    assert ind_by_code[UNCLASSIFIED]["risk_share_minus_weight"] == pytest.approx(-0.1)

    # 3. 整组确实均未分类：冻结分布也是 {unclassified: 1.0} -> 正常核对
    res_all_unclass = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            facts={"1": _make_fact(None), "2": _make_fact(None)},
            dist={UNCLASSIFIED: 1.0},
        ),
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res_all_unclass["industries"]["status"] == "ok"
    assert len(res_all_unclass["industries"]["value"]) == 1
    assert res_all_unclass["industries"]["value"][0]["industry_code"] == UNCLASSIFIED

    # 4. 行业体系整体不可用 -> 逐股正常，行业继承不可用
    res_no_scheme = compute_holding_risk_comparison(
        plan_input=plan.summary,
        section_a=_make_section_a(
            facts={"1": _make_fact(None), "2": _make_fact(None)},
            dist={},
            dist_metric=unavailable(
                reason_code="feature_not_available",
                reason="当前快照未配置行业分类体系。",
            ),
        ),
        section_b=sec_b,
        declared_metrics=ADMITTED,
    )
    assert res_no_scheme["stocks"]["status"] == "ok"
    assert res_no_scheme["industries"]["status"] == "unavailable"
    assert res_no_scheme["industries"]["reason_code"] == "feature_not_available"
