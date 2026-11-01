"""模块 B／D 的区块组装：历史口径与模型口径各自出数，互不顶替。

模型口径（米筐 v2）的波动率、风险贡献、L3／L4、模型相关性与风格暴露来自
:mod:`gr_api.diagnosis_calc.model_risk`；风险数据未取得时显式不可用，不以历史协方差替代
（PA-04、PA-10）。个股 Beta 依赖全收益基准，缺失时不回退价格指数（PA-11）。
某一口径不可用不影响另一口径已经可算的指标（DP-05）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gr_api.diagnosis_calc.history import METHOD, CorrelationView
from gr_api.diagnosis_calc.metrics import has_value, ok, unavailable
from gr_api.diagnosis_calc.model_risk import ModelRiskResult


MODEL_REASON = (
    "米筐 v2 风险模型数据尚未入库并按 D-022 发布，模型口径指标不可用，不以历史协方差替代。"
)
BENCHMARK_REASON = "全收益基准尚未接入，个股 Beta 与基准相关性不可用，不回退价格指数。"


def _model_unavailable() -> dict[str, Any]:
    return unavailable(reason_code="data_not_validated", reason=MODEL_REASON)


def _single_unavailable() -> dict[str, Any]:
    return unavailable(reason_code="not_applicable", reason="单只股票不适用两两相关性。")


def risk_section(
    instrument_ids: Sequence[int],
    volatility: Mapping[int, dict[str, Any]],
    model: ModelRiskResult | None = None,
) -> dict[str, Any]:
    """RiskSection 同形字典；逐股历史年化波动率（PA-20）与模型口径风险（PA-10）。"""
    benchmark_na = unavailable(reason_code="benchmark_missing", reason=BENCHMARK_REASON)

    def pick(name: str) -> dict[str, Any]:
        return _model_unavailable() if model is None else dict(getattr(model, name))

    vol = pick("volatility")
    return {
        # 一期 by_method 只含 forward，历史协方差估计的组合波动不展示（PA-10）
        "volatility": {
            "primary": "forward" if has_value(vol) else None,
            "by_method": {"forward": vol},
        },
        "instrument_betas": ok(
            [
                {
                    "instrument_id": iid,
                    "historical_volatility": volatility[iid],
                    "beta": dict(benchmark_na),
                    "benchmark_correlation": dict(benchmark_na),
                }
                for iid in instrument_ids
            ],
            method=METHOD,
        ),
        "risk_contribution": pick("risk_contribution"),
        "risk_contribution_ratio": pick("risk_contribution_ratio"),
        "marginal_risk_contribution": pick("marginal_risk_contribution"),
        "l3_effective_count": pick("l3_effective_count"),
        "l4_effective_count": pick("l4_effective_count"),
        "l4_market_source_share": pick("l4_market_source_share"),
        "l4_largest_source": pick("l4_largest_source"),
    }


def structure_section(
    view: CorrelationView,
    *,
    single_instrument: bool,
    model: ModelRiskResult | None = None,
) -> dict[str, Any]:
    """StructureSection 同形字典；primary 为模型口径，未算出时为 null，不以历史顶替。"""

    def forward(name: str) -> dict[str, Any]:
        if model is not None:
            return dict(getattr(model, name))
        return _single_unavailable() if single_instrument else _model_unavailable()

    matrix = forward("correlation")
    primary = "forward" if has_value(matrix) else None
    return {
        "correlation": {
            "primary": primary,
            "by_method": {"forward": matrix, "historical": view.matrix},
            "divergence": unavailable(
                reason_code="feature_not_available",
                reason="一期不生成两种口径的差异综合分（PA-09）。",
            ),
        },
        "avg_pairwise_correlation": {
            "primary": primary,
            "by_method": {"forward": forward("average_correlation"), "historical": view.average},
        },
        "high_correlation_pairs": {
            "primary": primary,
            "by_method": {
                "forward": forward("high_correlation_pairs"),
                "historical": view.high_pairs,
            },
        },
        "style_exposure": _model_unavailable() if model is None else dict(model.style_exposure),
        "hidden_exposure": unavailable(
            reason_code="feature_not_available", reason="隐性暴露的开放范围尚待审核。"
        ),
    }
