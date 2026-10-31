"""持仓输入规范化：份额、合并、量化与回显（PA-02，设计 §7.2 第 3～4 步、§7.8 第 3 条）。

两个分母必须分开：``input_share`` 以完整输入（含未识别代码）为分母，供 TopN 与覆盖率；
``calculation_weight`` 只在已识别子集内归一化，供 HHI、L1、L2 等计算。混用任何一个
都会让「10 只里有 3 只没识别」看起来像一个完整的 7 只组合。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any


#: §7.8：计算与哈希共用的权重精度，8 位小数，即和为 1e8 的整数份额。
WEIGHT_UNITS = 100_000_000
WEIGHT_QUANT = Decimal(1) / Decimal(WEIGHT_UNITS)


class NoCalculableHoldingsError(ValueError):
    """方案在量化后没有任何可计算的正权重已识别标的（设计 §7.2 第 4 步，返回 422）。"""


@dataclass(frozen=True)
class InputRow:
    """一行原始输入及其解析结果。``instrument`` 为 None 表示未识别。"""

    input_index: int
    input_symbol: str
    input_weight: Decimal | None
    normalized_symbol: str
    instrument: Mapping[str, Any] | None  # 至少含 instrument_id、symbol、name


@dataclass(frozen=True)
class NormalizedPlan:
    weight_mode: str
    summary: dict[str, Any]  # PlanInputSummary 同形
    quantized: dict[int, int]  # instrument_id → 整数份额（和为 WEIGHT_UNITS），只含正值


def quantize_weights(raw: Mapping[int, Decimal]) -> dict[int, int]:
    """把正权重归一化为和恰为 ``WEIGHT_UNITS`` 的整数份额。

    ``ROUND_HALF_EVEN`` 舍入；残差补给原权重最大者，并列取 instrument_id 最小者，
    保证输入顺序不改变结果。量化为 0 的标的保留在返回值中，由调用方按零权重处理。

    Raises:
        ValueError: 没有正权重。
    """
    positive = {k: v for k, v in raw.items() if v > 0}
    total = sum(positive.values(), Decimal(0))
    if total <= 0:
        raise ValueError("quantize_weights requires at least one positive weight")
    units = {
        k: int((v / total * WEIGHT_UNITS).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
        for k, v in positive.items()
    }
    residual = WEIGHT_UNITS - sum(units.values())
    if residual:
        largest = min(positive, key=lambda k: (-positive[k], k))
        units[largest] += residual
    return units


def _ratio(value: Decimal) -> float:
    """Decimal 份额转浮点；只截掉表示误差，不改变口径。"""
    return float(min(max(value, Decimal(0)), Decimal(1)))


def normalize_plan(rows: Sequence[InputRow]) -> NormalizedPlan:
    """按 PA-02 计算份额、合并重复标的并量化计算权重。

    * 显式权重：先按原始输入总和（含零权重与未识别行）计份额，再按标的合并；
    * 全部缺省：先按唯一标的（未识别代码按规范化代码）去重，再等权；
    * 零权重与量化后为 0 的标的回显为 ``zero_weight``，不计入名义持仓数和计算。

    Raises:
        NoCalculableHoldingsError: 没有可计算的正权重已识别标的。
    """
    weight_mode = "user" if any(r.input_weight is not None for r in rows) else "equal"

    def key_of(row: InputRow) -> int | str:
        # 已识别按 instrument_id 合并（不同别名视为同一标的），未识别按规范化代码合并。
        if row.instrument is not None:
            return int(row.instrument["instrument_id"])
        return row.normalized_symbol

    first_index: dict[int | str, int] = {}
    statuses: list[str] = []
    merged_into: list[int | None] = []
    for row in rows:
        key = key_of(row)
        if weight_mode == "user" and row.input_weight == 0:
            statuses.append("zero_weight")
            merged_into.append(None)
        elif key in first_index:
            statuses.append("duplicate")
            merged_into.append(first_index[key])
        else:
            first_index[key] = row.input_index
            statuses.append("resolved" if row.instrument is not None else "unresolved")
            merged_into.append(None)

    shares: dict[int | str, Decimal] = {}
    if weight_mode == "user":
        total = sum((r.input_weight or Decimal(0) for r in rows), Decimal(0))
        for row in rows:
            if row.input_weight:
                key = key_of(row)
                shares[key] = shares.get(key, Decimal(0)) + row.input_weight / total
    else:
        each = Decimal(1) / Decimal(len(first_index))
        shares = dict.fromkeys(first_index, each)

    id_shares = {k: v for k, v in shares.items() if isinstance(k, int)}
    # 未识别份额直接加总，已识别份额取其补：没有未识别行时恰为 0，不受除法尾数影响。
    unresolved_share = sum((v for k, v in shares.items() if isinstance(k, str)), Decimal(0))
    resolved_share = Decimal(1) - unresolved_share
    raw = {k: v for k, v in id_shares.items() if v > 0}
    if not raw:
        raise NoCalculableHoldingsError("no positive holdings could be resolved")
    units = quantize_weights(raw)
    positive = {k: v for k, v in units.items() if v > 0}
    if not positive:
        raise NoCalculableHoldingsError("all resolved holdings quantize to zero weight")

    instruments: dict[int, Mapping[str, Any]] = {}
    for idx, row in enumerate(rows):
        if row.instrument is None:
            continue
        iid = int(row.instrument["instrument_id"])
        instruments.setdefault(iid, row.instrument)
        if statuses[idx] == "resolved" and iid not in positive:
            statuses[idx] = "zero_weight"  # PA-02：量化后为 0，按零权重处理

    echoes = [
        {
            "input_index": row.input_index,
            "input_symbol": row.input_symbol,
            "input_weight": None if row.input_weight is None else str(row.input_weight),
            "normalized_symbol": row.normalized_symbol,
            "instrument_id": None
            if row.instrument is None
            else int(row.instrument["instrument_id"]),
            "name": None if row.instrument is None else row.instrument.get("name"),
            "status": statuses[idx],
            "merged_into_input_index": merged_into[idx],
        }
        for idx, row in enumerate(rows)
    ]
    calculation_holdings = [
        {
            "instrument_id": iid,
            "symbol": str(instruments[iid]["symbol"]),
            "name": str(instruments[iid].get("name") or instruments[iid]["symbol"]),
            "input_share": _ratio(id_shares[iid]),
            "calculation_weight": units[iid] / WEIGHT_UNITS,
        }
        for iid in dict.fromkeys(
            int(r.instrument["instrument_id"]) for r in rows if r.instrument is not None
        )
        if iid in positive
    ]
    summary = {
        "weight_mode": weight_mode,
        "holdings": echoes,
        "calculation_holdings": calculation_holdings,
        "input_weight": 1.0,
        "resolved_weight": _ratio(resolved_share),
        "unresolved_weight": _ratio(unresolved_share),
        "calculation_coverage_ratio": _ratio(resolved_share),
        "normalized_within_resolved_subset": unresolved_share > 0,
    }
    return NormalizedPlan(weight_mode=weight_mode, summary=summary, quantized=positive)
