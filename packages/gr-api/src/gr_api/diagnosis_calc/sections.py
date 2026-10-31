"""模块 B／D 的区块组装：历史口径出数，模型口径与基准相关指标显式不可用。

模型口径（米筐 v2）的波动率、风险贡献、L3／L4、模型相关性与风格暴露依赖尚未发布的
风险数据，不以历史协方差替代（PA-04、PA-10）；个股 Beta 依赖全收益基准，缺失时不回退
价格指数（PA-11）。这些不可用不影响已经可算的历史指标（DP-05）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from gr_api.diagnosis_calc.history import METHOD, CorrelationView
from gr_api.diagnosis_calc.metrics import ok, unavailable


MODEL_REASON = (
    "米筐 v2 风险模型数据尚未入库并按 D-022 发布，模型口径指标不可用，不以历史协方差替代。"
)
BENCHMARK_REASON = "全收益基准尚未接入，个股 Beta 与基准相关性不可用，不回退价格指数。"


def _model_unavailable() -> dict[str, Any]:
    return unavailable(reason_code="data_not_validated", reason=MODEL_REASON)


def risk_section(
    instrument_ids: Sequence[int], volatility: Mapping[int, dict[str, Any]]
) -> dict[str, Any]:
    """RiskSection 同形字典；逐股只出历史年化波动率（PA-20）。"""
    benchmark_na = unavailable(reason_code="benchmark_missing", reason=BENCHMARK_REASON)
    return {
        # 一期 by_method 只含 forward，历史协方差估计的组合波动不展示（PA-10）
        "volatility": {"primary": None, "by_method": {"forward": _model_unavailable()}},
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
        "risk_contribution": _model_unavailable(),
        "risk_contribution_ratio": _model_unavailable(),
        "marginal_risk_contribution": _model_unavailable(),
        "l3_effective_count": _model_unavailable(),
        "l4_effective_count": _model_unavailable(),
        "l4_market_source_share": _model_unavailable(),
        "l4_largest_source": _model_unavailable(),
    }


def structure_section(view: CorrelationView, *, single_instrument: bool) -> dict[str, Any]:
    """StructureSection 同形字典；primary 为模型口径，未算出时为 null，不以历史顶替。"""

    def forward() -> dict[str, Any]:
        if single_instrument:
            return unavailable(reason_code="not_applicable", reason="单只股票不适用两两相关性。")
        return _model_unavailable()

    return {
        "correlation": {
            "primary": None,
            "by_method": {"forward": forward(), "historical": view.matrix},
            "divergence": unavailable(
                reason_code="feature_not_available",
                reason="一期不生成两种口径的差异综合分（PA-09）。",
            ),
        },
        "avg_pairwise_correlation": {
            "primary": None,
            "by_method": {"forward": forward(), "historical": view.average},
        },
        "high_correlation_pairs": {
            "primary": None,
            "by_method": {"forward": forward(), "historical": view.high_pairs},
        },
        "style_exposure": _model_unavailable(),
        "hidden_exposure": unavailable(
            reason_code="feature_not_available", reason="隐性暴露的开放范围尚待审核。"
        ),
    }
