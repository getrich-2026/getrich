"""模块 A：构成与敞口（PA-04～PA-07、设计 §7.3.2 2026-10-20／21 补充）。

全部在已识别子集的计算权重上计算，结果进入跨用户共享的计算载体；TopN 改按完整输入
份额与覆盖率阈值在组装时处理（见 :mod:`gr_api.diagnosis_calc.coverage`），不把请求
覆盖率混入缓存。n ≤ 100 时纯 Python 在微秒级，不引入 numpy。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from gr_api.diagnosis_calc.metrics import degraded, ok, unavailable


#: 分布的保留键：分类缺失与估值缺失／异常单列，不剔除后重新归一化（PA-05、PA-07）。
UNCLASSIFIED = "unclassified"
MISSING_OR_INVALID = "missing_or_invalid"
NON_POSITIVE = "non_positive"

TOPN_NS: tuple[int, ...] = (1, 3, 5)

#: 元 → 亿元。total_mv 入库统一为元（T1），档位阈值用亿元；换算只在这里做一次。
YUAN_PER_YI = Decimal(100_000_000)


@dataclass(frozen=True)
class CalcHolding:
    instrument_id: int
    weight: Decimal  # 已识别子集内的量化计算权重，合计为 1


@dataclass(frozen=True)
class IndustryAssignment:
    code: str
    name: str


@dataclass(frozen=True)
class Valuation:
    trading_day: date
    total_mv: Decimal | None  # 元
    pb: Decimal | None


def _ratio(value: Decimal) -> float:
    return float(min(max(value, Decimal(0)), Decimal(1)))


def topn(shares: Iterable[Decimal], ns: Sequence[int] = TOPN_NS) -> list[dict[str, Any]]:
    """按份额降序取前 N 加总；少于 N 只时按实际数量加总并回显 ``actual_count``。"""
    ordered = sorted((s for s in shares if s > 0), reverse=True)
    if not ordered:
        raise ValueError("topn requires at least one positive share")
    return [
        {
            "n": n,
            "actual_count": min(n, len(ordered)),
            "weight": _ratio(sum(ordered[:n], Decimal(0))),
        }
        for n in ns
    ]


def band_key(value: Decimal, bands: Sequence[float]) -> str:
    """按升序阈值分档，边界值归较高档；键形如 ``lt_100``、``100_500``、``ge_3000``。"""
    edges = [Decimal(str(b)) for b in bands]
    if edges != sorted(edges) or len(set(edges)) != len(edges) or not edges:
        raise ValueError("bands must be strictly increasing and non-empty")
    labels = [_fmt(e) for e in edges]
    if value < edges[0]:
        return f"lt_{labels[0]}"
    for i in range(1, len(edges)):
        if value < edges[i]:
            return f"{labels[i - 1]}_{labels[i]}"
    return f"ge_{labels[-1]}"


def _fmt(edge: Decimal) -> str:
    return str(int(edge)) if edge == edge.to_integral_value() else format(edge.normalize(), "f")


def band_keys(bands: Sequence[float]) -> list[str]:
    edges = [Decimal(str(b)) for b in bands]
    labels = [_fmt(e) for e in edges]
    return (
        [f"lt_{labels[0]}"]
        + [f"{labels[i - 1]}_{labels[i]}" for i in range(1, len(labels))]
        + [f"ge_{labels[-1]}"]
    )


def mktcap_bucket(total_mv_yuan: Decimal | None, bands_yi: Sequence[float]) -> str:
    """总市值档位；缺失、非有限或非正值归 ``missing_or_invalid``，不归入最低档。"""
    yi = _mktcap_yi(total_mv_yuan)
    return MISSING_OR_INVALID if yi is None else band_key(yi, bands_yi)


def _mktcap_yi(total_mv_yuan: Decimal | None) -> Decimal | None:
    if total_mv_yuan is None or not total_mv_yuan.is_finite() or total_mv_yuan <= 0:
        return None
    return total_mv_yuan / YUAN_PER_YI


def pb_bucket(pb: Decimal | None, bands: Sequence[float]) -> str:
    """PB 档位；净资产为负等非正值单列 ``non_positive``，不当作「便宜」。"""
    if pb is None or not pb.is_finite():
        return MISSING_OR_INVALID
    if pb <= 0:
        return NON_POSITIVE
    return band_key(pb, bands)


def distribution(
    holdings: Sequence[CalcHolding], labels: Mapping[int, str], *, keys: Iterable[str] = ()
) -> dict[str, float]:
    """按标签汇总计算权重；``keys`` 中的档位即使为 0 也输出，便于前端固定图例。"""
    totals: dict[str, Decimal] = dict.fromkeys(keys, Decimal(0))
    for h in holdings:
        key = labels[h.instrument_id]
        totals[key] = totals.get(key, Decimal(0)) + h.weight
    return {k: _ratio(v) for k, v in totals.items()}


def data_coverage(holdings: Sequence[CalcHolding], missing: Iterable[int]) -> float:
    """已识别子集内具备该指标必要数据的权重占比。"""
    absent = set(missing)
    return _ratio(sum((h.weight for h in holdings if h.instrument_id not in absent), Decimal(0)))


def compute_exposure(
    holdings: Sequence[CalcHolding],
    *,
    as_of: date,
    params: Mapping[str, Any],
    industry_scheme: str | None,
    industry: Mapping[int, IndustryAssignment],
    category: Mapping[int, Mapping[str, str]],
    valuation: Mapping[int, Valuation],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """计算模块 A 的共享载体与跨用户安全的数据事实。

    Args:
        holdings: 已识别子集，计算权重合计为 1。
        as_of: 诊断日期；估值日期早于它时标 ``valuation_lagged``。
        params: 口径版本参数，读取 ``mktcap_bands_yi`` 与 ``pb_bands``。
        industry_scheme: 已验证可用的行业体系；None 表示当前数据版本没有可用体系。
        industry / category / valuation: 按 instrument_id 取到的分类与估值，缺失即不在映射中。

    Returns:
        ``(metrics, facts)``。metrics 为 ExposureMetrics 同形字典，状态只反映子集内
        的数据可得性；facts 记录各指标在子集内的数据覆盖率、缺失标的与行业名称，
        供组装时按完整输入应用 PA-13 阈值。
    """
    if not holdings:
        raise ValueError("compute_exposure requires at least one calculation holding")
    ids = [h.instrument_id for h in holdings]
    weights = [h.weight for h in holdings]

    hhi = sum((w * w for w in weights), Decimal(0))
    metrics: dict[str, Any] = {
        # 载体中按计算权重给出；组装时改为完整输入份额（2026-10-21 PA-04）。
        "topn": ok(topn(weights)),
        "hhi": ok(_ratio(hhi)),
        "l1_count": ok(len(holdings)),
        "l2_effective_count": ok(float(Decimal(1) / hhi)),
        # 一期只接受沪深 A 股个股（PA-01），不存在需要穿透的基金持仓。
        "lookthrough_coverage": ok(1.0),
    }
    facts: dict[str, Any] = {"coverage": {}, "missing": {}, "industry_names": {}}

    # 行业（PA-05）：只在已验证的体系下出数，缺失单列 unclassified。
    if industry_scheme is None:
        reason = "申万一级行业（SW2021）及历史归属尚未完成接入验证，行业分布暂不可用。"
        metrics["industry_distribution"] = unavailable(
            reason_code="data_not_validated", reason=reason
        )
        metrics["max_industry"] = unavailable(reason_code="data_not_validated", reason=reason)
    else:
        labels = {i: industry[i].code if i in industry else UNCLASSIFIED for i in ids}
        dist = distribution(holdings, labels)
        names = {a.code: a.name for a in industry.values()}
        metrics["industry_distribution"] = ok(dist)
        classified = {k: v for k, v in dist.items() if k != UNCLASSIFIED and v > 0}
        if classified:
            code = min(classified, key=lambda k: (-classified[k], k))
            metrics["max_industry"] = ok(
                {"industry_code": code, "industry_name": names[code], "weight": classified[code]}
            )
        else:
            metrics["max_industry"] = unavailable(
                reason_code="coverage_below_threshold",
                reason="组合内没有标的具备行业分类，无法给出最大行业。",
            )
        missing = [i for i in ids if i not in industry]
        facts["coverage"]["industry"] = data_coverage(holdings, missing)
        facts["missing"]["industry"] = missing
        facts["industry_names"] = names

    # 资产类别与市场（PA-06）：缺失同样单列，不重新归一化。
    for metric_id, field in (
        ("market_distribution", "market"),
        ("asset_category_distribution", "asset_category"),
    ):
        labels = {
            i: str(category[i][field]) if category.get(i, {}).get(field) else UNCLASSIFIED
            for i in ids
        }
        metrics[metric_id] = ok(distribution(holdings, labels))
    missing = [i for i in ids if i not in category]
    facts["coverage"]["category"] = data_coverage(holdings, missing)
    facts["missing"]["category"] = missing

    # 市值与 PB（PA-07）：取不晚于诊断日期的最近一条，不设天数上限，滞后的照常分档。
    bands_yi = list(params.get("mktcap_bands_yi") or [100, 500, 1000, 3000])
    pb_bands = list(params.get("pb_bands") or [1, 2, 4, 8])
    cap_labels = {
        i: mktcap_bucket(valuation[i].total_mv if i in valuation else None, bands_yi) for i in ids
    }
    pb_labels = {i: pb_bucket(valuation[i].pb if i in valuation else None, pb_bands) for i in ids}
    metrics["mktcap_distribution"] = ok(
        distribution(holdings, cap_labels, keys=[*band_keys(bands_yi), MISSING_OR_INVALID])
    )
    metrics["pb_distribution"] = ok(
        distribution(
            holdings, pb_labels, keys=[*band_keys(pb_bands), NON_POSITIVE, MISSING_OR_INVALID]
        )
    )
    cap_missing = [i for i in ids if cap_labels[i] == MISSING_OR_INVALID]
    pb_missing = [i for i in ids if pb_labels[i] == MISSING_OR_INVALID]
    lagged = [i for i in ids if i in valuation and valuation[i].trading_day < as_of]
    facts["coverage"]["mktcap"] = data_coverage(holdings, cap_missing)
    facts["coverage"]["pb"] = data_coverage(holdings, pb_missing)
    facts["missing"]["mktcap"] = cap_missing
    facts["missing"]["pb"] = pb_missing
    facts["valuation_lagged"] = lagged
    facts["valuation_lagged_weight"] = _ratio(
        sum((h.weight for h in holdings if h.instrument_id in set(lagged)), Decimal(0))
    )

    metrics["instrument_facts"] = ok(
        {str(i): _instrument_facts(valuation.get(i), as_of=as_of) for i in ids}
    )
    return metrics, facts


def _valuation_metric(value: Decimal | None, *, lagged: bool, label: str) -> dict[str, Any]:
    if value is None or not value.is_finite():
        return unavailable(
            reason_code="coverage_below_threshold", reason=f"缺少有效的{label}数据。"
        )
    if lagged:
        return degraded(
            float(value),
            reason_code="valuation_lagged",
            reason=f"{label}取自早于诊断日期的最近一条记录（如停牌）。",
        )
    return ok(float(value))


def _instrument_facts(row: Valuation | None, *, as_of: date) -> dict[str, Any]:
    lagged = row is not None and row.trading_day < as_of
    return {
        "total_mv_yi": _valuation_metric(
            _mktcap_yi(row.total_mv if row is not None else None), lagged=lagged, label="总市值"
        ),
        # PB 原值展示，非正值不截断（PA-07）
        "pb": _valuation_metric(row.pb if row is not None else None, lagged=lagged, label="PB"),
        "valuation_date": row.trading_day.isoformat() if row is not None else None,
        # DS10：roe_waa 单位与可用时间尚未核验，一期不展示，不回退单季或年化口径。
        "roe": unavailable(
            reason_code="data_not_validated",
            reason="年度加权平均 ROE 的来源单位与披露时间尚未核验，暂不展示。",
        ),
        "roe_report_year": None,
        "roe_ann_date": None,
    }
