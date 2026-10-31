"""指标三态的字典构造器，与 ``schemas.diagnosis_response.MetricValue`` 同形。

计算层产出普通字典，由调用方在落库前统一过 Pydantic 校验；这里不 import schema，
避免纯计算模块依赖 API 层。``window`` 字段为 ``(start, end)`` 日期对，``None`` 表示不回显。
"""

from __future__ import annotations

from datetime import date
from typing import Any


Window = tuple[date, date]


def _sample_fields(
    window_target: Window | None, window_actual: Window | None, sample_count: int | None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if window_target is not None:
        out["window_target"] = {"start": window_target[0], "end": window_target[1]}
    if window_actual is not None:
        out["window_actual"] = {"start": window_actual[0], "end": window_actual[1]}
    if sample_count is not None:
        out["sample_count"] = sample_count
    return out


def ok(
    value: Any,
    *,
    method: str = "exact",
    confidence: str = "high",
    window_target: Window | None = None,
    window_actual: Window | None = None,
    sample_count: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "value": value,
        "method": method,
        "confidence": confidence,
        **_sample_fields(window_target, window_actual, sample_count),
    }


def degraded(
    value: Any,
    *,
    reason_code: str,
    reason: str,
    method: str = "exact",
    confidence: str = "medium",
    window_target: Window | None = None,
    window_actual: Window | None = None,
    sample_count: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "degraded",
        "value": value,
        "method": method,
        "reason_code": reason_code,
        "reason": reason,
        "confidence": confidence,
        **_sample_fields(window_target, window_actual, sample_count),
    }


def unavailable(
    *,
    reason_code: str,
    reason: str,
    window_target: Window | None = None,
    window_actual: Window | None = None,
    sample_count: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason_code": reason_code,
        "reason": reason,
        **_sample_fields(window_target, window_actual, sample_count),
    }


def has_value(metric: dict[str, Any]) -> bool:
    return metric.get("status") in ("ok", "degraded")
