"""指标三态的字典构造器，与 ``schemas.diagnosis_response.MetricValue`` 同形。

计算层产出普通字典，由调用方在落库前统一过 Pydantic 校验；这里不 import schema，
避免纯计算模块依赖 API 层。
"""

from __future__ import annotations

from typing import Any


def ok(value: Any, *, method: str = "exact", confidence: str = "high") -> dict[str, Any]:
    return {"status": "ok", "value": value, "method": method, "confidence": confidence}


def degraded(
    value: Any,
    *,
    reason_code: str,
    reason: str,
    method: str = "exact",
    confidence: str = "medium",
) -> dict[str, Any]:
    return {
        "status": "degraded",
        "value": value,
        "method": method,
        "reason_code": reason_code,
        "reason": reason,
        "confidence": confidence,
    }


def unavailable(*, reason_code: str, reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason_code": reason_code, "reason": reason}


def has_value(metric: dict[str, Any]) -> bool:
    return metric.get("status") in ("ok", "degraded")
