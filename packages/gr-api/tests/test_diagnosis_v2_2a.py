"""V2 批次 2A 回归测试：diag-publication-v4 全量模型风险与调仓前后对比。"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from gr_api.diagnosis_calc.comparison import compute_rebalance_comparison
from gr_api.diagnosis_calc.exposure import (
    CalcHolding,
    IndustryAssignment,
    Valuation,
    compute_exposure,
)
from gr_api.diagnosis_calc.history import correlation_view, historical_volatility
from gr_api.diagnosis_calc.metrics import degraded, ok, unavailable
from gr_api.diagnosis_calc.model_risk import RiskModelInputs
from gr_api.diagnosis_calc.sections import risk_section, structure_section
from gr_api.diagnosis_calc.weights import WEIGHT_UNITS, InputRow, normalize_plan
from gr_api.schemas.diagnosis import SnapshotRequest
from gr_api.schemas.diagnosis_response import (
    CalculationPayload,
    DiagnosisResult,
    PairComparison,
    ReportResponse,
    SharedReportResponse,
)
from gr_api.services import diagnosis as svc, diagnosis_presentation as view
from gr_api.services.diagnosis_scope import ENHANCED_METRICS, V4_MODEL_METRICS
from pydantic import ValidationError


AS_OF = date(2026, 11, 23)
SPEC = {
    "params": {
        "cov_methods": ["forward", "historical"],
        "mktcap_bands_yi": [100, 500, 1000, 3000],
        "pb_bands": [1, 2, 4, 8],
    }
}
OPTIONS = {
    "industry_scheme": "sw2021",
    "industry_scheme_version": "2021",
    "benchmark_instrument_id": None,
    "benchmark_version": None,
    "correlation_window": {"start": "2025-11-24", "end": "2026-11-23"},
    "beta_window": {"start": "2025-11-24", "end": "2026-11-23"},
    "replay_start": None,
    "stats_window": None,
}
STYLE_CODES = frozenset({"beta", "size", "momentum"})
FACTOR_CODES = ("comovement", "beta", "size", "momentum", "银行")
FACTOR_COV = np.array(
    [
        [0.040, 0.008, -0.003, 0.002, 0.005],
        [0.008, 0.025, -0.002, 0.004, 0.001],
        [-0.003, -0.002, 0.018, -0.001, 0.002],
        [0.002, 0.004, -0.001, 0.020, -0.001],
        [0.005, 0.001, 0.002, -0.001, 0.030],
    ],
    dtype=float,
)
EXPOSURES = {
    1: np.array([1.0, 0.6, 1.2, -0.3, 1.0]),
    2: np.array([1.0, -0.4, 0.8, 0.7, 0.0]),
    3: np.array([1.0, 0.9, -0.5, 1.1, 0.0]),
}
SPECIFIC_VAR = {1: 0.015, 2: 0.022, 3: 0.035}
META = {
    1: ("600036.SH", "招商银行", IndustryAssignment("801780", "银行")),
    2: ("600519.SH", "贵州茅台", IndustryAssignment("801120", "食品饮料")),
    3: ("300750.SZ", "宁德时代", IndustryAssignment("801730", "电力设备")),
}


def _risk_inputs() -> RiskModelInputs:
    return RiskModelInputs(
        factor_codes=FACTOR_CODES,
        factor_covariance=FACTOR_COV,
        exposures=EXPOSURES,
        specific_variance=SPECIFIC_VAR,
        market_factor="comovement",
        style_factors=STYLE_CODES,
    )


def _loaded_model(*, metrics: frozenset[str], calibrated: bool = False) -> svc.LoadedRiskModel:
    return svc.LoadedRiskModel(
        inputs=_risk_inputs(),
        model_id="rq_v2_test",
        model_version="v2",
        model_date=AS_OF,
        admission={
            "metrics": sorted(metrics),
            "calibrated": calibrated,
            "run_id": "run-v4-test",
            "receipt_id": "receipt-v4-test",
            "units_evidence": {"stored_variance": "pct2_annual"},
        },
    )


def _build_plan_row(
    plan_index: int,
    plan_id: str,
    label: str,
    holdings_spec: list[tuple[int, Decimal]],
    *,
    admitted_metrics: frozenset[str] = V4_MODEL_METRICS,
    calibrated: bool = False,
    unresolved_symbol: tuple[str, Decimal] | None = None,
    failed: bool = False,
) -> dict[str, Any]:
    rows: list[InputRow] = []
    for idx, (iid, w) in enumerate(holdings_spec):
        sym, name, _ = META[iid]
        rows.append(InputRow(idx, sym, w, sym, {"instrument_id": iid, "symbol": sym, "name": name}))
    if unresolved_symbol is not None:
        rows.append(
            InputRow(
                len(rows), unresolved_symbol[0], unresolved_symbol[1], unresolved_symbol[0], None
            )
        )
    normalized = normalize_plan(rows)
    if failed:
        return {
            "plan_index": plan_index,
            "plan_id": plan_id,
            "label": label,
            "weight_mode": normalized.weight_mode,
            "input_context": normalized.summary,
            "status": "failed",
            "payload": None,
            "data_quality": None,
        }
    calc_holdings = [
        CalcHolding(iid, Decimal(units) / WEIGHT_UNITS)
        for iid, units in sorted(normalized.quantized.items())
    ]
    ids = [h.instrument_id for h in calc_holdings]
    metrics_a, facts = compute_exposure(
        calc_holdings,
        as_of=AS_OF,
        params=SPEC["params"],
        industry_scheme="sw2021",
        industry={i: META[i][2] for i in ids},
        category={i: {"market": "cn_a", "asset_category": "equity"} for i in ids},
        valuation={i: Valuation(AS_OF, Decimal("5e11"), Decimal("2.5")) for i in ids},
    )
    loaded = _loaded_model(metrics=admitted_metrics, calibrated=calibrated)
    model = svc._scoped_risk(calc_holdings, loaded)
    hist_vols = {
        i: historical_volatility({}, window=(date(2025, 11, 24), AS_OF), min_samples=120)
        for i in ids
    }
    hist_corr = correlation_view(
        {i: {} for i in ids},
        window=(date(2025, 11, 24), AS_OF),
        min_samples=120,
        high_threshold=0.7,
    )
    risk = risk_section(ids, hist_vols, model)
    for metric_name in ("annual_variance", "daily_prediction_volatility"):
        risk[metric_name] = svc._wrap_admitted_metric(
            ok(model.facts[metric_name], method="forward"),
            calibrated=calibrated,
            reason="本次单日范围与指标已准入；全区间未校准。",
        )
    risk.update(annualization_days=252, model_run_id="run-v4-test", calibrated=calibrated)
    structure = structure_section(hist_corr, single_instrument=len(ids) == 1, model=model)
    facts["model"] = {
        **model.facts,
        "coverage": normalized.summary["resolved_weight"],
        "coverage_basis": "full_input",
    }
    payload = CalculationPayload.model_validate(
        {
            "cov": {
                "requested": ["forward", "historical"],
                "forward_model": {
                    "model_id": loaded.model_id,
                    "model_version": loaded.model_version,
                    "model_date": AS_OF,
                },
                "primary": "forward",
                "computed": ["forward"],
            },
            "section_a": {"status": "ready", "value": metrics_a},
            "section_b": {"status": "ready", "value": risk},
            "section_d": {"status": "ready", "value": structure},
            **{key: svc._unavailable_section(key) for key in svc.SECTION_REASONS},
        }
    ).model_dump(mode="json")
    return {
        "plan_index": plan_index,
        "plan_id": plan_id,
        "label": label,
        "weight_mode": normalized.weight_mode,
        "input_context": normalized.summary,
        "status": "partially_succeeded",
        "payload": payload,
        "data_quality": facts,
    }


def _snapshot(intent: str) -> dict[str, Any]:
    return {
        "snapshot_id": uuid4(),
        "resolved_spec_version": "v1-model-20261031",
        "resolved_as_of_date": AS_OF,
        "resolved_intent": intent,
        "data_fingerprint": "diag-v4-20261123-daily-fixture",
        "data_snapshot_at": datetime(2026, 11, 24, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "resolved_options": OPTIONS,
        "base_snapshot_id": None,
    }


def _portfolio_vol(weights: dict[int, float]) -> float:
    b = sum((w * EXPOSURES[i] for i, w in weights.items()), np.zeros(len(FACTOR_CODES)))
    fvar = float(b @ FACTOR_COV @ b)
    svar = sum(w * w * SPECIFIC_VAR[i] for i, w in weights.items())
    return math.sqrt(fvar + svar)


def test_scoped_risk_v4_admits_all_12_metrics_and_stores_comparison_vectors() -> None:
    holdings = [CalcHolding(1, Decimal("0.5")), CalcHolding(2, Decimal("0.5"))]
    v4 = svc._scoped_risk(holdings, _loaded_model(metrics=V4_MODEL_METRICS, calibrated=False))
    for metric in (
        v4.volatility,
        v4.risk_contribution,
        v4.risk_contribution_ratio,
        v4.marginal_risk_contribution,
        v4.l3_effective_count,
        v4.l4_effective_count,
        v4.l4_market_source_share,
        v4.l4_largest_source,
        v4.style_exposure,
        v4.correlation,
        v4.average_correlation,
        v4.high_correlation_pairs,
    ):
        assert metric["status"] == "degraded"
        assert metric["reason_code"] == "not_calibrated"
    assert set(v4.style_exposure["value"]) == STYLE_CODES
    assert v4.correlation["value"]["instrument_ids"] == [1, 2]
    assert v4.facts["factor_codes"] == list(FACTOR_CODES)
    assert len(v4.facts["portfolio_factor_exposure"]) == len(FACTOR_CODES)
    assert len(v4.facts["factor_cov_exposure"]) == len(FACTOR_CODES)
    assert set(v4.facts["holding_exposures"]) == {"1", "2"}
    assert set(v4.facts["holding_specific_var"]) == {"1", "2"}

    v4_cal = svc._scoped_risk(holdings, _loaded_model(metrics=V4_MODEL_METRICS, calibrated=True))
    assert v4_cal.l4_effective_count["status"] == "ok"
    assert v4_cal.style_exposure["status"] == "ok"
    assert v4_cal.correlation["status"] == "ok"


def test_snapshot_request_metrics_accepts_v4_and_rejects_unknown() -> None:
    req = SnapshotRequest.model_validate(
        {
            "metrics": sorted(V4_MODEL_METRICS),
            "plans": [{"plan_id": "p1", "holdings": [{"symbol": "600519.SH"}]}],
        }
    )
    assert req.metrics is not None and len(req.metrics) == 12
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(
            {
                "metrics": ["not_a_real_metric"],
                "plans": [{"plan_id": "p1", "holdings": [{"symbol": "600519.SH"}]}],
            }
        )


def test_comparison_marginal_impact_matches_finite_difference_with_new_stock() -> None:
    """含新增标的（stock 3）的一阶边际波动影响必须精确匹配有限差分方向导数。"""
    eps = 1e-6
    w_before = {1: Decimal("0.6"), 2: Decimal("0.4")}
    w_after_small = {
        1: Decimal("0.6") - Decimal(str(eps)),
        2: Decimal("0.4"),
        3: Decimal(str(eps)),
    }
    before_row = _build_plan_row(0, "before", "调仓前", list(w_before.items()), calibrated=True)
    after_row = _build_plan_row(1, "after", "调仓后", list(w_after_small.items()), calibrated=True)
    result = view.assemble(
        _snapshot("rebalance_holding"),
        SPEC,
        [before_row, after_row],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    pair = result["comparison"]["value"]["pairs"][0]
    PairComparison.model_validate(pair)

    fd = _portfolio_vol({k: float(v) for k, v in w_after_small.items()}) - _portfolio_vol(
        {k: float(v) for k, v in w_before.items()}
    )
    assert pair["marginal_impact"]["status"] == "ok"
    assert pair["marginal_impact"]["value"] == pytest.approx(fd, rel=1e-5, abs=1e-11)

    # 仅新增 stock 3：beta_new == EXPOSURES[3]，overlap_with_new == cos(beta_3, E_before)
    e_before = 0.6 * EXPOSURES[1] + 0.4 * EXPOSURES[2]
    expected_cos = float(
        (EXPOSURES[3] @ e_before) / (np.linalg.norm(EXPOSURES[3]) * np.linalg.norm(e_before))
    )
    assert pair["overlap_with_new"]["value"] == pytest.approx(expected_cos, rel=1e-12)
    assert pair["intent_effect_gap"] == []


@pytest.mark.parametrize(
    ("beta_new", "expected"),
    [
        (np.array([1.0, 0.0]), 1.0),
        (np.array([0.0, 1.0]), 0.0),
        (np.array([-1.0, 0.0]), -1.0),
    ],
)
def test_comparison_overlap_with_new_geometry(beta_new: np.ndarray, expected: float) -> None:
    def dummy_plan(pid: str, weights: list[tuple[int, float]]) -> dict[str, Any]:
        return {
            "plan_id": pid,
            "input": {
                "resolved_weight": 1.0,
                "calculation_holdings": [
                    {"instrument_id": i, "calculation_weight": w} for i, w in weights
                ],
            },
            "section_a": {"status": "unavailable"},
            "section_b": {
                "status": "ready",
                "value": {"volatility": {"by_method": {"forward": ok(0.2, method="forward")}}},
            },
            "section_d": {"status": "unavailable"},
        }

    e_before = np.array([1.0, 0.0])
    facts_before = {
        "run_id": "r1",
        "factor_codes": ["f1", "f2"],
        "portfolio_factor_exposure": e_before.tolist(),
        "factor_cov_exposure": [0.04, 0.0],
        "holding_exposures": {"1": e_before.tolist()},
        "holding_specific_var": {"1": 0.01},
        "portfolio_volatility": 0.2,
    }
    facts_after = {
        **facts_before,
        "holding_exposures": {"1": e_before.tolist(), "2": beta_new.tolist()},
        "holding_specific_var": {"1": 0.01, "2": 0.01},
    }
    pair = compute_rebalance_comparison(
        dummy_plan("b", [(1, 1.0)]),
        dummy_plan("a", [(1, 0.5), (2, 0.5)]),
        before_model_facts=facts_before,
        after_model_facts=facts_after,
    )
    assert pair["overlap_with_new"]["status"] == "ok"
    assert pair["overlap_with_new"]["value"] == pytest.approx(expected, abs=1e-12)


def test_comparison_edge_cases_identical_missing_and_mismatched_runs() -> None:
    row = _build_plan_row(0, "p1", "原方案", [(1, Decimal("0.5")), (2, Decimal("0.5"))])
    same = _build_plan_row(1, "p2", "相同方案", [(1, Decimal("0.5")), (2, Decimal("0.5"))])
    res_same = view.assemble(
        _snapshot("rebalance_amount"),
        SPEC,
        [row, same],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    pair = res_same["comparison"]["value"]["pairs"][0]
    assert pair["marginal_impact"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert pair["overlap_with_new"]["status"] == "unavailable"
    assert pair["overlap_with_new"]["reason_code"] == "not_applicable"
    assert pair["deltas"]["volatility"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert pair["deltas"]["volatility"]["status"] == "degraded"
    assert pair["deltas"]["volatility"]["reason_code"] == "not_calibrated"

    # 既有持仓加仓（stock 1 从 0.5 -> 0.6）不计入新增标的；仅新进入组合的标的算作新增。
    reweight_only = _build_plan_row(1, "p2", "仅调权", [(1, Decimal("0.6")), (2, Decimal("0.4"))])
    res_reweight = view.assemble(
        _snapshot("rebalance_amount"),
        SPEC,
        [row, reweight_only],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    p_rw = res_reweight["comparison"]["value"]["pairs"][0]
    assert p_rw["overlap_with_new"]["status"] == "unavailable"
    assert p_rw["overlap_with_new"]["reason_code"] == "not_applicable"

    # 同时加仓旧股 1（0.5 -> 0.6）并买入新股 3（0 -> 0.1）时，overlap_with_new 仅使用新股 3。
    add_and_topup = _build_plan_row(
        1, "p2", "加旧买新", [(1, Decimal("0.6")), (2, Decimal("0.3")), (3, Decimal("0.1"))]
    )
    res_mixed = view.assemble(
        _snapshot("rebalance_holding"),
        SPEC,
        [row, add_and_topup],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    p_mixed = res_mixed["comparison"]["value"]["pairs"][0]
    e_before = 0.5 * EXPOSURES[1] + 0.5 * EXPOSURES[2]
    expected_new_only = float(
        (EXPOSURES[3] @ e_before) / (np.linalg.norm(EXPOSURES[3]) * np.linalg.norm(e_before))
    )
    assert p_mixed["overlap_with_new"]["value"] == pytest.approx(expected_new_only, rel=1e-12)

    # 任一侧未识别代码时，模型对比指标与完整组合 delta 显式 unavailable。
    partial = _build_plan_row(
        1,
        "p2",
        "含未识别",
        [(1, Decimal("0.45")), (2, Decimal("0.45"))],
        unresolved_symbol=("BAD.SH", Decimal("0.10")),
    )
    res_partial = view.assemble(
        _snapshot("rebalance_holding"),
        SPEC,
        [row, partial],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    p_partial = res_partial["comparison"]["value"]["pairs"][0]
    assert p_partial["marginal_impact"]["status"] == "unavailable"
    assert p_partial["marginal_impact"]["reason_code"] == "coverage_below_threshold"
    assert p_partial["deltas"]["volatility"]["status"] == "unavailable"
    assert p_partial["deltas"]["daily_prediction_volatility"]["status"] == "unavailable"
    assert p_partial["deltas"]["hhi"]["status"] == "degraded"

    # 失败方案不崩溃，返回 unavailable comparison。
    failed = _build_plan_row(1, "p2", "失败", [(1, Decimal("1"))], failed=True)
    res_failed = view.assemble(
        _snapshot("rebalance_holding"),
        SPEC,
        [row, failed],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    assert res_failed["comparison"]["status"] == "unavailable"
    assert res_failed["comparison"]["reason_code"] == "not_applicable"
    ReportResponse.model_validate(view.report(res_failed))

    # 跨模型截面不混算。
    before_f = dict(row["data_quality"]["model"])
    after_f = {**same["data_quality"]["model"], "run_id": "different-run"}
    pair_diff = compute_rebalance_comparison(
        res_same["plans"][0],
        res_same["plans"][1],
        before_model_facts=before_f,
        after_model_facts=after_f,
    )
    assert pair_diff["marginal_impact"]["status"] == "unavailable"
    assert pair_diff["overlap_with_new"]["status"] == "unavailable"


@pytest.mark.parametrize("intent", ["rebalance_holding", "rebalance_amount"])
def test_rebalance_report_and_shared_report_validate_and_gate_v3_vs_v4(intent: str) -> None:
    before = _build_plan_row(0, "before", "调仓前", [(1, Decimal("0.6")), (2, Decimal("0.4"))])
    after = _build_plan_row(
        1, "after", "调仓后", [(1, Decimal("0.4")), (2, Decimal("0.3")), (3, Decimal("0.3"))]
    )
    result = view.assemble(
        _snapshot(intent),
        SPEC,
        [before, after],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    result["publication"] = {
        "scope_type": "security_universe",
        "scope_id": "adm-v4",
        "declared_metrics": sorted(V4_MODEL_METRICS),
        "status": "available",
        "recomputable": True,
        "invalidation_reasons": [],
        "model_run_id": "run-v4-test",
        "calibrated": False,
        "units_evidence": {"stored_variance": "pct2_annual"},
    }
    DiagnosisResult.model_validate(result)
    assert result["report_mode"] == "compare"
    assert result["comparison"]["status"] == "ready"
    pair = result["comparison"]["value"]["pairs"][0]
    assert pair["deltas"]["l1_count"]["value"] == pytest.approx(1.0)
    assert pair["deltas"]["volatility"]["status"] == "degraded"
    assert pair["deltas"]["l4_effective_count"]["status"] == "degraded"
    assert pair["deltas"]["avg_pairwise_correlation"]["status"] == "degraded"

    for level in ("retail", "pro"):
        rep = view.report(result, level)
        ReportResponse.model_validate(rep)
        by_id = {s["section_id"]: s for s in rep["sections"]}
        comp = by_id["comparison"]["content"]
        assert comp["status"] == "ready"
        assert comp["value"][0]["type"] == "text"
        cards = {c["metric_id"]: c for c in comp["value"][1]["items"]}
        assert "delta.volatility" in cards
        assert "delta.l4_effective_count" in cards
        assert "comparison.marginal_impact" in cards
        assert "comparison.overlap_with_new" in cards

        # v4 报告展示 L4 卡片与中文风格暴露标签
        risk_cards = {
            c["metric_id"]: c
            for b in by_id["before:risk"]["content"]["value"]
            if b["type"] == "metric_cards"
            for c in b["items"]
        }
        assert {"l4_effective_count", "l4_market_source_share", "l4_largest_source"} <= set(
            risk_cards
        )
        div_cards = {
            c["metric_id"]: c
            for b in by_id["before:diversification"]["content"]["value"]
            if b["type"] == "metric_cards"
            for c in b["items"]
        }
        assert div_cards["style_exposure:size"]["label"] == "风格暴露：市值"
        assert div_cards["style_exposure:momentum"]["label"] == "风格暴露：动量"

        # 分享白名单校验
        shared = SharedReportResponse.model_validate(
            {
                "report_mode": rep["report_mode"],
                "disclosures": rep["disclosures"],
                "sections": [
                    {"title": s["title"], "content": s["content"]}
                    for s in rep["sections"]
                    if s["kind"] != "instrument"
                ],
            }
        )
        assert any(
            s.title == "方案比较" and s.content.root.status == "ready" for s in shared.sections
        )

    # v3 快照仍严格屏蔽 L4 / 风格 / 模型相关性
    v3_row = _build_plan_row(
        0,
        "p_v3",
        "V3方案",
        [(1, Decimal("0.5")), (2, Decimal("0.5"))],
        admitted_metrics=ENHANCED_METRICS,
    )
    v3_res = view.assemble(
        _snapshot("single_portfolio"),
        SPEC,
        [v3_row],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    v3_res["publication"] = {
        "scope_type": "security_universe",
        "scope_id": "adm-v3",
        "declared_metrics": sorted(ENHANCED_METRICS),
        "status": "available",
        "recomputable": True,
        "invalidation_reasons": [],
        "model_run_id": "run-v3-test",
        "calibrated": False,
        "units_evidence": {"stored_variance": "pct2_annual"},
    }
    v3_rep = view.report(v3_res, "pro")
    ReportResponse.model_validate(v3_rep)
    v3_by_id = {s["section_id"]: s for s in v3_rep["sections"]}
    v3_risk_ids = {
        c["metric_id"]
        for b in v3_by_id["p_v3:risk"]["content"]["value"]
        if b["type"] == "metric_cards"
        for c in b["items"]
    }
    assert "l3_effective_count" in v3_risk_ids
    assert not any(mid.startswith("l4_") for mid in v3_risk_ids)
    v3_div_ids = {
        c["metric_id"]
        for b in v3_by_id["p_v3:diversification"]["content"]["value"]
        if b["type"] == "metric_cards"
        for c in b["items"]
    }
    assert not any(mid.startswith("style_exposure:") for mid in v3_div_ids)


def test_multi_portfolio_keeps_comparison_unavailable() -> None:
    p1 = _build_plan_row(0, "p1", "方案一", [(1, Decimal("0.5")), (2, Decimal("0.5"))])
    p2 = _build_plan_row(1, "p2", "方案二", [(2, Decimal("0.5")), (3, Decimal("0.5"))])
    res = view.assemble(
        _snapshot("multi_portfolio"),
        SPEC,
        [p1, p2],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    assert res["comparison"]["status"] == "unavailable"
    assert res["comparison"]["reason_code"] == "feature_not_available"
    assert (
        degraded(0.1, reason_code="not_calibrated", reason="x", method="forward")["status"]
        == "degraded"
    )
    assert unavailable(reason_code="not_applicable", reason="x")["status"] == "unavailable"


def test_comparison_removed_holding_and_zero_edge_cases() -> None:
    """清仓某股（w_after == 0）的边际影响、零波动与零范数暴露边界均须准确。"""
    eps = 1e-6
    w_before = {1: Decimal("0.5"), 2: Decimal("0.5")}
    # 股票 2 权重微减、股票 1 微增（含完全清仓方向的一致性）
    w_removed = {1: Decimal("1.0")}
    before_row = _build_plan_row(0, "b", "调仓前", list(w_before.items()), calibrated=True)
    removed_row = _build_plan_row(1, "a", "清仓后", list(w_removed.items()), calibrated=True)
    res_rm = view.assemble(
        _snapshot("rebalance_holding"),
        SPEC,
        [before_row, removed_row],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    pair_rm = res_rm["comparison"]["value"]["pairs"][0]
    # 手工复算精确一阶边际影响：stock 1 (+0.5), stock 2 (-0.5)
    e0 = 0.5 * EXPOSURES[1] + 0.5 * EXPOSURES[2]
    g0 = FACTOR_COV @ e0
    sig0 = _portfolio_vol({1: 0.5, 2: 0.5})
    mrc1 = (float(EXPOSURES[1] @ g0) + SPECIFIC_VAR[1] * 0.5) / sig0
    mrc2 = (float(EXPOSURES[2] @ g0) + SPECIFIC_VAR[2] * 0.5) / sig0
    assert pair_rm["marginal_impact"]["value"] == pytest.approx(0.5 * mrc1 - 0.5 * mrc2, rel=1e-12)
    # 纯清仓（无新进入标的）时 overlap_with_new 为 unavailable(not_applicable)
    assert pair_rm["overlap_with_new"]["status"] == "unavailable"
    assert pair_rm["overlap_with_new"]["reason_code"] == "not_applicable"

    # 沿清仓方向微小步长与有限差分一致
    fd = (_portfolio_vol({1: 0.5 + eps, 2: 0.5 - eps}) - sig0) / eps
    assert (mrc1 - mrc2) == pytest.approx(fd, rel=1e-5)

    # 零波动与零范数暴露
    dummy_b = {
        "plan_id": "b",
        "input": {
            "resolved_weight": 1.0,
            "calculation_holdings": [{"instrument_id": 1, "calculation_weight": 1.0}],
        },
        "section_a": {"status": "unavailable"},
        "section_b": {
            "status": "ready",
            "value": {"volatility": {"by_method": {"forward": ok(0.0, method="forward")}}},
        },
        "section_d": {"status": "unavailable"},
    }
    dummy_a = {
        "plan_id": "a",
        "input": {
            "resolved_weight": 1.0,
            "calculation_holdings": [{"instrument_id": 2, "calculation_weight": 1.0}],
        },
        "section_a": {"status": "unavailable"},
        "section_b": {
            "status": "ready",
            "value": {"volatility": {"by_method": {"forward": ok(0.2, method="forward")}}},
        },
        "section_d": {"status": "unavailable"},
    }
    zero_vol_facts = {
        "run_id": "r1",
        "factor_codes": ["f1"],
        "portfolio_factor_exposure": [0.0],
        "factor_cov_exposure": [0.0],
        "holding_exposures": {"1": [0.0], "2": [1.0]},
        "holding_specific_var": {"1": 0.0, "2": 0.01},
        "portfolio_volatility": 0.0,
    }
    p_zero = compute_rebalance_comparison(
        dummy_b, dummy_a, before_model_facts=zero_vol_facts, after_model_facts=zero_vol_facts
    )
    assert p_zero["marginal_impact"]["reason_code"] == "zero_variance"

    zero_norm_b = {
        **dummy_b,
        "section_b": {
            "status": "ready",
            "value": {"volatility": {"by_method": {"forward": ok(0.1, method="forward")}}},
        },
    }
    zero_norm_facts = {**zero_vol_facts, "portfolio_volatility": 0.1}
    p_zn = compute_rebalance_comparison(
        zero_norm_b, dummy_a, before_model_facts=zero_norm_facts, after_model_facts=zero_norm_facts
    )
    assert p_zn["marginal_impact"]["status"] == "ok"
    assert p_zn["overlap_with_new"]["reason_code"] == "zero_variance"


def test_rebalance_comparison_respects_v2_and_v3_protocol_admission_gates() -> None:
    """v2 屏蔽 marginal_impact/overlap；v3 允许 marginal_impact、屏蔽 overlap 与 L4 卡片。"""
    from gr_api.services.diagnosis_scope import METRICS as V2_METRICS

    for metrics, allow_marginal, allow_overlap in (
        (V2_METRICS, False, False),
        (ENHANCED_METRICS, True, False),
        (V4_MODEL_METRICS, True, True),
    ):
        b = _build_plan_row(
            0,
            "before",
            "旧方案",
            [(1, Decimal("0.6")), (2, Decimal("0.4"))],
            admitted_metrics=metrics,
        )
        a = _build_plan_row(
            1,
            "after",
            "新方案",
            [(1, Decimal("0.4")), (2, Decimal("0.3")), (3, Decimal("0.3"))],
            admitted_metrics=metrics,
        )
        res = view.assemble(
            _snapshot("rebalance_holding"),
            SPEC,
            [b, a],
            "partially_succeeded",
            report_mode=svc._report_mode,
        )
        res["publication"] = {
            "scope_type": "security_universe",
            "scope_id": "adm",
            "declared_metrics": sorted(metrics),
            "status": "available",
            "recomputable": True,
            "invalidation_reasons": [],
            "model_run_id": "run-v4-test",
            "calibrated": False,
            "units_evidence": {"stored_variance": "pct2_annual"},
        }
        pair = res["comparison"]["value"]["pairs"][0]
        assert (pair["marginal_impact"]["status"] != "unavailable") is allow_marginal
        assert (pair["overlap_with_new"]["status"] != "unavailable") is allow_overlap

        rep = view.report(res, "pro")
        ReportResponse.model_validate(rep)
        comp_section = next(s for s in rep["sections"] if s["section_id"] == "comparison")
        comp_ids = {
            c["metric_id"]
            for blk in comp_section["content"]["value"]
            if blk["type"] == "metric_cards"
            for c in blk["items"]
        }
        assert ("comparison.marginal_impact" in comp_ids) is allow_marginal
        assert ("comparison.overlap_with_new" in comp_ids) is allow_overlap
        assert ("delta.l4_effective_count" in comp_ids) is ("l4_effective_count" in metrics)
        assert ("delta.avg_pairwise_correlation" in comp_ids) is ("model_correlation" in metrics)


@pytest.mark.anyio
async def test_compute_plan_calibrated_true_marks_annual_variance_and_daily_vol_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """calibrated=True 时，annual_variance 与 daily_prediction_volatility 须为 ok。"""
    normalized = normalize_plan(
        [
            InputRow(
                0,
                "600036.SH",
                Decimal("1"),
                "600036.SH",
                {"instrument_id": 1, "symbol": "600036.SH", "name": "招商银行"},
            )
        ]
    )
    item = svc.PlanInput(
        0, "p1", "校准测试", [], normalized.weight_mode, normalized.summary, normalized.quantized
    )

    async def fake_industry(*args, **kwargs):
        return {1: META[1][2]}

    async def fake_category(*args, **kwargs):
        return {1: {"market": "cn_a", "asset_category": "equity"}}

    async def fake_valuation(*args, **kwargs):
        return {1: Valuation(AS_OF, Decimal("5e11"), Decimal("1.5"))}

    async def fake_roe(*args, **kwargs):
        return {}

    async def fake_prev(*args, **kwargs):
        return date(2025, 11, 21)

    async def fake_obs(db, ids, **kwargs):
        return {i: [] for i in ids}, {i: {} for i in ids}

    async def fake_load(*args, **kwargs):
        assessment = kwargs.get("assessment")
        if assessment is not None:
            assessment.update(status="complete", covered_count=1, covered_weight="1", reason=None)
        return _loaded_model(metrics=V4_MODEL_METRICS, calibrated=True)

    monkeypatch.setattr(svc, "_fetch_industry", fake_industry)
    monkeypatch.setattr(svc, "_fetch_category", fake_category)
    monkeypatch.setattr(svc, "_fetch_valuation", fake_valuation)
    monkeypatch.setattr(svc, "_fetch_annual_roe", fake_roe)
    monkeypatch.setattr(svc, "_trading_day_before", fake_prev)
    monkeypatch.setattr(svc, "_fetch_daily_observations", fake_obs)
    monkeypatch.setattr(svc, "_load_risk_model", fake_load)

    payload, _ = await svc._compute_plan(
        None,  # type: ignore[arg-type]
        item=item,
        spec=SPEC,
        as_of=AS_OF,
        options=OPTIONS,
    )
    sb = payload["section_b"]["value"]
    assert sb["volatility"]["by_method"]["forward"]["status"] == "ok"
    assert sb["annual_variance"]["status"] == "ok"
    assert sb["daily_prediction_volatility"]["status"] == "ok"
    assert sb["l4_effective_count"]["status"] == "ok"


@pytest.mark.anyio
async def test_load_risk_model_rejects_swapped_market_and_style_definitions() -> None:
    """v4 下 comovement 与 size 类型互换时，API 加载器必须拒绝，防止把风格因子当成市场源。"""
    from contextlib import asynccontextmanager
    from datetime import timezone

    from gr_api.services import diagnosis_publication as pub, diagnosis_scope

    all_factors = sorted(svc.V2_STYLE_FACTORS | {svc.V2_MARKET_FACTOR, "银行"})
    k = len(all_factors)
    cov_flat = [100.0 if i == j else 0.0 for i in range(k) for j in range(i, k)]
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)

    class SwappedDb:
        def __init__(self) -> None:
            self.q = ""

        @asynccontextmanager
        async def cursor(self, **kwargs):
            yield self

        async def execute(self, query, params=None):
            self.q = query

        async def fetchall(self):
            if "SELECT instrument_id,symbol" in self.q:
                return [{"instrument_id": 1, "symbol": "600036.SH"}]
            if "FROM factor.definition" in self.q:
                # 故意把 comovement 与 size 的 factor_type 互换
                out = []
                for code in all_factors:
                    if code == "comovement":
                        ftype = "style"
                    elif code == "size":
                        ftype = "market"
                    elif code in svc.V2_STYLE_FACTORS:
                        ftype = "style"
                    else:
                        ftype = "industry"
                    out.append({"factor_code": code, "factor_type": ftype})
                return out
            if "SELECT m.*" in self.q:
                return [
                    {
                        "run_id": "run",
                        "model_id": "m",
                        "model_version": "v2",
                        "metrics": sorted(V4_MODEL_METRICS),
                        "units_evidence": {"F": "annual"},
                        "evidence": {"l4_orth_verified": True},
                        "receipt_id": "receipt",
                        "horizon": "daily",
                        "trading_day": AS_OF,
                        "observed_at": now,
                        "source": "ricequant",
                        "annualization_basis": "annual_252",
                        "units": {
                            "model": "v2",
                            "covariance": "pct2_annual",
                            "specific_risk": "pct2_annual",
                        },
                        "factor_order": all_factors,
                        "calibrated": False,
                    }
                ]
            return [
                {
                    "instrument_id": 1,
                    "exposure": [1.0] * k,
                    "specific_var": 100.0,
                    "status": "included",
                    "exposure_at": now,
                    "specific_at": now,
                }
            ]

        async def fetchone(self):
            return {"cov_flat": cov_flat}

    ver = {
        "data_version_id": "v4-test",
        "as_of_date": AS_OF,
        "published_at": now,
        "contract_version": "diag-publication-v4",
        "available_options": {
            "publication_scope": {
                "scope_type": "security_universe",
                "as_of": str(AS_OF),
                "model": "v2",
                "run_id": "run",
                "metrics": sorted(V4_MODEL_METRICS),
                "calibrated": False,
                "security_ids": [1],
                "security_hash": "h",
                "universe_admission_id": "adm",
            }
        },
    }
    token = pub.current.set(pub.PublishedDiagnosticContext("v4-test", AS_OF, now, ver))
    try:
        details, orig = diagnosis_scope.initial_coverage(
            {
                "weight_mode": "user",
                "holdings": [
                    {
                        "instrument_id": 1,
                        "normalized_symbol": "600036.SH",
                        "input_weight": "1",
                    }
                ],
            }
        )
        loaded = await svc._load_risk_model(
            SwappedDb(),  # type: ignore[arg-type]
            [1],
            spec={
                "params": {
                    "cov_methods": ["forward"],
                    "forward_model_selector": {
                        "source": "ricequant",
                        "model": "v2",
                        "industry_mapping": "sws_2021",
                    },
                }
            },
            as_of=AS_OF,
            weights={1: Decimal("1")},
            assessment=details,
            input_weights=orig,
        )
        assert loaded is None
        assert details["reason"] == "risk_identity_or_units_mismatch"
    finally:
        pub.current.reset(token)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("unknown_w", "expected_avg_status"),
    [
        ("0.02", "degraded"),  # 98% >= 95%：保留平均相关（仅 not_calibrated）
        ("0.10", "degraded"),  # 90% in [80%, 95%)：按覆盖率降级
        ("0.30", "unavailable"),  # 70% < 80%：平均相关不可用，热力图仍保留 A/B
    ],
)
async def test_partial_coverage_preserves_model_correlation_matrix_per_pa13(
    monkeypatch: pytest.MonkeyPatch,
    unknown_w: str,
    expected_avg_status: str,
) -> None:
    """PA-13：少量缺失持仓时保留已覆盖股票 A/B 的模型相关矩阵，完整组合指标显式不可用。"""
    from contextlib import asynccontextmanager
    from datetime import timezone

    from gr_api.services import diagnosis_publication as pub

    all_factors = sorted(svc.V2_STYLE_FACTORS | {svc.V2_MARKET_FACTOR, "银行"})
    k = len(all_factors)
    cov_flat = [400.0 if i == j else 0.0 for i in range(k) for j in range(i, k)]
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    half_known = (Decimal("1") - Decimal(unknown_w)) / Decimal("2")

    class PartialV4Db:
        def __init__(self) -> None:
            self.q = ""

        @asynccontextmanager
        async def cursor(self, **kwargs):
            yield self

        async def execute(self, query, params=None):
            self.q = query

        async def fetchall(self):
            if "SELECT instrument_id,symbol" in self.q:
                return [
                    {"instrument_id": 1, "symbol": "600036.SH"},
                    {"instrument_id": 2, "symbol": "600519.SH"},
                ]
            if "FROM factor.definition" in self.q:
                return [
                    {
                        "factor_code": code,
                        "factor_type": (
                            "market"
                            if code == svc.V2_MARKET_FACTOR
                            else ("style" if code in svc.V2_STYLE_FACTORS else "industry")
                        ),
                    }
                    for code in all_factors
                ]
            if "SELECT m.*" in self.q:
                return [
                    {
                        "run_id": "run",
                        "model_id": "m",
                        "model_version": "v2",
                        "metrics": sorted(V4_MODEL_METRICS),
                        "units_evidence": {"F": "annual"},
                        "evidence": {"l4_orth_verified": True},
                        "receipt_id": "receipt",
                        "horizon": "daily",
                        "trading_day": AS_OF,
                        "observed_at": now,
                        "source": "ricequant",
                        "annualization_basis": "annual_252",
                        "units": {
                            "model": "v2",
                            "covariance": "pct2_annual",
                            "specific_risk": "pct2_annual",
                        },
                        "factor_order": all_factors,
                        "calibrated": False,
                    }
                ]
            return [
                {
                    "instrument_id": 1,
                    "exposure": [1.0] + [0.0] * (k - 1),
                    "specific_var": 100.0,
                    "status": "included",
                    "exposure_at": now,
                    "specific_at": now,
                },
                {
                    "instrument_id": 2,
                    "exposure": [1.0] + [0.0] * (k - 1),
                    "specific_var": 100.0,
                    "status": "included",
                    "exposure_at": now,
                    "specific_at": now,
                },
            ]

        async def fetchone(self):
            return {"cov_flat": cov_flat}

    ver = {
        "data_version_id": "v4-partial",
        "as_of_date": AS_OF,
        "published_at": now,
        "contract_version": "diag-publication-v4",
        "available_options": {
            "publication_scope": {
                "scope_type": "security_universe",
                "as_of": str(AS_OF),
                "model": "v2",
                "run_id": "run",
                "metrics": sorted(V4_MODEL_METRICS),
                "calibrated": False,
                "security_ids": [1, 2],
                "security_hash": "h",
                "universe_admission_id": "adm",
            }
        },
    }

    async def fake_industry(*args, **kwargs):
        return {1: META[1][2], 2: META[2][2]}

    async def fake_category(*args, **kwargs):
        return {
            1: {"market": "cn_a", "asset_category": "equity"},
            2: {"market": "cn_a", "asset_category": "equity"},
        }

    async def fake_valuation(*args, **kwargs):
        return {
            1: Valuation(AS_OF, Decimal("5e11"), Decimal("1.5")),
            2: Valuation(AS_OF, Decimal("1e12"), Decimal("5.0")),
        }

    async def fake_roe(*args, **kwargs):
        return {}

    async def fake_prev(*args, **kwargs):
        return date(2025, 11, 21)

    async def fake_obs(db, ids, **kwargs):
        return {i: [] for i in ids}, {i: {} for i in ids}

    monkeypatch.setattr(svc, "_fetch_industry", fake_industry)
    monkeypatch.setattr(svc, "_fetch_category", fake_category)
    monkeypatch.setattr(svc, "_fetch_valuation", fake_valuation)
    monkeypatch.setattr(svc, "_fetch_annual_roe", fake_roe)
    monkeypatch.setattr(svc, "_trading_day_before", fake_prev)
    monkeypatch.setattr(svc, "_fetch_daily_observations", fake_obs)

    spec_v4 = {
        "params": {
            **SPEC["params"],
            "forward_model_selector": {
                "source": "ricequant",
                "model": "v2",
                "industry_mapping": "sws_2021",
            },
        }
    }
    normalized = normalize_plan(
        [
            InputRow(
                0,
                "600036.SH",
                half_known,
                "600036.SH",
                {"instrument_id": 1, "symbol": "600036.SH", "name": "招商银行"},
            ),
            InputRow(
                1,
                "600519.SH",
                half_known,
                "600519.SH",
                {"instrument_id": 2, "symbol": "600519.SH", "name": "贵州茅台"},
            ),
            InputRow(2, "UNKNOWN.SH", Decimal(unknown_w), "UNKNOWN.SH", None),
        ]
    )
    item = svc.PlanInput(
        0,
        "partial",
        "部分覆盖",
        [],
        normalized.weight_mode,
        normalized.summary,
        normalized.quantized,
    )
    token = pub.current.set(pub.PublishedDiagnosticContext("v4-partial", AS_OF, now, ver))
    try:
        payload, facts = await svc._compute_plan(
            PartialV4Db(),  # type: ignore[arg-type]
            item=item,
            spec=spec_v4,
            as_of=AS_OF,
            options=OPTIONS,
        )
    finally:
        pub.current.reset(token)

    row = {
        "plan_index": 0,
        "plan_id": "partial",
        "label": "部分覆盖",
        "weight_mode": normalized.weight_mode,
        "input_context": normalized.summary,
        "status": "partially_succeeded",
        "payload": payload,
        "data_quality": facts,
    }
    result = view.assemble(
        _snapshot("single_portfolio"),
        spec_v4,
        [row],
        "partially_succeeded",
        report_mode=svc._report_mode,
    )
    plan = result["plans"][0]
    sb = plan["section_b"]["value"]
    sd = plan["section_d"]["value"]

    # 完整组合风险指标全部显式 unavailable(coverage_below_threshold)
    assert sb["volatility"]["by_method"]["forward"]["status"] == "unavailable"
    assert sb["volatility"]["by_method"]["forward"]["reason_code"] == "coverage_below_threshold"
    assert sb["annual_variance"]["status"] == "unavailable"
    assert sb["daily_prediction_volatility"]["status"] == "unavailable"
    assert sb["l4_effective_count"]["status"] == "unavailable"
    assert sd["style_exposure"]["status"] == "unavailable"
    assert sb["model_coverage"]["status"] == "incomplete"
    assert sb["model_coverage"]["covered_count"] == 2

    # 模型相关矩阵热力图保留已覆盖的 A/B（0.04 / (0.04 + 0.01) = 0.8）
    corr_m = sd["correlation"]["by_method"]["forward"]
    assert corr_m["status"] == "degraded"
    assert corr_m["value"]["instrument_ids"] == [1, 2]
    assert corr_m["value"]["matrix"][0][1] == pytest.approx(0.8, rel=1e-12)
    assert sd["correlation"]["primary"] == "forward"
    assert sd["avg_pairwise_correlation"]["by_method"]["forward"]["status"] == expected_avg_status
