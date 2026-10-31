"""PA-13 覆盖率阈值：把共享计算载体与当前请求的输入覆盖率合成最终状态。

共享载体只描述已识别子集；同一载体可能被「完整输入」与「一半是未识别代码」的两个
请求复用（§7.8 缓存纯度验收例），所以阈值必须在组装时按各自的输入份额重新判定，
且不能就地修改共享对象。
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from typing import Any

from gr_api.diagnosis_calc.exposure import topn
from gr_api.diagnosis_calc.metrics import has_value, unavailable


DEFAULT_GROUP = "_default"
MISSING_BUCKET_GROUP = "distribution_with_missing_bucket"

#: 口径版本未配置分组时的兜底，与 051 迁移写入的 v1-model-20261031 一致。
DEFAULT_COVERAGE_GROUPS: dict[str, list[str]] = {
    DEFAULT_GROUP: [
        "topn",
        "hhi",
        "l1_count",
        "l2_effective_count",
        "market_distribution",
        "asset_category_distribution",
    ],
    MISSING_BUCKET_GROUP: [
        "industry_distribution",
        "max_industry",
        "mktcap_distribution",
        "pb_distribution",
    ],
}
DEFAULT_THRESHOLDS: dict[str, dict[str, float | None]] = {
    DEFAULT_GROUP: {"degraded": 0.95, "unavailable": 0.80},
    MISSING_BUCKET_GROUP: {"degraded": 0.95, "unavailable": None},
}

#: 指标所需数据在 facts["coverage"] 中的键；None 表示只需代码可识别。
DATA_SOURCE: dict[str, str | None] = {
    "topn": None,
    "hhi": None,
    "l1_count": None,
    "l2_effective_count": None,
    "market_distribution": "category",
    "asset_category_distribution": "category",
    "industry_distribution": "industry",
    "max_industry": "industry",
    "mktcap_distribution": "mktcap",
    "pb_distribution": "pb",
}


def effective_coverage(metric_id: str, resolved_weight: float, facts: Mapping[str, Any]) -> float:
    """完整输入分母上的指标覆盖率：未识别份额与子集内缺数份额都计入缺失。"""
    source = DATA_SOURCE.get(metric_id)
    subset = 1.0 if source is None else float(facts.get("coverage", {}).get(source, 1.0))
    return resolved_weight * subset


def _group_of(metric_id: str, params: Mapping[str, Any]) -> str | None:
    groups = params.get("coverage_groups") or DEFAULT_COVERAGE_GROUPS
    for group, members in groups.items():
        if metric_id in members:
            return str(group)
    return None


def _thresholds(group: str, params: Mapping[str, Any]) -> tuple[float, float | None]:
    configured = params.get("coverage_thresholds") or {}
    limits = (
        configured.get(group)
        or DEFAULT_THRESHOLDS.get(group)
        or configured.get(DEFAULT_GROUP, DEFAULT_THRESHOLDS[DEFAULT_GROUP])
    )
    degraded_at = limits.get("degraded")
    low = limits.get("unavailable")
    return (
        0.95 if degraded_at is None else float(degraded_at),
        None if low is None else float(low),
    )


def apply_exposure_coverage(
    metrics: Mapping[str, Any],
    *,
    calculation_holdings: list[Mapping[str, Any]],
    resolved_weight: float,
    facts: Mapping[str, Any],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """返回按当前请求定状态的模块 A 指标副本。

    * TopN 改用完整输入份额 ``input_share`` 加总（2026-10-21 PA-04），分母含未识别份额；
    * 一般指标低于 0.95 降级、低于 0.80 不可用；带缺失档的分布只降级（PA-13）；
    * 已因结构原因不可用的指标（如行业体系未验证）保持原状。
    """
    result = deepcopy(dict(metrics))
    if has_value(result["topn"]):
        result["topn"]["value"] = topn(Decimal(str(h["input_share"])) for h in calculation_holdings)
    for metric_id, metric in result.items():
        if not has_value(metric):
            continue
        group = _group_of(metric_id, params)
        if group is None:
            continue
        degraded_at, unavailable_at = _thresholds(group, params)
        coverage = effective_coverage(metric_id, resolved_weight, facts)
        if unavailable_at is not None and coverage < unavailable_at:
            result[metric_id] = unavailable(
                reason_code="coverage_below_threshold",
                reason=f"有效数据仅覆盖完整输入的 {coverage:.1%}，不足以代表完整组合。",
            )
        elif coverage < degraded_at:
            metric.update(
                status="degraded",
                reason_code="coverage_below_threshold",
                reason=f"有效数据覆盖完整输入的 {coverage:.1%}，缺失部分未重新归一化。",
                confidence="low",
            )
    return result
