"""诊断终态和页面报告组装：消费固定快照，不查询行情或重算指标。

共享计算载体只描述已识别子集；这里结合当前快照固定的输入回显应用覆盖率阈值、
合成方案状态，再生成盲点、数据质量与披露。共享对象一律深拷贝后再改。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from gr_api.diagnosis_calc.comparison import compute_rebalance_comparison
from gr_api.diagnosis_calc.coverage import (
    apply_exposure_coverage,
    apply_model_coverage,
    effective_coverage,
    model_input_coverage,
)
from gr_api.diagnosis_calc.exposure import MISSING_OR_INVALID, NON_POSITIVE, UNCLASSIFIED
from gr_api.diagnosis_calc.holding_risk import compute_holding_risk_comparison
from gr_api.diagnosis_calc.metrics import has_value
from gr_api.schemas.diagnosis_response import (
    DataQualityResponse,
    DiagnosisResult,
    ReportResponse,
    SharedReportResponse,
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
            if key == "industry_labels":
                continue
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
    model_facts = facts.get("model") or {}
    if model_facts.get("missing"):
        issues.append(
            {
                "code": "model_data_missing",
                "reason": "缺少模型暴露或特质风险，完整组合模型指标不可用："
                + "、".join(names.get(i, str(i)) for i in model_facts["missing"]),
                "paths": ["/section_b/value", "/section_d/value/correlation"],
            }
        )
    history = facts.get("history") or {}
    if history.get("volatility_insufficient"):
        issues.append(
            {
                "code": "history_insufficient",
                "reason": "有效日收益不足，个股历史年化波动率不可用："
                + "、".join(names.get(i, str(i)) for i in history["volatility_insufficient"]),
                "paths": ["/section_b/value/instrument_betas"],
            }
        )
    if history.get("correlation_excluded"):
        issues.append(
            {
                "code": "zero_variance",
                "reason": "共同样本内收益恒定，已从历史相关矩阵中排除："
                + "、".join(names.get(i, str(i)) for i in history["correlation_excluded"]),
                "paths": ["/section_d/value/correlation"],
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


def snapshot_disclosures(
    snapshot: dict[str, Any], forward_models: list[dict[str, Any]] | None = None
) -> list[str]:
    snapshot_at = snapshot["data_snapshot_at"].strftime("%Y-%m-%d %H:%M")
    out = [
        f"本报告基于 {snapshot_at} 发布的数据快照计算，诊断日期 {snapshot['resolved_as_of_date']}；"
        "数据供应商的后续修订不会反映在本报告中。",
        "本报告分析当前输入持仓的构成，不代表用户的真实收益，也不构成投资建议。",
        "历史相关性与个股历史年化波动率基于复权日简单收益，剔除停牌日与跨停牌收益，"
        "描述的是统计区间内的历史表现，不代表未来风险。",
    ]
    models = sorted(
        {(m["model_id"], m["model_version"], str(m["model_date"])) for m in forward_models or []}
    )
    if models:
        out += [
            f"模型口径指标基于风险模型 {mid}（版本 {ver}，截面日 {day}），"
            "默认信任供应商模型，不代表模型已完成校准。"
            for mid, ver, day in models
        ]

    else:
        out.append("本报告未取得准入的风险模型截面，模型口径指标显示为不可用。")
    if (snapshot.get("resolved_options") or {}).get("replay_start"):
        out.append(
            "历史回放按当前配置假设买入持有，采用小数股、税前分红再投资、未扣交易成本，"
            "无成交量冲击；回放波动率及尾部损益仅描述历史区间。"
        )
    if (snapshot.get("resolved_options") or {}).get("benchmark_version"):
        out.append("个股 Beta 与基准相关性按个股和全收益基准共同有效的日简单收益计算。")
    else:
        out.append("当前快照没有已准入的全收益基准，个股 Beta 与基准相关性不可用。")
    return out


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
            if payload["section_b"]["status"] == payload["section_d"]["status"] == "ready":
                risk, structure = apply_model_coverage(
                    payload["section_b"]["value"],
                    payload["section_d"]["value"],
                    resolved_weight=summary["resolved_weight"],
                    model_facts=facts.get("model"),
                    params=params,
                )
                payload["section_b"], payload["section_d"] = ready(risk), ready(structure)
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
        if facts.get("model"):
            coverage["risk_model"] = model_input_coverage(facts["model"])
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

    disclosures = snapshot_disclosures(
        snapshot, [p["cov"]["forward_model"] for p in plans if p["cov"].get("forward_model")]
    )
    intent = snapshot["resolved_intent"]
    if len(plans) == 1:
        comparison = unavailable("not_applicable", "单方案不适用方案比较。")
    elif intent in ("rebalance_holding", "rebalance_amount") and len(plans) == 2:
        if plans[0]["run_status"] == "failed" or plans[1]["run_status"] == "failed":
            comparison = unavailable("not_applicable", "调仓前后存在计算失败方案，无法生成对比。")
        else:
            before_facts = (rows[0]["data_quality"] or {}).get("model")
            after_facts = (rows[1]["data_quality"] or {}).get("model")
            comparison = ready(
                {
                    "pairs": [
                        compute_rebalance_comparison(
                            plans[0],
                            plans[1],
                            before_model_facts=before_facts,
                            after_model_facts=after_facts,
                        )
                    ]
                }
            )
    else:
        comparison = unavailable(
            "feature_not_available",
            "多方案自动两两比较暂未开放，请使用调仓意图对比或分别查看各方案。",
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

METHOD_LABELS = {"forward": "模型", "historical": "历史"}

STYLE_FACTOR_LABELS: dict[str, str] = {
    "beta": "Beta",
    "book_to_price": "账面市值比",
    "dividend_yield": "股息率",
    "earnings_quality": "盈利质量",
    "earnings_variability": "盈利波动",
    "earnings_yield": "盈利收益率",
    "growth": "成长",
    "investment_quality": "投资质量",
    "leverage": "杠杆",
    "liquidity": "流动性",
    "longterm_reversal": "长期反转",
    "mid_cap": "中盘",
    "momentum": "动量",
    "profitability": "盈利能力",
    "residual_volatility": "残差波动率",
    "size": "市值",
}

COMPARISON_DELTA_SPECS: tuple[tuple[str, str, str, int, str | None], ...] = (
    ("volatility", "模型年化波动率变化", "percentage_point", 2, "volatility"),
    (
        "daily_prediction_volatility",
        "单日预测波动率变化",
        "percentage_point",
        4,
        "daily_prediction_volatility",
    ),
    ("l3_effective_count", "风险有效持仓数（L3）变化", "number", 2, "l3_effective_count"),
    ("l4_effective_count", "风险源方差集中度（L4）变化", "number", 2, "l4_effective_count"),
    (
        "l4_market_source_share",
        "市场源占比变化",
        "percentage_point",
        2,
        "l4_market_source_share",
    ),
    ("avg_pairwise_correlation", "模型平均两两相关变化", "number", 2, "model_correlation"),
    ("top1", "Top1 权重变化", "percentage_point", 1, None),
    ("top3", "Top3 权重变化", "percentage_point", 1, None),
    ("top5", "Top5 权重变化", "percentage_point", 1, None),
    ("max_industry", "最大行业占比变化", "percentage_point", 1, None),
    ("l1_count", "名义持仓数变化", "integer", 0, None),
    ("l2_effective_count", "权重有效持仓数（L2）变化", "number", 2, None),
    ("hhi", "HHI 集中度变化", "number", 4, None),
)

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


def _name(names: dict[str, str], instrument_id: object) -> str:
    return names.get(str(instrument_id), str(instrument_id))


def _card(
    metric_id: str, label: str, value: dict[str, Any], fmt: str, decimals: int
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "label": label,
        "value": value,
        "format": fmt,
        "decimals": decimals,
    }


def _source_label(source: dict[str, Any], names: dict[str, str]) -> str:
    if source["kind"] == "factor":
        return f"与因子 {source['factor_code']} 对应的正交风险源"
    return f"{_name(names, source['instrument_id'])} 的特质风险"


def _per_stock(metric: dict[str, Any], instrument_id: int) -> dict[str, Any]:
    """把按股票键的字典指标拆成单股卡片的值，保留原状态与原因。"""
    if not has_value(metric):
        return metric
    return {**metric, "value": metric["value"][str(instrument_id)]}


def _model_blocks(risk: dict[str, Any], names: dict[str, str], level: str) -> list[dict[str, Any]]:
    """模型口径组合风险与逐股风险贡献。

    L4 必须与市场源占比、最大风险源占比同时展示，并说明它描述风险源之间的方差集中度、
    数值越大不代表越分散（计算指标清单 §4）。
    """
    forward = risk["volatility"]["by_method"]["forward"]
    if not has_value(forward):
        blocks = [{"type": "text", "text": f"模型风险：{forward['reason']}"}]
        coverage = risk.get("model_coverage") or {}
        labels = {
            "outside_security_universe": "不在已准入证券清单",
            "unresolved_symbol": "代码未识别",
            "specific_risk_missing": "特异风险缺失",
            "exposure_missing": "因子暴露缺失",
            "risk_coverage_not_included": "风险覆盖未纳入",
            "risk_not_available_at_publication": "发布时风险数据尚不可用",
            "covariance_missing": "因子协方差缺失",
            "covariance_invalid": "因子协方差未通过校验",
        }
        for missing in coverage.get("missing", []):
            blocks.append(
                {
                    "type": "text",
                    "text": f"{missing['symbol']}，权重 {missing['weight']}："
                    + labels.get(str(missing["reason"]), str(missing["reason"])),
                }
            )
        return blocks
    largest = risk["l4_largest_source"]
    largest_label = (
        f"最大风险源占比（{_source_label(largest['value'], names)}）"
        if has_value(largest)
        else "最大风险源占比"
    )
    largest_value = (
        {**largest, "value": largest["value"]["share"]} if has_value(largest) else largest
    )
    blocks: list[dict[str, Any]] = [
        {
            "type": "metric_cards",
            "items": [
                _card("volatility.forward", "模型年化波动率", forward, "percent", 1),
                *(
                    [
                        _card(
                            "daily_prediction_volatility",
                            "单日预测波动率",
                            risk["daily_prediction_volatility"],
                            "percent",
                            6,
                        )
                    ]
                    if risk.get("daily_prediction_volatility") is not None
                    else []
                ),
                _card(
                    "l3_effective_count",
                    "风险有效持仓数（L3）",
                    risk["l3_effective_count"],
                    "number",
                    2,
                ),
                _card(
                    "l4_effective_count",
                    "风险源方差集中度（L4）",
                    risk["l4_effective_count"],
                    "number",
                    2,
                ),
                _card(
                    "l4_market_source_share",
                    "市场源占比",
                    risk["l4_market_source_share"],
                    "percent",
                    1,
                ),
                _card("l4_largest_source", largest_label, largest_value, "percent", 1),
            ],
        },
        {
            "type": "text",
            "text": "L4 描述模型下互不相关的风险源之间的方差集中度，数值越大不代表越分散；"
            "市场因子主导时分散良好的组合 L4 反而可能接近 1。",
        },
    ]
    ratio = risk["risk_contribution_ratio"]
    if not has_value(ratio):
        blocks.append({"type": "text", "text": f"风险贡献：{ratio['reason']}"})
        return blocks
    ids = [int(k) for k in ratio["value"]]
    items = [
        _card(
            f"risk_contribution_ratio:{i}",
            f"{_name(names, i)} 风险贡献占比",
            _per_stock(ratio, i),
            "percent",
            1,
        )
        for i in ids
    ]
    if level == "pro":
        items += [
            _card(
                f"risk_contribution:{i}",
                f"{_name(names, i)} 风险贡献",
                _per_stock(risk["risk_contribution"], i),
                "percentage_point",
                2,
            )
            for i in ids
        ]
        items += [
            _card(
                f"marginal_risk_contribution:{i}",
                f"{_name(names, i)} 边际风险贡献",
                _per_stock(risk["marginal_risk_contribution"], i),
                "number",
                4,
            )
            for i in ids
        ]
    blocks.append({"type": "metric_cards", "items": items})
    if any(v < 0 for v in ratio["value"].values()):
        blocks.append(
            {
                "type": "text",
                "text": "部分持仓风险贡献为负，表示在当前模型下起风险抵消作用；"
                "此时 L3 不能直接理解为独立股票数。",
            }
        )
    return blocks


def _risk_blocks(
    risk: dict[str, Any],
    names: dict[str, str],
    level: str = "retail",
    admitted_metrics: set[str] | None = None,
) -> list[dict[str, Any]]:
    """模型口径风险、逐股历史年化波动率；不可用项给出原因。"""
    blocks = _model_blocks(risk, names, level)
    if admitted_metrics is not None and has_value(risk["volatility"]["by_method"]["forward"]):
        filtered = []
        for block in blocks:
            if block["type"] == "metric_cards":
                items = [
                    item
                    for item in block["items"]
                    if item["metric_id"].split(":")[0].split(".")[0] in admitted_metrics
                ]
                if items:
                    filtered.append({**block, "items": items})
            elif block["text"].startswith("L4"):
                if "l4_effective_count" in admitted_metrics:
                    filtered.append(block)
            elif block["text"].startswith(("风险贡献：", "部分持仓风险贡献")):
                if "risk_contribution_ratio" in admitted_metrics:
                    filtered.append(block)
            elif "volatility" in admitted_metrics:
                filtered.append(block)
        blocks = filtered
    betas = risk["instrument_betas"]
    if has_value(betas):
        blocks.append(
            {
                "type": "metric_cards",
                "items": [
                    _card(
                        f"historical_volatility:{row['instrument_id']}",
                        f"{_name(names, row['instrument_id'])} 历史年化波动率",
                        row["historical_volatility"],
                        "percent",
                        1,
                    )
                    for row in betas["value"]
                ],
            }
        )
        if any(has_value(row["beta"]) for row in betas["value"]):
            blocks.append(
                {
                    "type": "metric_cards",
                    "items": [
                        _card(
                            f"{key}:{row['instrument_id']}",
                            f"{_name(names, row['instrument_id'])} {label}",
                            row[key],
                            "number",
                            2,
                        )
                        for row in betas["value"]
                        for key, label in (
                            ("beta", "Beta"),
                            ("benchmark_correlation", "基准相关性"),
                        )
                    ],
                }
            )
        elif betas["value"]:
            blocks.append(
                {"type": "text", "text": f"个股 Beta：{betas['value'][0]['beta']['reason']}"}
            )
    else:
        blocks.append({"type": "text", "text": betas["reason"]})
    return blocks


def _pairs_text(pairs: dict[str, Any], method: str, names: dict[str, str]) -> str | None:
    if not has_value(pairs):
        return None
    label = METHOD_LABELS.get(method, method)
    if not pairs["value"]:
        return f"{label}口径下没有相关系数大于 0.7 的持仓对。"
    lines = [
        f"{_name(names, x['left_instrument_id'])} 与 {_name(names, x['right_instrument_id'])}："
        f"{x['correlation']:.2f}"
        for x in pairs["value"]
    ]
    return f"{label}高相关持仓对（相关系数大于 0.7）：" + "；".join(lines)


def _structure_blocks(structure: dict[str, Any], names: dict[str, str]) -> list[dict[str, Any]]:
    """相关性热力图（模型与历史并列）、平均两两相关、高相关持仓对与风格暴露。"""
    blocks: list[dict[str, Any]] = [
        {
            "type": "correlation_matrix",
            "labels": dict(names),
            "values": structure["correlation"],
        },
        {
            "type": "metric_cards",
            "items": [
                _card(
                    f"avg_pairwise_correlation.{method}",
                    f"平均两两相关（{METHOD_LABELS.get(method, method)}）",
                    metric,
                    "number",
                    2,
                )
                for method, metric in structure["avg_pairwise_correlation"]["by_method"].items()
            ],
        },
    ]
    for method in ("forward", "historical"):
        pairs = structure["high_correlation_pairs"]["by_method"].get(method)
        text = _pairs_text(pairs, method, names) if pairs else None
        if text:
            blocks.append({"type": "text", "text": text})
    style = structure["style_exposure"]
    if has_value(style) and style["value"]:
        blocks.append(
            {
                "type": "metric_cards",
                "items": [
                    _card(
                        f"style_exposure:{code}",
                        f"风格暴露：{STYLE_FACTOR_LABELS.get(code, code)}",
                        {**style, "value": value},
                        "number",
                        2,
                    )
                    for code, value in style["value"].items()
                ],
            }
        )
    return blocks


def _comparison_blocks(
    comparison: dict[str, Any],
    admitted_metrics: set[str] | None = None,
) -> list[dict[str, Any]]:
    """把 ComparisonSection 渲染为前端可直接消费的 ReportBlock 列表（按准入清单裁剪）。"""
    blocks: list[dict[str, Any]] = []
    for pair in comparison.get("pairs", []):
        # 不把用户输入的 plan.label / plan_id 拼入正文，保持分享报告白名单脱敏一致。
        blocks.append(
            {
                "type": "text",
                "text": "调仓对比：调仓前 → 调仓后（以下变化量均为调仓后减调仓前）。",
            }
        )
        deltas = pair.get("deltas") or {}
        items = [
            _card(f"delta.{key}", label, deltas[key], fmt, decimals)
            for key, label, fmt, decimals, required in COMPARISON_DELTA_SPECS
            if key in deltas
            and (required is None or admitted_metrics is None or required in admitted_metrics)
        ]
        if admitted_metrics is None or "marginal_risk_contribution" in admitted_metrics:
            items.append(
                _card(
                    "comparison.marginal_impact",
                    "一阶边际波动影响估算",
                    pair["marginal_impact"],
                    "percentage_point",
                    2,
                )
            )
        if admitted_metrics is None or "style_exposure" in admitted_metrics:
            items.append(
                _card(
                    "comparison.overlap_with_new",
                    "新增标的因子重叠度",
                    pair["overlap_with_new"],
                    "number",
                    2,
                )
            )
        blocks.append({"type": "metric_cards", "items": items})
    return blocks


def _history_blocks(
    values: dict[str, Any],
    stats_window: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """渲染 C 区：回放说明、净值曲线、回撤路径文字解读、同期收益差与历史风险卡片。"""
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "这篮子股票的假设历史回放（建仓后买入持有、权重自然漂移、"
                "税前分红再投资、小数股、现金不计息、未扣交易成本）。"
            ),
        },
        {
            "type": "replay_chart",
            "values": values["replay"],
            "stats_window": stats_window,
        },
    ]

    drawdown = values["max_drawdown"]
    if has_value(drawdown):
        dd = drawdown["value"]
        if dd["value"] == 0:
            dd_text = "最大回撤路径：窗口内无回撤。"
        else:
            pct = f"{dd['value'] * 100:.2f}%"
            if dd.get("recovery_date"):
                dd_text = (
                    f"最大回撤路径：最大回撤 {pct}，峰值日 {dd['peak_date']}，"
                    f"谷底日 {dd['trough_date']}，恢复日 {dd['recovery_date']}，"
                    f"持续 {dd['duration_days']} 个交易日间隔。"
                )
            else:
                end_day = (
                    (drawdown.get("window_actual") or {}).get("end")
                    or (stats_window or {}).get("end")
                    or dd["trough_date"]
                )
                dd_text = (
                    f"最大回撤路径：最大回撤 {pct}，峰值日 {dd['peak_date']}，"
                    f"谷底日 {dd['trough_date']}，截至 {end_day} 尚未恢复，"
                    f"持续 {dd['duration_days']} 个交易日间隔。"
                )
        if drawdown["status"] == "degraded":
            dd_text += "（统计区间不足 120 个收盘点，回撤可能低估。）"
        blocks.append({"type": "text", "text": dd_text})
    else:
        blocks.append({"type": "text", "text": f"最大回撤路径不可用：{drawdown['reason']}"})

    cards = [
        _card(key, label, values[key], fmt, 2)
        for key, label, fmt in (
            ("replay_volatility", "历史回放年化波动率", "percent"),
            ("portfolio_beta", "组合 Beta", "number"),
            ("portfolio_benchmark_correlation", "与基准的相关性", "number"),
            ("current_drawdown", "当前回撤", "percent"),
            ("var", "历史回放单日 VaR（95%）", "percent"),
            ("cvar", "历史回放单日 CVaR（95%）", "percent"),
        )
    ]
    drawdown_card = (
        {**drawdown, "value": drawdown["value"]["value"]} if has_value(drawdown) else drawdown
    )
    cards.append(_card("max_drawdown", "最大回撤", drawdown_card, "percent", 2))

    comparison = values.get("period_comparison")
    if comparison is not None:
        if has_value(comparison):
            pv = comparison["value"]
            wa = comparison.get("window_actual") or {}
            diff_pp = pv["return_difference"] * 100
            sign = "+" if diff_pp > 0 else ""
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        f"同期累计收益对照（{wa.get('start', '')} 至 {wa.get('end', '')}，"
                        f"共 {comparison.get('sample_count', 0)} 个交易日收益）："
                        f"组合累计收益 {pv['portfolio_simple_return'] * 100:.2f}%，"
                        f"基准 {pv['benchmark_name']}（{pv['benchmark_symbol']}）"
                        f"累计收益 {pv['benchmark_simple_return'] * 100:.2f}%，"
                        f"差值 {sign}{diff_pp:.2f} 个百分点。"
                    ),
                }
            )
            cards.extend(
                [
                    _card(
                        "period_portfolio_return",
                        "统计区间组合累计收益",
                        {**comparison, "value": pv["portfolio_simple_return"]},
                        "percent",
                        2,
                    ),
                    _card(
                        "period_benchmark_return",
                        f"统计区间基准累计收益（{pv['benchmark_name']}）",
                        {**comparison, "value": pv["benchmark_simple_return"]},
                        "percent",
                        2,
                    ),
                    _card(
                        "period_return_difference",
                        "同期收益差（组合 − 基准）",
                        {**comparison, "value": pv["return_difference"]},
                        "percentage_point",
                        2,
                    ),
                ]
            )
        else:
            blocks.append(
                {"type": "text", "text": f"同期累计收益对照不可用：{comparison['reason']}"}
            )
            cards.extend(
                [
                    _card(
                        "period_portfolio_return", "统计区间组合累计收益", comparison, "percent", 2
                    ),
                    _card(
                        "period_benchmark_return", "统计区间基准累计收益", comparison, "percent", 2
                    ),
                    _card(
                        "period_return_difference",
                        "同期收益差（组合 − 基准）",
                        comparison,
                        "percentage_point",
                        2,
                    ),
                ]
            )

    blocks.append({"type": "metric_cards", "items": cards})
    return blocks


def report(
    result: dict[str, Any],
    level: str = "retail",
    *,
    industry_labels: dict[str, str] | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """按访问时的 ``user_level`` 与可选 ``detail`` 裁剪；不省略缺失原因与声明。"""
    if result["run_status"] in ("pending", "running"):
        return result
    labels = industry_labels or {}
    admitted = (
        set(result["publication"]["declared_metrics"])
        if result.get("publication") is not None
        else None
    )
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
        merged_labels = {
            **labels,
            **(a["value"].get("industry_labels", {}) if a["status"] == "ready" else {}),
        }
        add(
            pid,
            "exposure",
            "构成与敞口",
            ready(_exposure_blocks(a["value"], level, merged_labels))
            if a["status"] == "ready"
            else a,
        )
        names = {str(h["instrument_id"]): h["name"] for h in p["input"]["calculation_holdings"]}
        b = p["section_b"]
        risk_content = (
            ready(_risk_blocks(b["value"], names, level, admitted)) if b["status"] == "ready" else b
        )
        if detail == "holdings":
            comparison_block = {
                "type": "holding_risk_comparison",
                **compute_holding_risk_comparison(
                    plan_input=p["input"],
                    section_a=a,
                    section_b=b,
                    declared_metrics=admitted,
                    industry_labels=merged_labels,
                ),
            }
            if risk_content["status"] == "ready":
                risk_content = ready([comparison_block, *risk_content["value"]])
            else:
                risk_content = ready([comparison_block])
        add(pid, "risk", "风险画像", risk_content)
        history = p["section_c"]
        if history["status"] == "ready":
            history = ready(_history_blocks(history["value"], result["options"]["stats_window"]))
        add(pid, "style", "历史回放与分位", history, "history")
        d = p["section_d"]
        add(
            pid,
            "diversification",
            "关系与结构",
            ready(_structure_blocks(d["value"], names)) if d["status"] == "ready" else d,
        )
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
    comparison = result["comparison"]
    add(
        None,
        "comparison",
        "方案比较",
        ready(_comparison_blocks(comparison["value"], admitted))
        if comparison["status"] == "ready"
        else comparison,
    )
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


# ---------------------------------------------------------------------------
# 分享报告双层白名单投影（section.kind × block.type × 组合级 metric_id / 公开文案）
# ---------------------------------------------------------------------------

_SHARED_ALLOWED_BLOCKS: dict[str, frozenset[str]] = {
    "profile": frozenset({"text"}),
    "exposure": frozenset({"metric_cards", "distribution"}),
    "risk": frozenset({"metric_cards", "text"}),
    "style": frozenset({"metric_cards"}),
    "diversification": frozenset({"metric_cards"}),
    "comparison": frozenset({"text", "metric_cards"}),
    "limitations": frozenset({"text"}),
    "summary": frozenset({"text"}),
}

_SHARED_EXPOSURE_CARDS = frozenset(
    {"top1", "top3", "top5", "hhi", "l1_count", "l2_effective_count", "max_industry"}
)
_SHARED_RISK_CARDS = frozenset(
    {
        "volatility.forward",
        "daily_prediction_volatility",
        "l3_effective_count",
        "l4_effective_count",
        "l4_market_source_share",
        "l4_largest_source",
    }
)
_SHARED_STYLE_CARDS = frozenset(
    {
        "replay_volatility",
        "portfolio_beta",
        "portfolio_benchmark_correlation",
        "current_drawdown",
        "var",
        "cvar",
        "max_drawdown",
        "period_portfolio_return",
        "period_benchmark_return",
        "period_return_difference",
    }
)
_SHARED_SAFE_RISK_TEXT_PREFIXES = (
    "L4 描述模型下互不相关的风险源之间的方差集中度",
    "部分持仓风险贡献为负，表示在当前模型下起风险抵消作用",
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SHARED_TERMINATION_LABELS: dict[str, str] = {
    "delisted_no_terminal_value": "存在退市且无可靠终值的持仓",
    "valuation_unreliable": "存在估值不可靠的持仓",
    "execution_undetermined": "存在开盘或停复牌执行状态无法确定的持仓",
}
_SHARED_REASON_LABELS: dict[str, str] = {
    "not_calibrated": "模型尚未完成全区间校准，结果降级展示。",
    "factor_model_unavailable": "当前快照未取得可用的风险模型截面。",
    "history_insufficient": "统计区间内有效历史样本不足。",
    "coverage_below_threshold": "组合数据覆盖不足，该指标暂不可用或降级展示。",
    "spec_not_defined": "该项定性规则或阈值尚未确认，暂不输出。",
    "lookthrough_incomplete": "底层穿透数据不完整，暂不输出。",
    "benchmark_missing": "缺少已准入的全收益基准序列。",
    "new_listing_short_window": "存在新上市标的导致有效历史窗口不足。",
    "feature_not_available": "该分析项在当前版本尚未开放。",
    "not_applicable": "当前组合形态不适用该指标。",
    "data_not_validated": "相关数据未通过完整性或一致性核验。",
    "data_stale": "相关数据存在滞后或已过期。",
    "zero_variance": "有效样本内收益或模型方差为零，该指标不可用。",
    "valuation_lagged": "部分估值数据日期早于诊断日期。",
}


def _sanitize_shared_reason(reason_code: str | None, raw_reason: str | None) -> str:
    """按 reason_code 生成公开分享说明，不透传可能含 instrument_id 或股票代码的原始文案。"""
    code = str(reason_code or "")
    text = str(raw_reason or "")
    if code in {"replay_terminated", "execution_undetermined"}:
        date_match = _ISO_DATE_RE.search(text)
        detail = next(
            (label for token, label in _SHARED_TERMINATION_LABELS.items() if token in text),
            _SHARED_TERMINATION_LABELS["execution_undetermined"]
            if code == "execution_undetermined"
            else "存在触发回放边界条件的持仓",
        )
        if date_match:
            return f"历史回放在 {date_match.group(1)} 中止（{detail}），相关区间统计不可用。"
        return f"历史回放因边界条件中止（{detail}），相关区间统计不可用。"
    return _SHARED_REASON_LABELS.get(code, "该项指标当前不可用或已降级展示。")


def _sanitize_shared_metric(metric: dict[str, Any]) -> dict[str, Any]:
    """脱敏分享报告中 MetricValue 的 reason 字段，防止持仓标识外泄。"""
    copy = deepcopy(metric)
    if copy.get("status") != "ok":
        copy["reason"] = _sanitize_shared_reason(copy.get("reason_code"), copy.get("reason"))
    return copy


def _is_shared_card_allowed(kind: str, metric_id: str) -> bool:
    if kind == "exposure":
        return metric_id in _SHARED_EXPOSURE_CARDS
    if kind == "risk":
        return metric_id in _SHARED_RISK_CARDS
    if kind == "style":
        return metric_id in _SHARED_STYLE_CARDS
    if kind == "diversification":
        return metric_id.startswith(("avg_pairwise_correlation.", "style_exposure:"))
    if kind == "comparison":
        return metric_id.startswith("delta.") or metric_id in {
            "comparison.marginal_impact",
            "comparison.overlap_with_new",
        }
    return False


def _sanitize_shared_card(kind: str, card: dict[str, Any]) -> dict[str, Any]:
    """避免组合级卡片标签或不可用原因中携带单一股票标识。"""
    sanitized = deepcopy(card)
    if isinstance(sanitized.get("value"), dict):
        sanitized["value"] = _sanitize_shared_metric(sanitized["value"])
    if (
        kind == "risk"
        and sanitized.get("metric_id") == "l4_largest_source"
        and "的特质风险" in str(sanitized.get("label") or "")
    ):
        sanitized["label"] = "最大风险源占比（单一持仓特质风险）"
    return sanitized


def _is_shared_text_allowed(kind: str, text: str) -> bool:
    if kind == "risk":
        return text.startswith(_SHARED_SAFE_RISK_TEXT_PREFIXES)
    if kind == "comparison":
        return text.startswith("调仓对比：")
    return kind in {"profile", "limitations", "summary"}


def project_shared_report(report_data: dict[str, Any]) -> dict[str, Any]:
    """把私有报告投影为可公开分享的脱敏报告。

    按 ``section.kind`` 与 ``block.type`` 双层白名单筛选，剔除逐股持仓明细、
    ``holding_risk_comparison``、逐股卡片、含代码/权重的缺口文本及相关性标签映射，
    并对所有不可用/降级 ``reason`` 按 ``reason_code`` 重写为公开组合级说明。
    """
    projected_sections: list[dict[str, Any]] = []
    for section in report_data.get("sections") or ():
        kind = str(section.get("kind") or "")
        allowed_types = _SHARED_ALLOWED_BLOCKS.get(kind)
        if not allowed_types:
            continue
        content = section.get("content") or {}
        status = content.get("status")
        if status == "unavailable":
            safe_content = {
                **deepcopy(content),
                "reason": _sanitize_shared_reason(
                    content.get("reason_code"), content.get("reason")
                ),
            }
            projected_sections.append({"title": section["title"], "content": safe_content})
            continue
        if status != "ready":
            continue
        blocks: list[dict[str, Any]] = []
        for block in content.get("value") or ():
            btype = str(block.get("type") or "")
            if btype not in allowed_types:
                continue
            if btype == "metric_cards":
                items = [
                    _sanitize_shared_card(kind, card)
                    for card in block.get("items") or ()
                    if _is_shared_card_allowed(kind, str(card.get("metric_id") or ""))
                ]
                if items:
                    blocks.append({"type": "metric_cards", "items": items})
            elif btype == "text":
                text = str(block.get("text") or "")
                if _is_shared_text_allowed(kind, text):
                    blocks.append({"type": "text", "text": text})
            elif btype == "distribution":
                dist_block = deepcopy(block)
                if isinstance(dist_block.get("values"), dict):
                    dist_block["values"] = _sanitize_shared_metric(dist_block["values"])
                blocks.append(dist_block)
        if blocks:
            projected_sections.append({"title": section["title"], "content": ready(blocks)})

    return SharedReportResponse.model_validate(
        {
            "report_mode": report_data["report_mode"],
            "disclosures": list(report_data.get("disclosures") or ()),
            "sections": projected_sections,
        }
    ).model_dump(mode="json")


def project_public_options(
    available_options: dict[str, Any] | None,
    publication_scope: dict[str, Any],
) -> dict[str, Any]:
    """按白名单投影 ``GET /v1/diagnosis/options`` 的 ``available_options``。

    客户端仅拿到界面与请求构造所需的公开摘要，避免逐股 ``dividend_sha256``、
    ``dividend_signatures``、``delist_dates`` 或私有原件路径随扩面膨胀和外泄。
    """
    source = available_options if isinstance(available_options, dict) else {}
    projected: dict[str, Any] = {"publication_scope": deepcopy(publication_scope)}

    schemes = source.get("industry_schemes")
    if isinstance(schemes, list):
        projected["industry_schemes"] = [str(item) for item in schemes]

    benchmarks = source.get("benchmarks")
    if isinstance(benchmarks, list):
        public_benchmarks = []
        for item in benchmarks:
            if not isinstance(item, dict):
                continue
            entry: dict[str, Any] = {}
            for key in ("instrument_id", "symbol", "name", "version"):
                if key in item and item[key] is not None:
                    entry[key] = item[key]
            if entry:
                public_benchmarks.append(entry)
        projected["benchmarks"] = public_benchmarks

    replay = source.get("replay")
    if isinstance(replay, dict):
        hashes = replay.get("dividend_sha256")
        covered_count = len(hashes) if isinstance(hashes, dict) else 0
        projected["replay"] = {
            "available": covered_count > 0 and bool(replay.get("version")),
            "version": replay.get("version"),
            "through_date": replay.get("through_date"),
            "covered_count": covered_count,
        }

    bench_ind = source.get("benchmark_industry")
    if isinstance(bench_ind, dict):
        projected["benchmark_industry"] = {
            key: bench_ind[key]
            for key in ("benchmark_symbol", "effective_date", "status")
            if key in bench_ind
        }

    return projected
