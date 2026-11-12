"""已发布诊断范围的请求级门禁和完整输入持仓覆盖，不缩小分母。"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from gr_api.errors import BadRequest
from gr_api.services import diagnosis_publication as publication
from gr_data.diagnostic_publication import portfolio_hash


METRICS = frozenset({"annual_variance", "volatility", "daily_prediction_volatility"})


def input_weights(summary: dict[str, Any]) -> tuple[dict[int, Decimal], list[dict[str, Any]]]:
    """从固定输入回显还原完整分母份额，未识别项仍占分母，重复项合并。"""
    grouped: dict[int | str, dict[str, Any]] = {}
    for row in summary["holdings"]:
        key = row["instrument_id"] if row["instrument_id"] is not None else row["normalized_symbol"]
        weight = (
            Decimal(row["input_weight"] or "0") if summary["weight_mode"] == "user" else Decimal(1)
        )
        item = grouped.setdefault(
            key,
            {
                "instrument_id": row["instrument_id"],
                "symbol": row["normalized_symbol"],
                "raw": Decimal(0),
            },
        )
        if summary["weight_mode"] == "user":
            item["raw"] += weight
        else:
            item["raw"] = Decimal(1)
    total = sum((x["raw"] for x in grouped.values()), Decimal(0))
    weights: dict[int, Decimal] = {}
    missing = []
    for item in grouped.values():
        if item["raw"] <= 0:
            continue
        weight = item["raw"] / total
        if item["instrument_id"] is None:
            missing.append(
                {
                    "instrument_id": None,
                    "symbol": item["symbol"],
                    "weight": format(weight, "f"),
                    "reason": "unresolved_symbol",
                }
            )
        else:
            weights[item["instrument_id"]] = weight
    return weights, missing


def scope(version: dict[str, Any]) -> dict[str, Any]:
    """只有显式完整的发布范围才可供正式读取。"""
    value = (version.get("available_options") or {}).get("publication_scope")
    if not isinstance(value, dict):
        raise BadRequest("publication scope has not been admitted", http_status=503)
    kind = value.get("scope_type") or ("exact_portfolio" if "holdings" in value else None)
    contract = version.get("contract_version")
    if (
        kind not in ("exact_portfolio", "security_universe")
        or value.get("as_of") != str(version.get("as_of_date"))
        or value.get("model") != "v2"
        or not value.get("run_id")
        or set(value.get("metrics") or ()) != METRICS
        or (kind == "security_universe" and contract != "diag-publication-v2-universe")
        or (kind == "exact_portfolio" and contract != "diag-publication-v1")
    ):
        raise BadRequest("publication scope identity is invalid", http_status=503)
    return {**value, "scope_type": kind}


def validate_request(
    version: dict[str, Any], plans: list[Any], requested_date: Any, metrics: Sequence[str] | None
) -> None:
    """精确旧版不扩大解释；新版按证券清单诊断并回显缺项，不能回退日期。"""
    admitted = scope(version)
    if requested_date is not None and str(requested_date) != admitted["as_of"]:
        raise BadRequest("as_of_date must match the published scope", http_status=422)
    if not set(metrics or METRICS) <= set(admitted["metrics"]):
        raise BadRequest("requested metric is outside publication scope", http_status=422)
    if admitted["scope_type"] == "exact_portfolio":
        expected = {int(i): Decimal(w) for i, w in admitted.get("holdings", {}).items()}
        for plan in plans:
            weights, missing = input_weights(plan.summary)
            if (
                missing
                or weights != expected
                or portfolio_hash(weights) != admitted.get("portfolio_hash")
            ):
                error = BadRequest(
                    "portfolio does not match the exact published scope", http_status=422
                )
                error.issues = [
                    {
                        "path": f"/plans/{plan.plan_index}",
                        "code": "publication_scope_mismatch",
                        "message": "该旧版本仅允许原精确组合。",
                    }
                ]
                raise error


def initial_coverage(summary: dict[str, Any]) -> tuple[dict[str, Any], dict[int, Decimal]]:
    weights, missing = input_weights(summary)
    context = publication.current.get()
    admitted = scope(dict(context.version)) if context else {}
    return {
        "status": "incomplete",
        "scope_type": admitted.get("scope_type"),
        "total_count": len(weights) + len(missing),
        "covered_count": 0,
        "total_weight": "1",
        "covered_weight": "0",
        "missing": missing,
        "metrics": admitted.get("metrics", []),
        "reason": None,
    }, weights


def cache_scope(summary: dict[str, Any]) -> str:
    """完整风险计算依赖完整输入；原分母/未知项变化必须隔离成功缓存。"""
    import hashlib
    import json

    weights, missing = input_weights(summary)
    identity = {
        "weights": [[i, format(w.normalize(), "f")] for i, w in sorted(weights.items())],
        "unresolved": sorted([[r["symbol"], r["weight"]] for r in missing]),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def base_ids(ids: list[int]) -> list[int]:
    """基础数据只读已声明证券；清单外仍保留在输入分母及缺失桶。"""
    context = publication.current.get()
    if context is None:
        return ids
    admitted = scope(dict(context.version))
    allowed = set(
        admitted.get("security_ids", [])
        if admitted["scope_type"] == "security_universe"
        else (int(i) for i in admitted.get("holdings", {}))
    )
    return [i for i in ids if i in allowed]
