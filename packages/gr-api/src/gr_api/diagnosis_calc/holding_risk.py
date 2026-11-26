"""持仓仓位与风险贡献对照（批次 A：A1 逐股明细 + A2 行业汇总与排序）。

只消费快照已固定的输入回显、section_a 暴露事实和 section_b 模型风险结果，
不查询数据库、不重算协方差、不重新归一化未识别子集。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from gr_api.diagnosis_calc.exposure import UNCLASSIFIED
from gr_api.diagnosis_calc.metrics import degraded, has_value, ok, unavailable
from gr_api.diagnosis_calc.weights import WEIGHT_UNITS, quantize_weights, snapshot_input_shares


#: 冻结行业分布与逐股重建分布的对账容差（容纳浮点 JSON 往返误差，同时能检出缺失归属）。
_INDUSTRY_RECONCILE_TOL = Decimal("1e-5")
#: 完整组合逐股风险贡献份额的守恒容差（允许单股为负或超过 1，但全组合之和须约等于 1）。
_RISK_SHARE_SUM_TOL = Decimal("1e-4")
_ZERO_GAP_EPS = Decimal("1e-6")
_WEIGHT_UNITS_DEC = Decimal(WEIGHT_UNITS)


def _unavailable_pair(
    code: str,
    reason: str,
    *,
    quantized_zero_count: int = 0,
    quantized_zero_weight: str = "0",
    meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metric = unavailable(reason_code=code, reason=reason)
    return {
        "headline": None,
        "stocks": metric,
        "industries": dict(metric),
        "quantized_zero_count": quantized_zero_count,
        "quantized_zero_weight": quantized_zero_weight,
        **(dict(meta) if meta else {}),
    }


def _model_meta(section_b: Mapping[str, Any]) -> dict[str, Any]:
    value = section_b.get("value") if section_b.get("status") == "ready" else None
    if not isinstance(value, Mapping):
        return {
            "model_id": None,
            "model_date": None,
            "model_run_id": None,
            "calibrated": None,
        }
    model_date = value.get("model_date")
    return {
        "model_id": value.get("model_id"),
        "model_date": None if model_date is None else str(model_date),
        "model_run_id": value.get("model_run_id"),
        "calibrated": value.get("calibrated"),
    }


def _wrap_status(
    value: Any,
    source_metric: Mapping[str, Any],
    *,
    secondary_metric: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """继承原指标的 ok / degraded 状态、方法、原因与置信度。"""
    method = str(source_metric.get("method") or "forward")
    if source_metric.get("status") == "degraded":
        return degraded(
            value,
            method=method,
            reason_code=str(source_metric["reason_code"]),
            reason=str(source_metric["reason"]),
            confidence=str(source_metric["confidence"]),
        )
    if secondary_metric is not None and secondary_metric.get("status") == "degraded":
        return degraded(
            value,
            method=method,
            reason_code=str(secondary_metric["reason_code"]),
            reason=str(secondary_metric["reason"]),
            confidence=str(secondary_metric["confidence"]),
        )
    return ok(value, method=method)


def _format_pct(value: Decimal) -> str:
    return f"{value * Decimal(100):.1f}%"


def _build_headline(stock_rows: list[tuple[dict[str, Any], Decimal, Decimal, Decimal]]) -> str:
    """用实际结果生成平实的首屏发现文字（批次 A §2）。"""
    if len(stock_rows) == 1:
        row, cap, risk, _gap = stock_rows[0]
        return (
            f"{row['name']}（{row['symbol']}）是本方案唯一有效持仓，"
            f"模型采用的资金权重为 {_format_pct(cap)}，风险贡献份额为 {_format_pct(risk)}。"
        )
    if all(abs(gap) < _ZERO_GAP_EPS for _, _, _, gap in stock_rows):
        return "本方案各持仓的风险贡献份额与模型采用的资金权重基本一致。"
    top_row, cap, risk, gap = stock_rows[0]
    gap_pp = gap * Decimal(100)
    if gap > 0:
        return (
            f"{top_row['name']}（{top_row['symbol']}）占这篮子股票模型采用资金的 "
            f"{_format_pct(cap)}，模型估计它贡献了 {_format_pct(risk)} 的组合波动风险，"
            f"高出仓位 {gap_pp:.1f} 个百分点。"
        )
    return (
        f"{top_row['name']}（{top_row['symbol']}）占模型采用资金的 {_format_pct(cap)}，"
        f"模型估计其风险贡献份额为 {_format_pct(risk)}（差值 {gap_pp:+.1f} 个百分点）。"
    )


def _verify_quantized_holdings(
    plan_input: Mapping[str, Any],
    raw_weights: Mapping[int, Decimal],
) -> tuple[dict[int, tuple[dict[str, Any], int, Decimal]], list[int], str | None]:
    """核对原始正份额、8 位量化整数单位及冻结 calculation_holdings。

    返回 ``(positive_map, quantized_zero_ids, error_reason)``。
    """
    n_positive = len(raw_weights)
    if n_positive == 0:
        return {}, [], "方案缺少有效正权重证券，无法计算仓位与风险对照。"

    expected_units = quantize_weights(raw_weights)
    if sum(expected_units.values()) != WEIGHT_UNITS:
        return {}, [], "权重量化整数单位合计不等于 100,000,000，已停算仓位与风险对照。"

    # 校验单股与原始份额的绝对差上限：0.5 × n × 1e-8
    max_tol = Decimal("0.5") * Decimal(n_positive) / _WEIGHT_UNITS_DEC
    for iid, raw_share in raw_weights.items():
        q_share = Decimal(expected_units[iid]) / _WEIGHT_UNITS_DEC
        if abs(q_share - raw_share) > max_tol:
            return {}, [], "权重量化误差超过 0.5×n×1e-8 上限，已停算仓位与风险对照。"

    # 按证券合并统计回显状态，避免零权重或重复输入行掩盖同一证券的非零持仓。
    echo_statuses: dict[int, set[str]] = {}
    for row in plan_input.get("holdings") or ():
        iid = row.get("instrument_id")
        if iid is not None:
            echo_statuses.setdefault(int(iid), set()).add(str(row.get("status")))

    expected_positive = {iid: u for iid, u in expected_units.items() if u > 0}
    quantized_zero_ids = sorted(iid for iid, u in expected_units.items() if u == 0)

    for zid in quantized_zero_ids:
        statuses = echo_statuses.get(zid, set())
        if "zero_weight" not in statuses:
            return (
                {},
                quantized_zero_ids,
                f"量化归零证券 {zid} 缺少 zero_weight 回显记录，已停算仓位与风险对照。",
            )

    calc_rows = plan_input.get("calculation_holdings")
    if not isinstance(calc_rows, list):
        return {}, quantized_zero_ids, "快照缺少冻结的 calculation_holdings，无法核对模型资金权重。"

    positive_map: dict[int, tuple[dict[str, Any], int, Decimal]] = {}
    unit_sum = 0
    for item in calc_rows:
        iid = int(item["instrument_id"])
        if iid in positive_map:
            return {}, quantized_zero_ids, "冻结计算持仓存在重复证券，已停算仓位与风险对照。"
        raw_cw = item.get("calculation_weight")
        if not isinstance(raw_cw, (int, float)) or not math.isfinite(float(raw_cw)) or raw_cw <= 0:
            return (
                {},
                quantized_zero_ids,
                "冻结计算持仓存在非正或非有限权重，已停算仓位与风险对照。",
            )
        expected_u = expected_positive.get(iid)
        if expected_u is None:
            return (
                {},
                quantized_zero_ids,
                "冻结计算持仓与量化后有效正权重证券集合不一致，已停算仓位与风险对照。",
            )
        frozen_dec = Decimal(str(raw_cw))
        frozen_units = int((frozen_dec * _WEIGHT_UNITS_DEC).to_integral_value())
        if frozen_units != expected_u or abs(
            frozen_dec - Decimal(expected_u) / _WEIGHT_UNITS_DEC
        ) > Decimal("1e-12"):
            return (
                {},
                quantized_zero_ids,
                (
                    f"证券 {item.get('symbol', iid)} 的冻结计算权重与 8 位量化结果不符，"
                    "已停算仓位与风险对照。"
                ),
            )
        unit_sum += frozen_units
        positive_map[iid] = (item, frozen_units, Decimal(expected_u) / _WEIGHT_UNITS_DEC)

    if set(positive_map.keys()) != set(expected_positive.keys()):
        return (
            {},
            quantized_zero_ids,
            "冻结计算持仓缺少有效正权重证券，已停算仓位与风险对照。",
        )
    if unit_sum != WEIGHT_UNITS:
        return (
            {},
            quantized_zero_ids,
            "有效计算持仓整数单位合计不等于 100,000,000，已停算仓位与风险对照。",
        )

    return positive_map, quantized_zero_ids, None


def _compute_industry_comparison(
    section_a: Mapping[str, Any],
    stock_entries: list[tuple[int, dict[str, Any], Decimal, Decimal]],
    stocks_metric: Mapping[str, Any],
    extra_industry_labels: Mapping[str, str] | None,
) -> dict[str, Any]:
    """A2：按冻结逐股归属汇总行业仓位与风险份额，并与冻结行业分布对账。"""
    if section_a.get("status") != "ready":
        return unavailable(
            reason_code="data_not_validated",
            reason="快照缺少构成与敞口结果，仅展示逐股对照。",
        )

    a_value = section_a.get("value")
    if not isinstance(a_value, Mapping):
        return unavailable(
            reason_code="data_not_validated",
            reason="快照构成与敞口结构无效，仅展示逐股对照。",
        )

    industry_dist = a_value.get("industry_distribution")
    if not isinstance(industry_dist, dict) or not has_value(industry_dist):
        code = (
            str(industry_dist.get("reason_code") or "data_not_validated")
            if isinstance(industry_dist, dict)
            else "data_not_validated"
        )
        reason = (
            str(industry_dist.get("reason") or "行业分类体系不可用，仅展示逐股对照。")
            if isinstance(industry_dist, dict)
            else "行业分类体系不可用，仅展示逐股对照。"
        )
        return unavailable(reason_code=code, reason=reason)

    inst_facts = a_value.get("instrument_facts")
    if not isinstance(inst_facts, dict) or not has_value(inst_facts):
        return unavailable(
            reason_code="data_not_validated",
            reason="快照缺少逐股行业归属事实，无法还原当时行业汇总。",
        )

    facts_map = inst_facts["value"]
    frozen_dist = industry_dist["value"]
    if not isinstance(facts_map, Mapping) or not isinstance(frozen_dist, Mapping):
        return unavailable(
            reason_code="data_not_validated",
            reason="快照行业归属或分布格式无效，仅展示逐股对照。",
        )

    merged_labels: dict[str, str] = {}
    if extra_industry_labels:
        merged_labels.update({str(k): str(v) for k, v in extra_industry_labels.items()})
    raw_labels = a_value.get("industry_labels")
    if isinstance(raw_labels, Mapping):
        merged_labels.update({str(k): str(v) for k, v in raw_labels.items()})

    cap_by_ind: dict[str, Decimal] = {}
    risk_by_ind: dict[str, Decimal] = {}
    name_by_ind: dict[str, str] = {}

    for iid, _row, cap_dec, risk_dec in stock_entries:
        fact = facts_map.get(str(iid))
        if not isinstance(fact, Mapping):
            return unavailable(
                reason_code="data_not_validated",
                reason="历史快照缺少部分有效持仓的逐股行业归属事实，无法核对行业汇总，仅展示逐股对照。",
            )
        raw_code = fact.get("industry_code")
        code = (
            str(raw_code).strip()
            if isinstance(raw_code, str) and raw_code.strip()
            else UNCLASSIFIED
        )
        cap_by_ind[code] = cap_by_ind.get(code, Decimal(0)) + cap_dec
        risk_by_ind[code] = risk_by_ind.get(code, Decimal(0)) + risk_dec
        if code not in name_by_ind:
            if code == UNCLASSIFIED:
                name_by_ind[code] = "未分类"
            else:
                fact_name = fact.get("industry_name")
                if isinstance(fact_name, str) and fact_name.strip():
                    name_by_ind[code] = fact_name.strip()
                else:
                    name_by_ind[code] = merged_labels.get(code) or code

    # 与同快照冻结 industry_distribution 对账：识别 7.2 以前缺省 industry_code=None 的老快照。
    frozen_positive: dict[str, Decimal] = {}
    for k, v in frozen_dist.items():
        if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            return unavailable(
                reason_code="data_not_validated",
                reason="冻结行业分布包含非有限值，仅展示逐股对照。",
            )
        dec_v = Decimal(str(v))
        if dec_v > 0:
            frozen_positive[str(k)] = dec_v

    if set(cap_by_ind.keys()) != set(frozen_positive.keys()):
        return unavailable(
            reason_code="data_not_validated",
            reason="历史快照的逐股行业归属与冻结行业分布无法对账（可能为旧版快照缺逐股行业），仅展示逐股对照。",
        )
    for code, rebuilt_weight in cap_by_ind.items():
        if abs(rebuilt_weight - frozen_positive[code]) > _INDUSTRY_RECONCILE_TOL:
            return unavailable(
                reason_code="data_not_validated",
                reason="历史快照的逐股行业归属小计与冻结行业分布不一致，仅展示逐股对照。",
            )

    rows_with_key: list[tuple[Decimal, str, dict[str, Any]]] = []
    for code, cap_dec in cap_by_ind.items():
        risk_dec = risk_by_ind[code]
        gap_dec = risk_dec - cap_dec
        rows_with_key.append(
            (
                gap_dec,
                code,
                {
                    "industry_code": code,
                    "industry_name": name_by_ind[code],
                    "capital_weight": float(cap_dec),
                    "risk_share": float(risk_dec),
                    "risk_share_minus_weight": float(gap_dec),
                },
            )
        )

    rows_with_key.sort(key=lambda item: (-item[0], item[1]))
    sorted_rows = [item[2] for item in rows_with_key]
    return _wrap_status(sorted_rows, stocks_metric, secondary_metric=industry_dist)


def compute_holding_risk_comparison(
    *,
    plan_input: Mapping[str, Any],
    section_a: Mapping[str, Any],
    section_b: Mapping[str, Any],
    declared_metrics: set[str] | frozenset[str] | None = None,
    industry_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """按单个方案计算仓位与风险贡献份额对照（A1 逐股 + A2 行业）。

    核验顺序：
    1. 完整输入分母无未识别正份额（``unresolved_weight == 0``）；
    2. 发布已准入 ``risk_contribution_ratio``，且 ``model_coverage.status == "complete"``；
    3. ``risk_contribution_ratio`` 有值且全为有限数（方差为零等状态直接继承不可用）；
    4. 原始正权重按 8 位量化后与冻结 ``calculation_holdings`` 及风险份额证券集合完全一致；
    5. 逐股计算 ``gap = risk_share - capital_weight`` 并降序排列；
    6. 按冻结逐股归属与冻结 ``industry_distribution`` 对账后，行业内先分别加总再作差。
    """
    meta = _model_meta(section_b)

    try:
        raw_weights, missing_unresolved = snapshot_input_shares(plan_input)
    except Exception:
        return _unavailable_pair(
            "data_not_validated",
            "快照缺少完整的持仓输入信息，无法核对完整输入分母。",
            meta=meta,
        )

    unresolved_weight = plan_input.get("unresolved_weight")
    if (
        missing_unresolved
        or not isinstance(unresolved_weight, (int, float))
        or unresolved_weight > 0
    ):
        return _unavailable_pair(
            "coverage_below_threshold",
            "存在未识别正权重持仓，无法按完整组合计算仓位与风险贡献对照。",
            meta=meta,
        )

    if declared_metrics is None or "risk_contribution_ratio" not in declared_metrics:
        return _unavailable_pair(
            "feature_not_available",
            "快照缺少已准入指标声明或未准入逐股风险贡献占比，无法输出仓位与风险对照。",
            meta=meta,
        )

    if section_b.get("status") != "ready" or not isinstance(section_b.get("value"), Mapping):
        code = str(section_b.get("reason_code") or "factor_model_unavailable")
        reason = str(section_b.get("reason") or "模型风险结果不可用，无法计算仓位与风险对照。")
        return _unavailable_pair(code, reason, meta=meta)

    b_value = section_b["value"]
    model_coverage = b_value.get("model_coverage")
    if not isinstance(model_coverage, Mapping) or model_coverage.get("status") != "complete":
        reason = (
            str(model_coverage.get("reason"))
            if isinstance(model_coverage, Mapping) and model_coverage.get("reason")
            else "快照缺少完整的模型持仓覆盖证据，无法计算完整组合的仓位与风险对照。"
        )
        return _unavailable_pair(
            "coverage_below_threshold",
            reason,
            meta=meta,
        )

    ratio_metric = b_value.get("risk_contribution_ratio")
    if not isinstance(ratio_metric, dict) or not has_value(ratio_metric):
        code = (
            str(ratio_metric.get("reason_code") or "factor_model_unavailable")
            if isinstance(ratio_metric, dict)
            else "factor_model_unavailable"
        )
        reason = (
            str(ratio_metric.get("reason") or "逐股风险贡献占比不可用，无法计算仓位与风险对照。")
            if isinstance(ratio_metric, dict)
            else "逐股风险贡献占比不可用，无法计算仓位与风险对照。"
        )
        return _unavailable_pair(code, reason, meta=meta)

    # 防御：若前向年化方差显式存在且 <= 0 或非有限，整组不可用。
    ann_var = b_value.get("annual_variance")
    if isinstance(ann_var, dict) and has_value(ann_var):
        var_val = ann_var.get("value")
        if (
            not isinstance(var_val, (int, float))
            or not math.isfinite(float(var_val))
            or var_val <= 0
        ):
            return _unavailable_pair(
                "zero_variance",
                "组合模型方差为零或无效，无法计算仓位与风险贡献对照。",
                meta=meta,
            )

    positive_map, quantized_zero_ids, verify_err = _verify_quantized_holdings(
        plan_input, raw_weights
    )
    zero_weight_dec = sum((raw_weights[zid] for zid in quantized_zero_ids), Decimal(0))
    zero_weight_str = format(zero_weight_dec.normalize(), "f") if zero_weight_dec > 0 else "0"
    if verify_err is not None:
        return _unavailable_pair(
            "data_not_validated",
            verify_err,
            quantized_zero_count=len(quantized_zero_ids),
            quantized_zero_weight=zero_weight_str,
            meta=meta,
        )

    ratio_values = ratio_metric["value"]
    if not isinstance(ratio_values, Mapping):
        return _unavailable_pair(
            "data_not_validated",
            "逐股风险贡献占比数据结构无效，已停算仓位与风险对照。",
            quantized_zero_count=len(quantized_zero_ids),
            quantized_zero_weight=zero_weight_str,
            meta=meta,
        )

    parsed_ratios: dict[int, Decimal] = {}
    for raw_k, raw_v in ratio_values.items():
        try:
            iid = int(raw_k)
        except (TypeError, ValueError):
            return _unavailable_pair(
                "data_not_validated",
                "逐股风险贡献占比包含非法证券标识，已停算仓位与风险对照。",
                quantized_zero_count=len(quantized_zero_ids),
                quantized_zero_weight=zero_weight_str,
                meta=meta,
            )
        if not isinstance(raw_v, (int, float)) or not math.isfinite(float(raw_v)):
            return _unavailable_pair(
                "data_not_validated",
                "逐股风险贡献占比包含非有限数值，已停算仓位与风险对照。",
                quantized_zero_count=len(quantized_zero_ids),
                quantized_zero_weight=zero_weight_str,
                meta=meta,
            )
        parsed_ratios[iid] = Decimal(str(raw_v))

    if set(parsed_ratios.keys()) != set(positive_map.keys()):
        return _unavailable_pair(
            "data_not_validated",
            "模型风险贡献证券集合与冻结有效计算持仓不一致，已停算仓位与风险对照。",
            quantized_zero_count=len(quantized_zero_ids),
            quantized_zero_weight=zero_weight_str,
            meta=meta,
        )

    total_risk_share = sum(parsed_ratios.values(), Decimal(0))
    if abs(total_risk_share - Decimal(1)) > _RISK_SHARE_SUM_TOL:
        return _unavailable_pair(
            "data_not_validated",
            "完整组合的逐股风险贡献份额合计偏离 100%，已停算仓位与风险对照。",
            quantized_zero_count=len(quantized_zero_ids),
            quantized_zero_weight=zero_weight_str,
            meta=meta,
        )

    ranked: list[tuple[dict[str, Any], Decimal, Decimal, Decimal]] = []
    stock_entries_for_ind: list[tuple[int, dict[str, Any], Decimal, Decimal]] = []
    for iid, (calc_row, _units, cap_dec) in positive_map.items():
        risk_dec = parsed_ratios[iid]
        gap_dec = risk_dec - cap_dec
        row = {
            "instrument_id": iid,
            "symbol": str(calc_row["symbol"]),
            "name": str(calc_row.get("name") or calc_row["symbol"]),
            "capital_weight": float(cap_dec),
            "risk_share": float(risk_dec),
            "risk_share_minus_weight": float(gap_dec),
        }
        ranked.append((row, cap_dec, risk_dec, gap_dec))
        stock_entries_for_ind.append((iid, row, cap_dec, risk_dec))

    # 按未舍入的差降序，同值按完整代码升序。
    ranked.sort(key=lambda item: (-item[3], item[0]["symbol"]))
    stock_rows = [item[0] for item in ranked]
    stocks_metric = _wrap_status(stock_rows, ratio_metric)
    industries_metric = _compute_industry_comparison(
        section_a,
        stock_entries_for_ind,
        stocks_metric,
        industry_labels,
    )

    return {
        "headline": _build_headline(ranked),
        "stocks": stocks_metric,
        "industries": industries_metric,
        "quantized_zero_count": len(quantized_zero_ids),
        "quantized_zero_weight": zero_weight_str,
        **meta,
    }
