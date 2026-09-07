"""诊断终态和页面报告组装：消费固定快照，不查询行情或重算指标。"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from gr_api.schemas.diagnosis_response import (
    DiagnosisResult,
    ReportResponse,
    SnapshotAccepted,
    SnapshotMeta,
    SnapshotProgress,
)
from gr_api.services.pick_symbols import parse_symbol


SECTION_IDS = (
    "section_a",
    "section_b",
    "section_c",
    "section_d",
    "stress_scenarios",
    "blindspots",
    "profile",
)


def unavailable(code: str, reason: str) -> dict:
    return {"status": "unavailable", "reason_code": code, "reason": reason}


def ready(value: object) -> dict:
    return {"status": "ready", "value": value}


def normalized_symbol(symbol: str) -> str:
    try:
        return parse_symbol(symbol).symbol_full
    except ValueError:
        return symbol.strip().upper()


def input_summary(row: dict, context: dict) -> dict:
    """回显原始行；实际权重直接来自持久化计算输入，不按页面重算。"""
    requested = row["requested_holdings"]
    holdings = row["resolved_holdings"] or []
    by_symbol = {h["symbol"]: h for h in holdings}
    equal = row["weight_mode"] == "equal"
    unique = {normalized_symbol(h["symbol"]) for h in requested}
    total = Decimal(len(unique)) if equal else sum(Decimal(str(h["weight"])) for h in requested)
    merged: dict[str, Decimal] = {}
    for h in requested:
        symbol = normalized_symbol(h["symbol"])
        merged[symbol] = (
            Decimal(1) if equal else merged.get(symbol, Decimal(0)) + Decimal(str(h["weight"]))
        )
    coverage = context["exposure"]["calculation_coverage_ratio"]
    seen: dict[str, int] = {}
    echoes = []
    for i, h in enumerate(requested):
        symbol = normalized_symbol(h["symbol"])
        resolved = by_symbol.get(symbol)
        zero = not equal and Decimal(str(h["weight"])) == 0
        status = (
            "zero_weight"
            if zero
            else "duplicate"
            if symbol in seen
            else "resolved"
            if resolved
            else "unresolved"
        )
        echoes.append(
            {
                "input_index": i,
                "input_symbol": h["symbol"],
                "input_weight": h.get("weight"),
                "normalized_symbol": symbol,
                "instrument_id": resolved["instrument_id"] if resolved else None,
                "name": resolved.get("name", resolved["symbol"]) if resolved else None,
                "status": status,
                "merged_into_input_index": seen.get(symbol) if status == "duplicate" else None,
            }
        )
        if not zero:
            seen.setdefault(symbol, i)
    return {
        "weight_mode": row["weight_mode"],
        "holdings": echoes,
        "calculation_holdings": [
            {
                "instrument_id": h["instrument_id"],
                "symbol": h["symbol"],
                "name": h.get("name", h["symbol"]),
                "input_share": float(merged[h["symbol"]] / total),
                "calculation_weight": h["weight"],
            }
            for h in holdings
            if h["weight"] > 0
        ],
        "input_weight": 1.0,
        "resolved_weight": coverage,
        "unresolved_weight": 1 - coverage,
        "calculation_coverage_ratio": coverage,
        "normalized_within_resolved_subset": coverage < 1,
    }


def apply_coverage(
    metrics: dict, coverage: float, params: dict, data_coverage: dict | None = None
) -> dict:
    """按版本阈值应用完整输入分母上的有效覆盖率，不修改共享计算值。"""
    result = deepcopy(metrics)
    thresholds = params.get("coverage_thresholds", {})
    sources = {
        "industry_distribution": "industry",
        "market_distribution": "category",
        "asset_category_distribution": "category",
        "style_distribution": "valuation",
    }
    for key, metric in result.items():
        if not isinstance(metric, dict) or metric.get("status") not in ("ok", "degraded"):
            continue
        limits = thresholds.get(key, thresholds.get("_default", {}))
        low, degraded = float(limits.get("unavailable", 0.80)), float(limits.get("degraded", 0.95))
        effective = coverage * (data_coverage or {}).get(sources.get(key), 1.0)
        if effective < low:
            result[key] = unavailable(
                "coverage_below_threshold",
                f"有效数据仅覆盖完整输入的 {effective:.1%}，不足以代表完整组合",
            )
        elif effective < degraded:
            previous = metric.get("reason", "")
            metric.update(
                status="degraded",
                reason_code="coverage_below_threshold",
                confidence="low",
                reason=f"仅在覆盖到的 {effective:.1%} 输入份额内计算。{previous}",
            )
    return result


def assemble(
    snapshot: dict,
    spec: dict,
    rows: list[dict],
    contexts: list[dict],
    old_plans: list[dict],
    dq_items: list[dict],
    run_status: str,
) -> dict:
    """每个方案保留自己的状态、覆盖率和错误，失败方案不从数组消失。"""
    from gr_api.services.diagnosis import (
        _build_blindspots,
        _build_disclosures,
        _build_profile,
        _report_mode,
    )

    versions = {
        (r["data_fingerprint"], r["data_snapshot_at"]) for r in rows if r.get("data_fingerprint")
    }
    if len(versions) != 1:
        from gr_api.errors import BadRequest

        raise BadRequest(
            "diagnosis data snapshot metadata is unavailable or inconsistent", http_status=503
        )
    fingerprint, snapshot_at = next(iter(versions))
    requested = list(spec["params"].get("cov_methods") or ["historical"])
    meta = {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "schema_version": "diagnosis.v1",
        "spec_version": snapshot["resolved_spec_version"],
        "as_of_date": snapshot["resolved_as_of_date"],
        "data_fingerprint": fingerprint,
        "data_snapshot_at": snapshot_at,
        "resolved_intent": snapshot["resolved_intent"],
        "report_mode": _report_mode(snapshot["resolved_intent"]),
        "requested_cov_methods": requested,
    }
    if run_status in ("pending", "running"):
        return SnapshotProgress(
            **meta,
            run_status=run_status,
            plans=[
                {
                    "plan_id": r["plan_id"],
                    "label": r["label"],
                    "run_status": r["status"] or "pending",
                    "sections": {key: "pending" for key in SECTION_IDS},
                    "error": None,
                }
                for r in rows
            ],
        ).model_dump(mode="json")
    old_by_id = {p["plan_id"]: p for p in old_plans}
    plans, quality = [], []
    for row, context, dq in zip(rows, contexts, dq_items, strict=True):
        summary = input_summary(row, context)
        dq = deepcopy(dq)
        if not dq["forced_disclosures"]:
            dq["forced_disclosures"] = _build_disclosures(
                spec["params"],
                weight_mode=row["weight_mode"],
                fingerprint_time=snapshot_at.strftime("%Y-%m-%d %H:%M"),
            )
        issues = [
            {
                "code": h["status"],
                "reason": f"输入代码 {h['input_symbol']}：{h['status']}",
                "paths": [f"/holdings/{h['input_index']}"],
            }
            for h in summary["holdings"]
            if h["status"] != "resolved"
        ]
        base = {
            "plan_id": row["plan_id"],
            "label": row["label"],
            "input": summary,
            "cov": {"requested": requested, "primary": None, "computed": []},
            "error": None,
        }
        if row["status"] == "failed" or row["plan_id"] not in old_by_id:
            error = {
                "code": "calculation_failed",
                "message": "本方案计算失败，请重新提交诊断。",
                "retryable": True,
                "issues": [],
            }
            base.update(
                run_status="failed",
                error=error,
                **{key: {"status": "failed", "error": error} for key in SECTION_IDS},
            )
        else:
            old = old_by_id[row["plan_id"]]
            a = {k: v for k, v in old["section_a"].items() if isinstance(v, dict)}
            a = apply_coverage(
                a, summary["calculation_coverage_ratio"], spec["params"], dq["coverage_summary"]
            )
            blindspots = _build_blindspots(a, spec["params"])
            if not any(b["detector"] == "concentration" for b in blindspots):
                blindspots.insert(
                    0,
                    {
                        "detector": "concentration",
                        "triggered": False,
                        "severity": None,
                        "message": "输入覆盖不足，无法判断集中度",
                        "reason_code": "coverage_below_threshold",
                    },
                )
            for hit in blindspots:
                triggered = hit.pop("triggered")
                if hit["reason_code"] == "factor_model_unavailable":
                    hit["reason_code"] = "feature_not_available"
                    hit["message"] = "相关性或因子暴露的诊断计算尚未开放，无法判断。"
                hit["status"] = (
                    "unavailable"
                    if hit["reason_code"]
                    else "triggered"
                    if triggered
                    else "not_triggered"
                )
            base.update(
                run_status="partially_succeeded",
                section_a=ready(a),
                section_b=unavailable("feature_not_available", "风险计算尚未开放。"),
                section_c=unavailable(
                    "spec_not_defined", "组合历史序列、回撤及归因的计算口径尚未确定。"
                ),
                section_d=unavailable("feature_not_available", "相关性与结构计算尚未开放。"),
                stress_scenarios=unavailable("feature_not_available", "压力测试尚未开放。"),
                blindspots=ready(blindspots),
                profile=ready(_build_profile(a, summary["calculation_holdings"])),
            )
        for key in SECTION_IDS:
            section = base[key]
            if section["status"] == "unavailable":
                issues.append(
                    {
                        "code": section["reason_code"],
                        "reason": section["reason"],
                        "paths": [f"/{key}"],
                    }
                )
            elif section["status"] == "failed":
                issues.append(
                    {
                        "code": section["error"]["code"],
                        "reason": section["error"]["message"],
                        "paths": [f"/{key}"],
                    }
                )
        if base["section_a"]["status"] == "ready":
            for key, metric in base["section_a"]["value"].items():
                if metric["status"] != "ok":
                    issues.append(
                        {
                            "code": metric["reason_code"],
                            "reason": metric["reason"],
                            "paths": [f"/section_a/value/{key}"],
                        }
                    )
        for key in ("suspended_or_delisted", "new_listings_short_window", "lookthrough_gaps"):
            if dq.get(key):
                issues.append({"code": key, "reason": "、".join(dq[key]), "paths": ["/holdings"]})
        quality.append(
            {
                "plan_id": row["plan_id"],
                "issues": issues,
                "coverage_summary": {
                    key: value
                    if key == "symbol_resolution"
                    else value * summary["calculation_coverage_ratio"]
                    for key, value in dq["coverage_summary"].items()
                },
                "forced_disclosures": dq["forced_disclosures"],
            }
        )
        plans.append(base)
    disclosures = list(dict.fromkeys(d for q in quality for d in q["forced_disclosures"]))
    comparison = (
        unavailable("not_applicable", "单方案不适用方案比较。")
        if len(plans) == 1
        else unavailable("feature_not_available", "方案比较尚未开放，各方案可独立查看。")
    )
    status = "failed" if all(p["run_status"] == "failed" for p in plans) else "partially_succeeded"
    return DiagnosisResult(
        **meta,
        run_status=status,
        plans=plans,
        comparison=comparison,
        disclosures=disclosures,
        data_quality={"plans": quality, "forced_disclosures": disclosures},
    ).model_dump(mode="json")


def accepted(result: dict) -> dict:
    meta = SnapshotMeta.model_validate(
        {k: result[k] for k in SnapshotMeta.model_fields}
    ).model_dump(mode="json")
    sid = result["snapshot_id"]
    return SnapshotAccepted(
        **meta,
        run_status=result["run_status"],
        plans=[
            {
                "plan_id": p["plan_id"],
                "label": p["label"],
                "run_status": p["run_status"],
                "sections": p.get("sections") or {key: p[key]["status"] for key in SECTION_IDS},
                "error": p.get("error"),
            }
            for p in result["plans"]
        ],
        links={
            key: f"/v1/diagnosis/snapshots/{sid}/{key.replace('_', '-')}"
            for key in ("result", "report", "stream", "data_quality")
        },
    ).model_dump(mode="json")


def report(result: dict, level: str = "retail") -> dict:
    if result["run_status"] in ("pending", "running"):
        return result
    sections = []

    def add(
        pid: str | None, kind: str, title: str, content: dict, suffix: str | None = None
    ) -> None:
        sections.append(
            {
                "section_id": f"{pid}:{suffix or kind}" if pid else kind,
                "plan_id": pid,
                "kind": kind,
                "title": title,
                "content": content,
            }
        )

    labels = {
        "topn": "TopN 权重",
        "hhi": "HHI 集中度",
        "l1_count": "名义持仓数",
        "l2_effective_count": "权重有效持仓数",
        "lookthrough_coverage": "穿透覆盖率",
    }
    distributions = {
        "industry_distribution": "行业",
        "market_distribution": "市场",
        "asset_category_distribution": "资产类别",
        "style_distribution": "风格",
    }
    for p in result["plans"]:
        pid = p["plan_id"]
        profile = p["profile"]
        content = profile
        if profile["status"] == "ready":
            v = profile["value"]
            content = ready(
                [
                    {"type": "text", "text": text}
                    for text in [
                        v["label"],
                        *v["top_findings"],
                        f"置信度：{v['confidence']}；数据状态：{v['data_status']}",
                    ]
                ]
            )
        add(pid, "profile", "整体判断", content)
        add(
            pid,
            "instrument",
            "输入持仓与解析结果",
            ready([{"type": "holdings", "input": p["input"]}]),
        )
        a = p["section_a"]
        content = a
        if a["status"] == "ready":
            metrics = a["value"]
            cards = [
                {
                    "metric_id": key,
                    "label": label,
                    "value": metrics[key],
                    "format": "percent"
                    if key in ("topn", "lookthrough_coverage")
                    else "integer"
                    if key == "l1_count"
                    else "number",
                    "decimals": 0 if key == "l1_count" else 2,
                }
                for key, label in labels.items()
                if level == "pro" or key != "hhi"
            ]
            blocks = [{"type": "metric_cards", "items": cards}]
            for key in distributions:
                metric = metrics[key]
                blocks.append(
                    {
                        "type": "distribution",
                        "metric_id": key,
                        "labels": {k: k for k in metric.get("value", {})},
                        "values": metric,
                    }
                )
            content = ready(blocks)
        add(pid, "exposure", "构成与敞口", content)
        add(pid, "risk", "风险画像", p["section_b"])
        add(pid, "style", "历史归因与分位", p["section_c"], "history")
        add(pid, "diversification", "关系与结构", p["section_d"])
        add(pid, "risk", "压力测试", p["stress_scenarios"], "stress")
        blind = p["blindspots"]
        add(
            pid,
            "summary",
            "盲点检查",
            ready([{"type": "text", "text": b["message"]} for b in blind["value"]])
            if blind["status"] == "ready"
            else blind,
        )
    add(None, "comparison", "方案比较", result["comparison"])
    add(
        None,
        "limitations",
        "方法与数据局限",
        ready([{"type": "text", "text": text} for text in result["disclosures"]]),
    )
    meta = {k: result[k] for k in SnapshotMeta.model_fields}
    return ReportResponse(
        **meta,
        user_level=level,
        run_status=result["run_status"],
        sections=sections,
        disclosures=result["disclosures"],
        data_quality=result["data_quality"],
    ).model_dump(mode="json")
