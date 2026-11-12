from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


_CANONICAL_STOCK = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)")


@dataclass(frozen=True)
class RiskDay:
    """一个精确模型日的库存事实，不是正式发布许可。

    日期是事件日；observed_at 是带时区的实际观测时间。accepted 仅表示
    已有整包验收证据，不能代替校准、历史 PIT 或正式发布。
    """

    model: str
    day: date
    storage_status: str
    run_id: str | None = None
    variant_id: str | None = None
    model_id: str | None = None
    observed_at: datetime | None = None
    calibrated: bool = False
    horizon: str | None = None
    factor_axis_hash: str | None = None
    reason: str | None = None
    variance_unit: str | None = None


@dataclass(frozen=True)
class RiskCoverage:
    """同一模型日/run 的真实暴露与特异风险交集，不允许跨日借覆盖。"""

    model: str
    day: date
    run_id: str | None
    symbols: tuple[str, ...]


def _require_identity(snapshot: RiskDay) -> None:
    if (
        not snapshot.run_id
        or not snapshot.variant_id
        or not snapshot.model_id
        or not snapshot.horizon
        or not snapshot.factor_axis_hash
        or snapshot.variance_unit not in {"pct2_annual", "dec2_annual", "pct2_daily", "dec2_daily"}
        or snapshot.observed_at is None
        or snapshot.observed_at.tzinfo is None
        or snapshot.observed_at.utcoffset() is None
    ):
        raise ValueError(
            "Accepted risk day lacks exact identity, units, axis, horizon or observed time"
        )


def assess_day(
    snapshot: RiskDay,
    *,
    model: str,
    day: date,
    holdings: Mapping[str, Decimal],
    coverage: RiskCoverage,
    known_at: datetime | None = None,
) -> dict[str, object]:
    """精确日期的只读计算预检；不回退日期、不换模型、不剔除缺失持仓。

    Args:
        snapshot: 必须与请求完全相同的模型日；无数据也传该日的缺口事实。
        model: 显式选择的模型版本，例如 v2，禁止隐式替代。
        day: 请求风险截面日期，不是默认为最近有数据的日期。
        holdings: 完整 canonical 代码到有符号 NAV 权重；不自动重新归一化。
        coverage: 同一 run 中暴露与特异风险实际齐全的完整代码及其模型／日期绑定。
        known_at: 可选历史可知时间，必须带时区；晚采集快照不能用于早期决策。

    Returns:
        模型／run／数据日、逐只覆盖与绝对权重覆盖率，以及研究预检状态。
        formal_ready 永远为 False；正式读取仍由发布机制控制。

    Raises:
        ValueError: 模型／日期不符、权重非法或缺少验收快照的身份／观测时间。
    """
    if snapshot.model != model or snapshot.day != day:
        raise ValueError("Exact requested model and date are required; fallback is forbidden")
    if model not in {"v1", "v2", "v2trd"}:
        raise ValueError("Unknown risk model")
    if known_at is not None and (known_at.tzinfo is None or known_at.utcoffset() is None):
        raise ValueError("known_at must be timezone-aware")
    for code, weight in holdings.items():
        if not isinstance(code, str) or _CANONICAL_STOCK.fullmatch(code) is None:
            raise ValueError("Holdings require full canonical symbols")
        if not isinstance(weight, Decimal) or not weight.is_finite():
            raise ValueError("Holdings require finite Decimal signed weights")
    positions = {code: weight for code, weight in holdings.items() if weight != 0}
    accepted = snapshot.storage_status == "accepted"
    if accepted:
        _require_identity(snapshot)
    if coverage.model != model or coverage.day != day or coverage.run_id != snapshot.run_id:
        raise ValueError("Holdings coverage belongs to another model, day or run")
    if any(
        not isinstance(s, str) or _CANONICAL_STOCK.fullmatch(s) is None for s in coverage.symbols
    ):
        raise ValueError("Coverage requires full canonical stock symbols")
    if len(coverage.symbols) != len(set(coverage.symbols)):
        raise ValueError("Holdings coverage contains duplicate canonical symbols")
    covered = set(coverage.symbols) if accepted else set()
    found = sorted(set(positions) & covered)
    missing = sorted(set(positions) - covered)
    gross = sum((abs(w) for w in positions.values()), Decimal(0))
    covered_gross = sum((abs(positions[s]) for s in found), Decimal(0))
    reasons = []
    if not positions:
        reasons.append("empty_nonzero_holdings")
    if not accepted:
        reasons.append(snapshot.reason or snapshot.storage_status)
    elif missing:
        reasons.append("holdings_not_fully_covered")
    if (
        accepted
        and known_at is not None
        and snapshot.observed_at is not None
        and snapshot.observed_at > known_at
    ):
        reasons.append("snapshot_observed_after_knowledge_time")
    return {
        "requested_model": model,
        "requested_day": day.isoformat(),
        "used_model": snapshot.model if accepted else None,
        "data_day": snapshot.day.isoformat() if accepted else None,
        "run_id": snapshot.run_id if accepted else None,
        "variant_id": snapshot.variant_id if accepted else None,
        "model_id": snapshot.model_id if accepted else None,
        "forecast_horizon": snapshot.horizon if accepted else None,
        "declared_variance_unit": snapshot.variance_unit if accepted else None,
        "unit_certification": "empirical_contract_not_supplier_certified",
        "factor_axis_hash": snapshot.factor_axis_hash if accepted else None,
        "observed_at": snapshot.observed_at.isoformat()
        if accepted and snapshot.observed_at is not None
        else None,
        "calibrated": snapshot.calibrated if accepted else False,
        "storage_status": snapshot.storage_status,
        "nonzero_holdings": len(positions),
        "covered_count": len(found),
        "covered_symbols": found,
        "missing_symbols": missing,
        "gross_weight": str(gross),
        "covered_gross_weight": str(covered_gross),
        "gross_weight_coverage": str(covered_gross / gross) if gross and accepted else None,
        "diagnostic_inputs_ready": not reasons,
        "reasons": reasons,
        "weights_renormalized": False,
        "fallback_used": False,
        "formal_ready": False,
        "formal_block_reason": "formal_risk_reader_closed",
        "calculation_scope": "ex_post_diagnostic_only_not_calibration_or_historical_PIT",
    }


def assess_range(
    snapshots: Mapping[date, RiskDay],
    *,
    model: str,
    start: date,
    end: date,
    expected_days: Sequence[date],
) -> dict[str, object]:
    """报告完整交易日历内的每个缺日，禁止只用有数据的日期推导分母。

    expected_days 必须来自完整市场日历，升序且唯一，限定在闭区间内。
    这里只检查库存；没有逐日持仓覆盖证据时不宣称区间可计算。
    """
    if start > end or model not in {"v1", "v2", "v2trd"}:
        raise ValueError("Invalid model or date interval")
    days = list(expected_days)
    if days != sorted(set(days)) or any(d < start or d > end for d in days):
        raise ValueError("Expected trading calendar must be unique, ordered and in range")
    missing = []
    used = []
    for day in days:
        row = snapshots.get(day)
        if row is not None and (row.model != model or row.day != day):
            raise ValueError("Range contains a different model or date")
        if row is None or row.storage_status != "accepted":
            missing.append(
                {
                    "day": day.isoformat(),
                    "reason": row.reason or row.storage_status if row else "snapshot_absent",
                }
            )
        else:
            _require_identity(row)
            used.append(
                {
                    "model": row.model,
                    "data_day": day.isoformat(),
                    "run_id": row.run_id,
                    "variant_id": row.variant_id,
                }
            )
    return {
        "requested_model": model,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected_trading_days": len(days),
        "accepted_days": len(used),
        "missing_dates": missing,
        "used_snapshots": used,
        "storage_interval_complete": bool(days) and not missing,
        "holdings_coverage_status": "requires_each_day_positions_and_coverage",
        "diagnostic_inputs_ready": False,
        "formal_ready": False,
        "formal_block_reason": "formal_risk_reader_closed",
        "fallback_used": False,
    }
