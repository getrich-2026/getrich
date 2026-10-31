"""诊断终态和页面报告组装：消费固定快照，不查询行情或重算指标。

共享计算载体只描述已识别子集；这里结合当前快照固定的输入回显应用覆盖率阈值、
合成方案状态，再生成盲点、数据质量与披露。共享对象一律深拷贝后再改。
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from gr_api.diagnosis_calc.coverage import apply_exposure_coverage, effective_coverage
from gr_api.diagnosis_calc.exposure import MISSING_OR_INVALID, NON_POSITIVE, UNCLASSIFIED
from gr_api.diagnosis_calc.metrics import has_value
from gr_api.schemas.diagnosis_response import (
    DataQualityResponse,
    DiagnosisResult,
    ReportResponse,
    SnapshotAccepted,
    SnapshotMeta,
    SnapshotProgress,
)


SECTION_IDS = (
    "section_a",
    "section_b",
    "section_c",
    "section_d",
    "stress_scenarios",
    "blindspots",
    "profile",
)

CALCULATION_SECTIONS = ("section_a", "section_b", "section_c", "section_d", "stress_scenarios")

ECHO_MESSAGES: dict[str, str] = {
    "unresolved": "未能识别该代码，其份额保留在完整输入分母中。",
    "duplicate": "与前面的输入为同一标的，已合并。",
    "zero_weight": "权重为零或过小（按 8 位小数量化后为 0），按零权重处理，不参与计算。",
}

#: 定性阈值确认前（2026-10-21 PA-04），盲点只给出明确的「未能判断」。
BLINDSPOTS: tuple[dict[str, Any], ...] = (
    {
        "detector": "concentration",
        "reason_code": "spec_not_defined",
        "message": "集中度的定性阈值尚未确认，暂不判断；数值见 HHI 与权重有效持仓数。",
    },
    {
        "detector": "industry_concentration",
        "reason_code": "spec_not_defined",
        "message": "行业集中的定性阈值尚未确认，暂不判断；数值见行业分布与最大行业。",
    },
    {
        "detector": "pseudo_diversification",
        "reason_code": "feature_not_available",
        "message": "需要模型相关性，风险模型尚未开放，无法判断。",
    },
    {
        "detector": "style_bet",
        "reason_code": "feature_not_available",
        "message": "需要风格暴露，风险模型尚未开放，无法判断。",
    },
)

PROFILE_UNAVAILABLE = {
    "status": "unavailable",
    "reason_code": "spec_not_defined",
    "reason": "组合画像的定性规则尚未确认，暂不输出类型判断；各项数值照常展示。",
}

DATA_COVERAGE_KEYS = {
    "industry": "industry_distribution",
    "category": "market_distribution",
    "mktcap": "mktcap_distribution",
    "pb": "pb_distribution",
}


def unavailable(code: str, reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason_code": code, "reason": reason}


def ready(value: object) -> dict[str, Any]:
    return {"status": "ready", "value": value}


def _meta(snapshot: dict[str, Any], spec: dict[str, Any], report_mode: str) -> dict[str, Any]:
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "schema_version": "diagnosis.v1",
        "spec_version": snapshot["resolved_spec_version"],
        "as_of_date": snapshot["resolved_as_of_date"],
        "data_fingerprint": snapshot["data_fingerprint"],
        "data_snapshot_at": snapshot["data_snapshot_at"],
        "resolved_intent": snapshot["resolved_intent"],
        "report_mode": report_mode,
        "requested_cov_methods": list(spec["params"].get("cov_methods") or []),
        "options": snapshot["resolved_options"],
        "base_snapshot_id": snapshot.get("base_snapshot_id"),
        # DP-08 时效上限尚未配置，重算结果暂不会被判为历史结果。
        "historical_result": False,
    }


def _blindspots() -> list[dict[str, Any]]:
    return [{**hit, "status": "unavailable", "severity": None} for hit in BLINDSPOTS]


def _failed_plan(base: dict[str, Any], requested: list[str]) -> dict[str, Any]:
    error = {
        "code": "calculation_failed",
        "message": "本方案计算失败，请重新提交诊断。",
        "retryable": True,
        "issues": [],
    }
    return {
        **base,
        "cov": {"requested": requested, "forward_model": None, "primary": None, "computed": []},
        "run_status": "failed",
        "error": error,
        **{key: {"status": "failed", "error": error} for key in SECTION_IDS},
    }


def _plan_issues(plan: dict[str, Any], facts: dict[str, Any]) -> list[dict[str, Any]]:
    """把输入回显、指标降级、区块不可用和数据缺口整理成可定位的数据质量项。"""
    summary = plan["input"]
    issues = [
        {
            "code": h["status"],
            "reason": f"输入 {h['input_symbol']}：{ECHO_MESSAGES[h['status']]}",
            "paths": [f"/holdings/{h['input_index']}"],
        }
        for h in summary["holdings"]
        if h["status"] != "resolved"
    ]
    for key in SECTION_IDS:
        section = plan[key]
        if section["status"] == "unavailable":
            issues.append(
                {"code": section["reason_code"], "reason": section["reason"], "paths": [f"/{key}"]}
            )
        elif section["status"] == "failed":
            issues.append(
                {
                    "code": section["error"]["code"],
                    "reason": section["error"]["message"],
                    "paths": [f"/{key}"],
                }
            )
    if plan["section_a"]["status"] == "ready":
        for key, metric in plan["section_a"]["value"].items():
            if metric["status"] != "ok":
                issues.append(
                    {
                        "code": metric["reason_code"],
                        "reason": metric["reason"],
                        "paths": [f"/section_a/value/{key}"],
                    }
                )
    names = {h["instrument_id"]: h["symbol"] for h in summary["calculation_holdings"]}
    lagged = facts.get("valuation_lagged") or []
    if lagged:
        share = float(facts.get("valuation_lagged_weight") or 0) * summary["resolved_weight"]
        issues.append(
            {
                "code": "valuation_lagged",
                "reason": (
                    "估值日期早于诊断日期（如停牌）："
                    + "、".join(names.get(i, str(i)) for i in lagged)
                    + f"，占完整输入 {share:.1%}。"
                ),
                "paths": ["/section_a/value/instrument_facts"],
            }
        )
    for source, metric_id in DATA_COVERAGE_KEYS.items():
        missing = (facts.get("missing") or {}).get(source) or []
        if missing:
            issues.append(
                {
                    "code": "data_missing",
                    "reason": "缺少所需数据，已单列缺失档："
                    + "、".join(names.get(i, str(i)) for i in missing),
                    "paths": [f"/section_a/value/{metric_id}"],
                }
            )
    return issues


def _plan_disclosures(summary: dict[str, Any]) -> list[str]:
    out = []
    if summary["weight_mode"] == "equal":
        out.append("未提供权重，本报告按去重后的标的等权计算。")
    if summary["unresolved_weight"] > 0:
        out.append(
            f"有 {summary['unresolved_weight']:.1%} 的输入份额未能识别；"
            "TopN 以完整输入为分母，其余指标在已识别部分计算并按覆盖率标注。"
        )
    return out


def snapshot_disclosures(snapshot: dict[str, Any]) -> list[str]:
    snapshot_at = snapshot["data_snapshot_at"].strftime("%Y-%m-%d %H:%M")
    return [
        f"本报告基于 {snapshot_at} 发布的数据快照计算，诊断日期 {snapshot['resolved_as_of_date']}；"
        "数据供应商的后续修订不会反映在本报告中。",
        "本报告分析当前输入持仓的构成，不代表用户的真实收益，也不构成投资建议。",
        "风险模型、相关性、历史回放与压力测试尚未开放，相关章节显示为不可用，不以估算值填充。",
    ]


def assemble(
    snapshot: dict[str, Any],
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    run_status: str,
    *,
    report_mode: Callable[[str], str],
) -> dict[str, Any]:
    """每个方案保留自己的状态、覆盖率和错误，失败方案不从数组消失。"""
    params = spec["params"]
    meta = _meta(snapshot, spec, report_mode(snapshot["resolved_intent"]))
    if run_status in ("pending", "running"):
        return SnapshotProgress.model_validate(
            dict(
                **meta,
                run_status=run_status,
                plans=[
                    {
                        "plan_id": r["plan_id"],
                        "label": r["label"],
                        "run_status": r["status"] or "pending",
                        "sections": dict.fromkeys(SECTION_IDS, "pending"),
                        "error": None,
                    }
                    for r in rows
                ],
            )
        ).model_dump(mode="json")

    requested = list(params.get("cov_methods") or [])
    plans: list[dict[str, Any]] = []
    quality: list[dict[str, Any]] = []
    for row in rows:
        summary = row["input_context"]
        base = {"plan_id": row["plan_id"], "label": row["label"], "input": summary}
        facts: dict[str, Any] = row["data_quality"] or {}
        if row["status"] == "failed" or row["payload"] is None:
            plan = _failed_plan(base, requested)
        else:
            payload = deepcopy(row["payload"])
            section_a = payload["section_a"]
            if section_a["status"] == "ready":
                section_a = ready(
                    apply_exposure_coverage(
                        section_a["value"],
                        calculation_holdings=summary["calculation_holdings"],
                        resolved_weight=summary["resolved_weight"],
                        facts=facts,
                        params=params,
                    )
                )
            plan = {
                **payload,
                **base,
                "section_a": section_a,
                # B/C/D 属于一期 core_diagnosis，因数据未就绪不可用，按规则降为部分成功。
                "run_status": "partially_succeeded",
                "error": None,
                "blindspots": ready(_blindspots()),
                "profile": dict(PROFILE_UNAVAILABLE),
            }
        coverage = {"symbol_resolution": summary["resolved_weight"]}
        for source, metric_id in DATA_COVERAGE_KEYS.items():
            if source in (facts.get("coverage") or {}):
                coverage[source] = effective_coverage(metric_id, summary["resolved_weight"], facts)
        quality.append(
            {
                "plan_id": row["plan_id"],
                "issues": _plan_issues(plan, facts),
                "coverage_summary": coverage,
                "forced_disclosures": _plan_disclosures(summary),
            }
        )
        plans.append(plan)

    disclosures = snapshot_disclosures(snapshot)
    comparison = (
        unavailable("not_applicable", "单方案不适用方案比较。")
        if len(plans) == 1
        else unavailable("feature_not_available", "方案比较尚未开放，各方案可独立查看。")
    )
    status = "failed" if all(p["run_status"] == "failed" for p in plans) else "partially_succeeded"
    return DiagnosisResult.model_validate(
        dict(
            **meta,
            run_status=status,
            plans=plans,
            comparison=comparison,
            disclosures=disclosures,
            data_quality={"plans": quality, "forced_disclosures": disclosures},
        )
    ).model_dump(mode="json")


def _meta_of(result: dict[str, Any]) -> dict[str, Any]:
    return {k: result[k] for k in SnapshotMeta.model_fields}


def data_quality(result: dict[str, Any]) -> dict[str, Any]:
    return DataQualityResponse.model_validate(
        dict(
            **_meta_of(result), run_status=result["run_status"], data_quality=result["data_quality"]
        )
    ).model_dump(mode="json")


def accepted(result: dict[str, Any]) -> dict[str, Any]:
    sid = result["snapshot_id"]
    return SnapshotAccepted.model_validate(
        dict(
            **_meta_of(result),
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
        )
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

TOPN_LABELS = {1: "Top1 权重", 3: "Top3 权重", 5: "Top5 权重"}

FIXED_LABELS = {
    UNCLASSIFIED: "未分类",
    MISSING_OR_INVALID: "缺失或异常",
    NON_POSITIVE: "非正值",
    "cn_a": "A 股",
    "hk": "港股",
    "us": "美股",
    "other": "其他",
    "equity": "股票",
}


def _band_label(key: str, unit: str) -> str:
    if key in FIXED_LABELS:
        return FIXED_LABELS[key]
    if key.startswith("lt_"):
        return f"<{key[3:]}{unit}"
    if key.startswith("ge_"):
        return f"≥{key[3:]}{unit}"
    low, sep, high = key.partition("_")
    return f"{low}–{high}{unit}" if sep else key


def _topn_cards(metric: dict[str, Any]) -> list[dict[str, Any]]:
    """TopN 列表拆成三张卡片；少于 N 只时在标签中注明实际数量（PA-04）。"""
    if not has_value(metric):
        return [
            {
                "metric_id": f"top{n}",
                "label": label,
                "value": metric,
                "format": "percent",
                "decimals": 1,
            }
            for n, label in TOPN_LABELS.items()
        ]
    cards = []
    for item in metric["value"]:
        label = TOPN_LABELS[item["n"]]
        if item["actual_count"] < item["n"]:
            label += f"（共 {item['actual_count']} 只）"
        cards.append(
            {
                "metric_id": f"top{item['n']}",
                "label": label,
                "value": {**metric, "value": item["weight"]},
                "format": "percent",
                "decimals": 1,
            }
        )
    return cards


def _exposure_blocks(
    metrics: dict[str, Any], level: str, industry_labels: dict[str, str]
) -> list[dict[str, Any]]:
    cards = _topn_cards(metrics["topn"])
    if level == "pro":
        cards.append(
            {
                "metric_id": "hhi",
                "label": "HHI 集中度",
                "value": metrics["hhi"],
                "format": "number",
                "decimals": 4,
            }
        )
    cards += [
        {
            "metric_id": "l1_count",
            "label": "名义持仓数",
            "value": metrics["l1_count"],
            "format": "integer",
            "decimals": 0,
        },
        {
            "metric_id": "l2_effective_count",
            "label": "权重有效持仓数",
            "value": metrics["l2_effective_count"],
            "format": "number",
            "decimals": 2,
        },
    ]
    max_industry = metrics["max_industry"]
    cards.append(
        {
            "metric_id": "max_industry",
            "label": (
                f"最大行业：{max_industry['value']['industry_name']}"
                if has_value(max_industry)
                else "最大行业"
            ),
            "value": (
                {**max_industry, "value": max_industry["value"]["weight"]}
                if has_value(max_industry)
                else max_industry
            ),
            "format": "percent",
            "decimals": 1,
        }
    )
    blocks: list[dict[str, Any]] = [{"type": "metric_cards", "items": cards}]
    for metric_id, unit in (
        ("industry_distribution", ""),
        ("market_distribution", ""),
        ("asset_category_distribution", ""),
        ("mktcap_distribution", " 亿元"),
        ("pb_distribution", ""),
    ):
        metric = metrics[metric_id]
        keys = metric["value"] if has_value(metric) else {}
        if metric_id == "industry_distribution":
            labels = {k: industry_labels.get(k) or FIXED_LABELS.get(k, k) for k in keys}
        else:
            labels = {k: _band_label(k, unit) for k in keys}
        blocks.append(
            {"type": "distribution", "metric_id": metric_id, "labels": labels, "values": metric}
        )
    return blocks


def report(
    result: dict[str, Any],
    level: str = "retail",
    *,
    industry_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """按访问时的 ``user_level`` 裁剪；retail 可省略中间指标，不能省略缺失原因与声明。"""
    if result["run_status"] in ("pending", "running"):
        return result
    labels = industry_labels or {}
    sections: list[dict[str, Any]] = []

    def add(
        pid: str | None, kind: str, title: str, content: dict[str, Any], suffix: str | None = None
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

    for p in result["plans"]:
        pid = p["plan_id"]
        add(pid, "profile", "整体判断", p["profile"])
        add(
            pid,
            "instrument",
            "输入持仓与解析结果",
            ready([{"type": "holdings", "input": p["input"]}]),
        )
        a = p["section_a"]
        add(
            pid,
            "exposure",
            "构成与敞口",
            ready(_exposure_blocks(a["value"], level, labels)) if a["status"] == "ready" else a,
        )
        add(pid, "risk", "风险画像", p["section_b"])
        add(pid, "style", "历史回放与分位", p["section_c"], "history")
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
    return ReportResponse.model_validate(
        dict(
            **_meta_of(result),
            user_level=level,
            run_status=result["run_status"],
            sections=sections,
            disclosures=result["disclosures"],
            data_quality=result["data_quality"],
        )
    ).model_dump(mode="json")
