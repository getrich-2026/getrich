"""风险日数据按缺失原因延迟验收；四条件 IPO 例外，无只数包络。"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from gr_data.common.ricequant_specs import semantic_hash
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.raw.ricequant.risk_dynamic import load_dynamic


PIECES = ("exposure", "specific_return", "specific_risk")
INTERFACES = (*PIECES, "factor_return", "covariance")
POLICY = {
    "id": "ipo_next_trading_day_included_v1",
    "uses_count_cap": False,
    "current_conditions": [
        "day_equals_list_date",
        "only_specific_return_missing",
        "exposure_and_specific_risk_present",
    ],
    "next_condition": "same_security_included_on_official_next_trading_day",
    "next_evidence_absent": "pending",
    "other_missing": "rejected",
    "whole_interface_empty": "rejected",
}
POLICY_SHA256 = semantic_hash(POLICY)


class DelayedEvidenceError(ValueError):
    """显式提供的验收证据无效，不可伪装为等待中的次日观察。"""


def file_sha256(path: Path) -> str:
    """文件字节 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _approved_data(path: Path, expected_sha256: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise DelayedEvidenceError("An explicit approved file SHA-256 is required")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise DelayedEvidenceError("Approved evidence file SHA-256 differs")
    return data


def _day(value: object) -> str:
    if not isinstance(value, str) or str(date.fromisoformat(value)) != value:
        raise DelayedEvidenceError("Evidence date is not ISO calendar date")
    return value


@dataclass(frozen=True)
class VerifiedRiskObservation:
    """复用既有严格 raw loader 校验的观察；完整代码是跨观察身份。"""

    path: Path
    file_sha256: str
    manifest: dict[str, Any] = field(repr=False)
    options: RiskOptions = field(repr=False)
    interface_nonempty: dict[str, bool]

    @classmethod
    def load(
        cls, path: Path, expected_sha256: str, options: RiskOptions
    ) -> VerifiedRiskObservation:
        """先核文件 SHA，再复核 Parquet／名单／覆盖／数值与既有用途身份。"""
        resolved = path.resolve()
        _approved_data(resolved, expected_sha256)
        manifest, frames = load_dynamic(resolved, options)
        return cls(
            resolved,
            expected_sha256,
            manifest,
            options,
            {piece: not frame.empty for piece, frame in frames.items()},
        )

    def verify(self) -> None:
        """拒绝已加载对象或原始文件的运行中漂移。"""
        data = _approved_data(self.path, self.file_sha256)
        if semantic_hash(json.loads(data)) != semantic_hash(self.manifest):
            raise DelayedEvidenceError("Loaded observation manifest changed")
        manifest, frames = load_dynamic(self.path, self.options)
        if manifest != self.manifest or self.interface_nonempty != {
            piece: not frame.empty for piece, frame in frames.items()
        }:
            raise DelayedEvidenceError("Loaded observation evidence changed")

    @property
    def evidence(self) -> dict[str, str]:
        """同时绑定文件字节与 raw 标准化语义哈希。"""
        return {
            "path": str(self.path),
            "file_sha256": self.file_sha256,
            "manifest_sha256": semantic_hash(self.manifest),
            "observation_id": self.manifest["observation_id"],
        }


@dataclass(frozen=True)
class VerifiedTradingCalendar:
    """完整交易日历查询的冻结证据；禁止使用稀疏探测日期推算下一交易日。"""

    path: Path
    sha256: str
    payload: dict[str, Any] = field(repr=False)

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> VerifiedTradingCalendar:
        """格式含 source/market/query_start/query_end/complete_query/trading_days。"""
        resolved = path.resolve()
        payload = json.loads(_approved_data(resolved, expected_sha256))
        if (
            payload.get("schema_version") != 1
            or payload.get("market") != "cn"
            or payload.get("complete_query") is not True
            or not payload.get("source")
        ):
            raise DelayedEvidenceError(
                "A complete Chinese-market trading-calendar query is required"
            )
        start, end = _day(payload["query_start"]), _day(payload["query_end"])
        days = [_day(value) for value in payload["trading_days"]]
        if (
            start > end
            or not days
            or days != sorted(set(days))
            or any(not start <= day <= end for day in days)
        ):
            raise DelayedEvidenceError("Trading-calendar evidence is incomplete or invalid")
        return cls(resolved, expected_sha256, payload)

    def verify(self) -> None:
        if json.loads(_approved_data(self.path, self.sha256)) != self.payload:
            raise DelayedEvidenceError("Trading-calendar evidence changed")

    def next_trading_day(self, current: str) -> str | None:
        """只能取完整查询中当前交易日的直接后继；尾端无后继时等待补证。"""
        self.verify()
        days = self.payload["trading_days"]
        if current not in days:
            raise DelayedEvidenceError(
                "Current observation day is absent from the trading calendar"
            )
        index = days.index(current)
        return days[index + 1] if index + 1 < len(days) else None

    @property
    def evidence(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "file_sha256": self.sha256,
            "source": self.payload["source"],
            "query_start": self.payload["query_start"],
            "query_end": self.payload["query_end"],
        }


def _symbol(row: Mapping[str, Any]) -> str:
    canonical = row.get("evidence", {}).get("canonical", {}).get("symbol")
    symbol = row.get("canonical_symbol")
    if not isinstance(symbol, str) or not symbol.endswith((".SH", ".SZ")) or canonical != symbol:
        raise DelayedEvidenceError("Full canonical security identity differs")
    return symbol


def ipo_first_day_conditions(day: str, list_date: str | None, pieces: Mapping[str, object]) -> bool:
    """供已验收基线与新日 gate 共用的前三条件；不读取任何次日字段。"""
    return (
        day == list_date
        and set(pieces) == set(PIECES)
        and all(type(value) is bool for value in pieces.values())
        and pieces == {"exposure": True, "specific_return": False, "specific_risk": True}
    )


def evaluate_delayed_day(
    current: VerifiedRiskObservation,
    *,
    calendar: VerifiedTradingCalendar | None = None,
    next_observation: VerifiedRiskObservation | None = None,
) -> dict[str, Any]:
    """只有上市首日仅缺特异收益、暴露／风险存在且下一交易日 included 才例外。

    缺次日或日历后继为 pending；当前任何其他缺失、整接口空及明确未恢复均拒绝。
    next 观察只证明目标证券恢复，不会因此接受 next 日自身的数据。
    """
    current.verify()
    manifest = current.manifest
    day, model = manifest["day"], manifest["identity"]["model"]
    counts, coverage = manifest["coverage_counts"], manifest["coverage"]
    report = {
        "model": model,
        "day": day,
        "candidate": counts["candidate"],
        "complete": counts["complete"],
        "status": "accepted",
        "policy": copy.deepcopy(POLICY),
        "policy_sha256": POLICY_SHA256,
        "current_observation": current.evidence,
        "calendar": None,
        "next_observation": None,
        "missing": [],
        "reject_reasons": [],
        "pending_reasons": [],
        "publication_authorized": False,
    }
    if (
        type(counts["candidate"]) is not int
        or counts["candidate"] <= 0
        or len(coverage) != counts["candidate"]
    ):
        report["reject_reasons"].append("invalid_coverage_denominator")
    if set(current.interface_nonempty) != set(INTERFACES) or not all(
        current.interface_nonempty.values()
    ):
        report["reject_reasons"].append("whole_interface_empty")
    seen = set()
    for row in coverage:
        symbol = _symbol(row)
        if symbol in seen:
            raise DelayedEvidenceError("Duplicate canonical security in current coverage")
        seen.add(symbol)
        if row["status"] == "included":
            continue
        pieces = row["pieces"]
        listed = row["evidence"]["canonical"].get("list_date")
        ipo = row["status"] == "partial_bundle" and ipo_first_day_conditions(day, listed, pieces)
        reason = "ipo_waiting_next_trading_day"
        if not ipo:
            if row["status"] in {"universe_boundary_unknown", "sdk_filtered", "unmapped_symbol"}:
                reason = "identity_" + row["status"]
            elif listed != day:
                reason = "non_listing_day_missing"
            elif not pieces["exposure"]:
                reason = "exposure_missing"
            elif not pieces["specific_risk"]:
                reason = "specific_risk_missing"
            else:
                reason = "unexpected_missing_pattern"
        item = {
            "symbol": symbol,
            "list_date": listed,
            "pieces": dict(pieces),
            "status": row["status"],
            "reason": reason,
            "next_included": None,
            "record_instrument_id": row["instrument_id"],
            "canonical_evidence_instrument_id": row["evidence"]["canonical"].get("instrument_id"),
            "source_record_sha256": semantic_hash(row),
        }
        report["missing"].append(item)
        if not ipo:
            report["reject_reasons"].append("other_missing:" + symbol)
    if report["reject_reasons"]:
        report["status"] = "rejected"
        return report
    if not report["missing"]:
        return report
    if calendar is None:
        report.update(status="pending", pending_reasons=["next_trading_calendar_evidence_absent"])
        return report
    next_day = calendar.next_trading_day(day)
    report["calendar"] = calendar.evidence
    report["expected_next_trading_day"] = next_day
    if next_day is None or next_observation is None:
        report.update(status="pending", pending_reasons=["next_trading_day_observation_absent"])
        return report
    next_observation.verify()
    report["next_observation"] = next_observation.evidence
    following = next_observation.manifest
    if (
        following["day"] != next_day
        or following["variant_id"] != manifest["variant_id"]
        or following["identity"] != manifest["identity"]
    ):
        report.update(status="rejected", reject_reasons=["next_observation_day_or_variant_differs"])
        return report
    next_rows = {}
    for row in following["coverage"]:
        symbol = _symbol(row)
        if symbol in next_rows:
            raise DelayedEvidenceError("Duplicate canonical security in next coverage")
        next_rows[symbol] = row
    for item in report["missing"]:
        row = next_rows.get(item["symbol"])
        included = (
            row is not None
            and row["status"] == "included"
            and row["pieces"] == dict.fromkeys(PIECES, True)
        )
        item["next_included"] = included
        item["next_record_instrument_id"] = row["instrument_id"] if row is not None else None
        item["next_record_sha256"] = semantic_hash(row) if row is not None else None
        item["reason"] = (
            "ipo_next_trading_day_recovered" if included else "ipo_not_recovered_next_trading_day"
        )
        if not included:
            report["reject_reasons"].append("next_day_not_recovered:" + item["symbol"])
    if report["reject_reasons"]:
        report["status"] = "rejected"
    return report


def monthly_summary(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """按已选择观察去重汇总，pending/rejected 永远不冒充 accepted。"""
    chosen = {}
    for report in reports:
        key = report["model"], report["day"]
        if key in chosen and semantic_hash(report) != semantic_hash(chosen[key]):
            raise DelayedEvidenceError(
                "Conflicting delayed decisions require explicit observation selection"
            )
        chosen[key] = report
    groups = defaultdict(list)
    for report in chosen.values():
        groups[report["model"], report["day"][:7]].append(report)
    result = []
    for (model, month), rows in sorted(groups.items()):
        counts = Counter(row["status"] for row in rows)
        entries = [(row["status"], item) for row in rows for item in row["missing"]]
        result.append(
            {
                "model": model,
                "month": month,
                "policy_sha256": POLICY_SHA256,
                "model_days_by_status": dict(counts),
                "missing_by_status": {
                    status: {
                        "missing_security_days": sum(key == status for key, _ in entries),
                        "unique_missing_instruments": len(
                            {item["symbol"] for key, item in entries if key == status}
                        ),
                    }
                    for status in ("accepted", "pending", "rejected")
                },
                "reason_metrics": {
                    reason: {
                        "missing_security_days": sum(
                            item["reason"] == reason for _, item in entries
                        ),
                        "unique_missing_instruments": len(
                            {item["symbol"] for _, item in entries if item["reason"] == reason}
                        ),
                    }
                    for reason in sorted({item["reason"] for _, item in entries})
                },
                "per_security_evidence": [
                    {"day": row["day"], "decision": row["status"], **item}
                    for row in rows
                    for item in row["missing"]
                ],
                "observation_bindings": [
                    {
                        "day": row["day"],
                        "current": row["current_observation"],
                        "next": row["next_observation"],
                        "calendar": row["calendar"],
                    }
                    for row in rows
                ],
            }
        )
    return result
