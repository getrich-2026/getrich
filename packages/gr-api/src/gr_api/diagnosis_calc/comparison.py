"""调仓前后客观对比纯计算（D-021：仅依赖标准库、numpy 与 metrics）。

针对 ``rebalance_holding`` / ``rebalance_amount`` 双方案快照（``plans[0]`` -> ``plans[1]``），
基于已持久化的 per-plan 诊断载体与紧凑风险模型向量计算：

* ``deltas``：核心标量指标的 ``after - before`` 变化量，严守三态传播；
* ``marginal_impact``：以调仓前组合为基点的一阶边际波动影响估算
  ``sum_i MRC_i^{before} * (w_i^{after} - w_i^{before})``，对新增标的同样使用
  ``MRC_i^{before} = (beta_i^T g_{before} + d_i w_i^{before}) / sigma_{before}``；
* ``overlap_with_new``：仅对新进入组合的标的（``w_i^{before} == 0`` 且 ``w_i^{after} > 0``）
  按调仓后权重归一化求暴露向量，与调仓前组合暴露求余弦相似度 ``cos(beta_{new}, E_{before})``；
  无新进入标的时显式返回 ``unavailable(not_applicable)``；
* ``intent_effect_gap``：当前不新增请求字段，固定返回空列表 ``[]``。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from gr_api.diagnosis_calc.metrics import degraded, has_value, ok, unavailable


DELTA_METHOD = "rebalance_delta"
MODEL_METHOD = "forward"

_WEIGHT_EPS = 1e-12
_NORM_EPS = 1e-12
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _topn_weight(n: int) -> Callable[[Any], float]:
    def extract(items: Any) -> float:
        for item in items:
            if item["n"] == n:
                return float(item["weight"])
        raise KeyError(f"topn missing n={n}")

    return extract


def _metric_delta(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    *,
    extract: Callable[[Any], float] | None = None,
) -> dict[str, Any]:
    """计算标量 ``after - before`` 变化量并传播 degraded / unavailable 状态。"""
    if before is None or after is None:
        return unavailable(
            reason_code="data_not_validated",
            reason="调仓前后缺少对应指标，无法计算变化量。",
        )
    if not has_value(before):
        return unavailable(
            reason_code=str(before["reason_code"]),
            reason=f"调仓前该指标不可用：{before['reason']}",
        )
    if not has_value(after):
        return unavailable(
            reason_code=str(after["reason_code"]),
            reason=f"调仓后该指标不可用：{after['reason']}",
        )
    v_before = float(extract(before["value"]) if extract is not None else before["value"])
    v_after = float(extract(after["value"]) if extract is not None else after["value"])
    diff = v_after - v_before
    if not math.isfinite(diff):
        return unavailable(
            reason_code="data_not_validated",
            reason="调仓前后指标变化量非有限数。",
        )
    degraded_sides = [m for m in (before, after) if m.get("status") == "degraded"]
    if degraded_sides:
        chosen = min(
            degraded_sides,
            key=lambda m: _CONFIDENCE_RANK.get(str(m.get("confidence", "medium")), 1),
        )
        return degraded(
            diff,
            reason_code=str(chosen["reason_code"]),
            reason=str(chosen["reason"]),
            method=DELTA_METHOD,
            confidence=str(chosen.get("confidence", "medium")),
        )
    return ok(diff, method=DELTA_METHOD)


def _section_value(plan: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    section = plan.get(key)
    if isinstance(section, Mapping) and section.get("status") == "ready":
        value = section.get("value")
        if isinstance(value, Mapping):
            return value
    return {}


def _weights_map(plan: Mapping[str, Any]) -> dict[str, float]:
    holdings = (plan.get("input") or {}).get("calculation_holdings") or []
    return {str(h["instrument_id"]): float(h["calculation_weight"]) for h in holdings}


def _model_vectors_ready(
    before_plan: Mapping[str, Any],
    after_plan: Mapping[str, Any],
    before_facts: Mapping[str, Any] | None,
    after_facts: Mapping[str, Any] | None,
) -> tuple[
    tuple[np.ndarray, np.ndarray, float, dict[str, np.ndarray], dict[str, float], dict[str, Any]]
    | None,
    dict[str, Any] | None,
]:
    """校验双方案是否共享有效且完整覆盖的模型截面向量，返回向量包或不可用结果。"""
    if float((before_plan.get("input") or {}).get("resolved_weight", 0.0)) < 1.0 - 1e-9:
        return None, unavailable(
            reason_code="coverage_below_threshold",
            reason="调仓前存在未识别代码，不计算模型调仓对比指标。",
        )
    if float((after_plan.get("input") or {}).get("resolved_weight", 0.0)) < 1.0 - 1e-9:
        return None, unavailable(
            reason_code="coverage_below_threshold",
            reason="调仓后存在未识别代码，不计算模型调仓对比指标。",
        )

    b_sec = _section_value(before_plan, "section_b")
    a_sec = _section_value(after_plan, "section_b")
    b_vol_m = ((b_sec.get("volatility") or {}).get("by_method") or {}).get("forward")
    a_vol_m = ((a_sec.get("volatility") or {}).get("by_method") or {}).get("forward")
    if not (b_vol_m and has_value(b_vol_m) and a_vol_m and has_value(a_vol_m)):
        return None, unavailable(
            reason_code="data_not_validated",
            reason="调仓前后至少一方缺少有效模型波动率，无法计算模型调仓对比指标。",
        )
    if not before_facts or not after_facts:
        return None, unavailable(
            reason_code="data_not_validated",
            reason="缺少持久化的风险模型向量摘要，无法计算模型调仓对比指标。",
        )

    required_keys = (
        "factor_codes",
        "portfolio_factor_exposure",
        "factor_cov_exposure",
        "holding_exposures",
        "holding_specific_var",
        "portfolio_volatility",
    )
    if any(k not in before_facts or k not in after_facts for k in required_keys):
        return None, unavailable(
            reason_code="data_not_validated",
            reason="模型缓存缺少调仓对比向量，请重新提交诊断。",
        )

    if before_facts.get("run_id") != after_facts.get("run_id") or list(
        before_facts["factor_codes"]
    ) != list(after_facts["factor_codes"]):
        return None, unavailable(
            reason_code="data_not_validated",
            reason="调仓前后未共享同一风险模型截面，无法计算跨方案模型对比。",
        )

    sigma_before = float(before_facts["portfolio_volatility"])
    if not math.isfinite(sigma_before) or sigma_before < 0:
        return None, unavailable(
            reason_code="data_not_validated",
            reason="调仓前组合模型波动率数值非法。",
        )
    if sigma_before == 0:
        return None, unavailable(
            reason_code="zero_variance",
            reason="调仓前组合模型波动率为零，无法计算边际波动影响。",
        )

    e_before = np.asarray(before_facts["portfolio_factor_exposure"], dtype=float)
    g_before = np.asarray(before_facts["factor_cov_exposure"], dtype=float)
    k = len(before_facts["factor_codes"])
    if (
        e_before.shape != (k,)
        or g_before.shape != (k,)
        or not np.isfinite(e_before).all()
        or not np.isfinite(g_before).all()
    ):
        return None, unavailable(
            reason_code="data_not_validated",
            reason="风险模型暴露向量维度或数值非法。",
        )

    exposures: dict[str, np.ndarray] = {}
    specific_var: dict[str, float] = {}
    for facts in (before_facts, after_facts):
        for iid, vec in (facts.get("holding_exposures") or {}).items():
            arr = np.asarray(vec, dtype=float)
            if arr.shape != (k,) or not np.isfinite(arr).all():
                return None, unavailable(
                    reason_code="data_not_validated",
                    reason="持仓因子暴露向量维度或数值非法。",
                )
            exposures[str(iid)] = arr
        for iid, var in (facts.get("holding_specific_var") or {}).items():
            val = float(var)
            if not math.isfinite(val) or val < 0:
                return None, unavailable(
                    reason_code="data_not_validated",
                    reason="持仓特质方差数值非法。",
                )
            specific_var[str(iid)] = val

    degraded_sides = [m for m in (b_vol_m, a_vol_m) if m.get("status") == "degraded"]
    degraded_meta: dict[str, Any] = {}
    if degraded_sides:
        chosen = min(
            degraded_sides,
            key=lambda m: _CONFIDENCE_RANK.get(str(m.get("confidence", "medium")), 1),
        )
        degraded_meta = {
            "reason_code": str(chosen["reason_code"]),
            "reason": str(chosen["reason"]),
            "confidence": str(chosen.get("confidence", "medium")),
        }
    return (e_before, g_before, sigma_before, exposures, specific_var, degraded_meta), None


def _admitted_gate(
    before_facts: Mapping[str, Any] | None,
    after_facts: Mapping[str, Any] | None,
    required_metric: str,
) -> bool:
    """若任一侧携带发布准入清单 ``metrics``，则要求双方均显式准入对应指标。"""
    has_scope = bool(
        (before_facts and before_facts.get("metrics") is not None)
        or (after_facts and after_facts.get("metrics") is not None)
    )
    if not has_scope:
        return True
    before_metrics = set((before_facts or {}).get("metrics") or ())
    after_metrics = set((after_facts or {}).get("metrics") or ())
    return required_metric in before_metrics and required_metric in after_metrics


def _wrap_model_scalar(value: float, degraded_meta: Mapping[str, Any]) -> dict[str, Any]:
    if degraded_meta:
        return degraded(
            value,
            reason_code=str(degraded_meta["reason_code"]),
            reason=str(degraded_meta["reason"]),
            method=MODEL_METHOD,
            confidence=str(degraded_meta.get("confidence", "medium")),
        )
    return ok(value, method=MODEL_METHOD)


def compute_rebalance_comparison(
    before_plan: Mapping[str, Any],
    after_plan: Mapping[str, Any],
    *,
    before_model_facts: Mapping[str, Any] | None = None,
    after_model_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """计算调仓前后（``before_plan`` -> ``after_plan``）的 ``PairComparison`` 同形字典。

    Args:
        before_plan: 调仓前已组装方案字典（``plans[0]``）。
        after_plan: 调仓后已组装方案字典（``plans[1]``）。
        before_model_facts: 调仓前方案的 ``data_quality["model"]`` 事实字典。
        after_model_facts: 调仓后方案的 ``data_quality["model"]`` 事实字典。

    Returns:
        符合 :class:`gr_api.schemas.diagnosis_response.PairComparison` 结构的字典。
    """
    ba = _section_value(before_plan, "section_a")
    aa = _section_value(after_plan, "section_a")
    bb = _section_value(before_plan, "section_b")
    ab = _section_value(after_plan, "section_b")
    bd = _section_value(before_plan, "section_d")
    ad = _section_value(after_plan, "section_d")

    deltas: dict[str, dict[str, Any]] = {
        "top1": _metric_delta(ba.get("topn"), aa.get("topn"), extract=_topn_weight(1)),
        "top3": _metric_delta(ba.get("topn"), aa.get("topn"), extract=_topn_weight(3)),
        "top5": _metric_delta(ba.get("topn"), aa.get("topn"), extract=_topn_weight(5)),
        "hhi": _metric_delta(ba.get("hhi"), aa.get("hhi")),
        "l1_count": _metric_delta(ba.get("l1_count"), aa.get("l1_count")),
        "l2_effective_count": _metric_delta(
            ba.get("l2_effective_count"), aa.get("l2_effective_count")
        ),
        "max_industry": _metric_delta(
            ba.get("max_industry"),
            aa.get("max_industry"),
            extract=lambda v: float(v["weight"]),
        ),
        "volatility": _metric_delta(
            ((bb.get("volatility") or {}).get("by_method") or {}).get("forward"),
            ((ab.get("volatility") or {}).get("by_method") or {}).get("forward"),
        ),
        "daily_prediction_volatility": _metric_delta(
            bb.get("daily_prediction_volatility"), ab.get("daily_prediction_volatility")
        ),
        "l3_effective_count": _metric_delta(
            bb.get("l3_effective_count"), ab.get("l3_effective_count")
        ),
        "l4_effective_count": _metric_delta(
            bb.get("l4_effective_count"), ab.get("l4_effective_count")
        ),
        "l4_market_source_share": _metric_delta(
            bb.get("l4_market_source_share"), ab.get("l4_market_source_share")
        ),
        "avg_pairwise_correlation": _metric_delta(
            ((bd.get("avg_pairwise_correlation") or {}).get("by_method") or {}).get("forward"),
            ((ad.get("avg_pairwise_correlation") or {}).get("by_method") or {}).get("forward"),
        ),
    }

    vectors, na = _model_vectors_ready(
        before_plan, after_plan, before_model_facts, after_model_facts
    )
    if vectors is None:
        assert na is not None
        marginal_impact = dict(na)
        overlap_with_new = dict(na)
    else:
        e_before, g_before, sigma_before, exposures, specific_var, degraded_meta = vectors
        w_before = _weights_map(before_plan)
        w_after = _weights_map(after_plan)
        union_ids = sorted(set(w_before) | set(w_after))

        if any(iid not in exposures or iid not in specific_var for iid in union_ids):
            missing_na = unavailable(
                reason_code="data_not_validated",
                reason="部分持仓缺少模型暴露或特质方差，无法计算模型调仓对比指标。",
            )
            marginal_impact = dict(missing_na)
            overlap_with_new = dict(missing_na)
        else:
            impact = 0.0
            new_holdings: list[tuple[str, float]] = []
            for iid in union_ids:
                w0 = w_before.get(iid, 0.0)
                w1 = w_after.get(iid, 0.0)
                dw = w1 - w0
                mrc_i = (float(exposures[iid] @ g_before) + specific_var[iid] * w0) / sigma_before
                impact += mrc_i * dw
                if w0 <= _WEIGHT_EPS and w1 > _WEIGHT_EPS:
                    new_holdings.append((iid, w1))

            if not _admitted_gate(
                before_model_facts, after_model_facts, "marginal_risk_contribution"
            ):
                marginal_impact = unavailable(
                    reason_code="data_not_validated",
                    reason="当前发布协议未准入边际风险贡献指标，无法计算一阶边际波动影响。",
                )
            else:
                marginal_impact = (
                    _wrap_model_scalar(float(impact), degraded_meta)
                    if math.isfinite(impact)
                    else unavailable(
                        reason_code="data_not_validated", reason="边际波动影响非有限数。"
                    )
                )

            if not _admitted_gate(before_model_facts, after_model_facts, "style_exposure"):
                overlap_with_new = unavailable(
                    reason_code="data_not_validated",
                    reason="当前发布协议未准入因子暴露指标，无法计算新增标的因子重叠度。",
                )
            elif not new_holdings:
                overlap_with_new = unavailable(
                    reason_code="not_applicable",
                    reason="调仓后无新进入组合的标的，不适用新增标的因子重叠度。",
                )
            else:
                total_new = sum(w for _, w in new_holdings)
                beta_new = sum(
                    ((w / total_new) * exposures[iid] for iid, w in new_holdings),
                    np.zeros_like(e_before),
                )
                norm_new = float(np.linalg.norm(beta_new))
                norm_before = float(np.linalg.norm(e_before))
                if norm_new <= _NORM_EPS or norm_before <= _NORM_EPS:
                    overlap_with_new = unavailable(
                        reason_code="zero_variance",
                        reason="新增持仓或调仓前组合的因子暴露向量为零，无法计算余弦重叠度。",
                    )
                else:
                    cos = float(
                        np.clip(float(beta_new @ e_before) / (norm_new * norm_before), -1.0, 1.0)
                    )
                    overlap_with_new = (
                        _wrap_model_scalar(cos, degraded_meta)
                        if math.isfinite(cos)
                        else unavailable(
                            reason_code="data_not_validated",
                            reason="新增标的因子重叠度非有限数。",
                        )
                    )

    return {
        "before_plan_id": str(before_plan["plan_id"]),
        "after_plan_id": str(after_plan["plan_id"]),
        "deltas": deltas,
        "marginal_impact": marginal_impact,
        "overlap_with_new": overlap_with_new,
        "intent_effect_gap": [],
    }
