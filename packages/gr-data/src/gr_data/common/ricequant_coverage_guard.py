"""从已验收风险覆盖基线推导整数包络；纯离线，不替代既有身份／数值门禁。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any


MODELS = ("v1", "v2", "v2trd")
INDIVIDUAL = ("exposure", "specific_return", "specific_risk")
INTERFACES = (*INDIVIDUAL, "factor_return", "covariance")
IDENTITY_STATUSES = {"universe_boundary_unknown", "sdk_filtered", "unmapped_symbol"}
MISSING_STATUSES = IDENTITY_STATUSES | {"partial_bundle", "provider_not_returned"}
EVENT_REASONS = {
    "new_listing_non_first_day": "new_listing_non_first_day_with_evidence",
    "suspension": "suspension_with_evidence",
    "code_change": "code_change_with_evidence",
}


def file_hash(path: Path) -> str:
    """文件字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_hash(value: object) -> str:
    """标准化 JSON 语义哈希。"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _day(value: object) -> str:
    if not isinstance(value, str) or str(date.fromisoformat(value)) != value:
        raise ValueError("Expected an ISO calendar date")
    return value


def symbol_of(row: Mapping[str, Any]) -> str:
    """完整代码为唯一跨库证券键；不同来源 ID 不参与相等判断。"""
    canonical = row.get("evidence", {}).get("canonical", {})
    codes = [
        value
        for value in (
            row.get("target_symbol"),
            row.get("canonical_symbol"),
            canonical.get("symbol"),
        )
        if value is not None
    ]
    if (
        not codes
        or any(not isinstance(code, str) or not code.endswith((".SH", ".SZ")) for code in codes)
        or len(set(codes)) != 1
    ):
        raise ValueError("Missing or conflicting full canonical symbol")
    return codes[0]


def classify_missing(
    row: Mapping[str, Any], events: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """只用当日事实归因；下一交易日恢复信息不参与运行决策。

    非首日新股／停牌／换码需要当日、同完整代码、已核定能解释缺失的事件证据。
    事件发生本身不能自动当成接口缺失的原因；冲突解释保留 unknown_reason。
    """
    day, symbol = _day(row["day"]), symbol_of(row)
    pieces = row["pieces"]
    if (
        set(pieces) != set(INDIVIDUAL)
        or any(type(value) is not bool for value in pieces.values())
        or all(pieces.values())
    ):
        raise ValueError("Missing row requires exact boolean piece evidence and a missing piece")
    status = row["status"]
    if status not in MISSING_STATUSES:
        raise ValueError("Missing row status is invalid")
    canonical = row.get("evidence", {}).get("canonical", {})
    listed = canonical.get("list_date")
    result = {
        "model": row["model"],
        "day": day,
        "symbol": symbol,
        "pieces": dict(pieces),
        "status": status,
        "record_instrument_id": row.get("instrument_id"),
        "canonical_evidence_instrument_id": canonical.get("instrument_id"),
        "reason": "unknown_reason",
        "reason_evidence": [],
        "existing_identity_gate_required": status in IDENTITY_STATUSES,
    }
    if status in IDENTITY_STATUSES:
        result["reason"] = "existing_identity_status"
        return result
    if listed == day and pieces == {
        "exposure": True,
        "specific_return": False,
        "specific_risk": True,
    }:
        result.update(
            reason="ipo_first_day_missing_specific_return",
            reason_evidence=[
                {
                    "list_date": listed,
                    "basis": "same_day_listing_and_only_specific_return_missing",
                }
            ],
        )
        return result
    valid = []
    for event in events:
        if (
            event.get("kind") not in EVENT_REASONS
            or event.get("symbol") != symbol
            or event.get("day") != day
            or event.get("explains_missing") is not True
            or not isinstance(event.get("reference"), str)
            or not event["reference"]
            or not isinstance(event.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", event["sha256"])
        ):
            continue
        if event["kind"] == "new_listing_non_first_day" and (
            not isinstance(listed, str) or not listed < day
        ):
            continue
        valid.append(dict(event))
    reasons = {event["kind"] for event in valid}
    if len(reasons) == 1:
        result.update(reason=EVENT_REASONS[next(iter(reasons))], reason_evidence=valid)
    elif valid:
        result["reason_evidence"] = valid
        result["unknown_detail"] = "conflicting_explicit_explanations"
    return result


def allowed_missing(candidate: int, envelope: Mapping[str, Any]) -> int:
    """min(max_count,ceil(candidate*max_fraction))，全程整数，不引入经验倍数。"""
    if type(candidate) is not int or candidate <= 0:
        raise ValueError("Candidate denominator must be a positive integer")
    maximum = envelope["max_missing_count"]
    fraction = envelope["max_missing_fraction"]
    numerator, denominator = fraction["numerator"], fraction["denominator"]
    if (
        any(type(value) is not int for value in (maximum, numerator, denominator))
        or maximum < 0
        or not 0 <= numerator <= denominator
        or denominator <= 0
    ):
        raise ValueError("Baseline envelope is invalid")
    return min(maximum, (candidate * numerator + denominator - 1) // denominator)


def evaluate_day(
    envelope: Mapping[str, Any],
    daily: Mapping[str, Any],
    missing: Sequence[Mapping[str, Any]],
    interface_nonempty: Mapping[str, bool],
    events: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """检查新增覆盖包络；unknown_reason 仅告警，既有身份／数值契约继续必需。"""
    day, model = _day(daily["day"]), daily["model"]
    if model != envelope["model"]:
        raise ValueError("Baseline model differs")
    candidate, complete = daily["candidate"], daily["complete"]
    reasons = []
    valid_counts = (
        type(candidate) is int
        and candidate > 0
        and type(complete) is int
        and 0 <= complete <= candidate
    )
    cap = allowed_missing(candidate, envelope) if valid_counts else None
    if not valid_counts:
        reasons.append("invalid_coverage_denominator")
    elif candidate - complete != len(missing):
        reasons.append("coverage_accounting_mismatch")
    rows = []
    seen = set()
    for row in missing:
        if row["day"] != day or row["model"] != model:
            raise ValueError("Missing row model/day differs from denominator")
        item = classify_missing(row, events)
        if item["symbol"] in seen:
            raise ValueError("Duplicate missing security")
        seen.add(item["symbol"])
        rows.append(item)
    if set(interface_nonempty) != set(INTERFACES) or any(
        type(value) is not bool for value in interface_nonempty.values()
    ):
        reasons.append("invalid_interface_evidence")
    else:
        reasons += [
            "interface_empty:" + piece for piece in INTERFACES if not interface_nonempty[piece]
        ]
    if valid_counts and cap is not None and len(missing) > cap:
        reasons.append("missing_count_above_empirical_envelope")
    unknown = [row for row in rows if row["reason"] == "unknown_reason"]
    identity = [row for row in rows if row["existing_identity_gate_required"]]
    return {
        "model": model,
        "day": day,
        "candidate": candidate,
        "complete": complete,
        "missing_count": len(missing),
        "allowed_missing_count": cap,
        "passes_coverage_guard": not reasons,
        "reject_reasons": reasons,
        "warnings": ["unknown_reason"] if unknown else [],
        "attributions": rows,
        "unknown_reason_rows": unknown,
        "existing_identity_anomalies": identity,
        "existing_contracts_still_required": True,
        "publication_authorized": False,
        "next_day_recovery_used_for_decision": False,
    }


@dataclass(frozen=True)
class ValidatedCoverageBaseline:
    """显式批准 SHA 绑定的经验包络；运行期间不自动接受变化后的文件。"""

    path: Path
    sha256: str
    payload: dict[str, Any] = field(repr=False)
    payload_sha256: str

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> ValidatedCoverageBaseline:
        """校验外部批准文件、三模型及整数包络；必须先于任何 SDK 请求。"""
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("Coverage baseline requires an explicit approved SHA-256")
        resolved = path.resolve()
        if file_hash(resolved) != expected_sha256:
            raise ValueError("Coverage baseline SHA-256 differs")
        payload = json.loads(resolved.read_text())
        if (
            payload.get("schema_version") != 1
            or payload.get("formula")
            != "min(max_missing_count,ceil(candidate*max_missing_fraction))"
            or set(payload.get("models", {})) != set(MODELS)
            or payload.get("unknown_reason_is_rejection_threshold") is not False
        ):
            raise ValueError("Coverage baseline schema or interpretation differs")
        for model, envelope in payload["models"].items():
            if envelope.get("model") != model:
                raise ValueError("Coverage baseline model identity differs")
            allowed_missing(1, envelope)
        return cls(resolved, expected_sha256, payload, semantic_hash(payload))

    def verify(self) -> None:
        """拒绝文件或已加载 payload 的运行中变更。"""
        data = self.path.read_bytes()
        if (
            hashlib.sha256(data).hexdigest() != self.sha256
            or semantic_hash(json.loads(data)) != self.payload_sha256
            or semantic_hash(self.payload) != self.payload_sha256
        ):
            raise ValueError("Frozen coverage baseline changed")

    @property
    def evidence(self) -> dict[str, str]:
        """可写入 gate/state/逐日审计的非敏感证明。"""
        return {"path": str(self.path), "sha256": self.sha256, "formula": self.payload["formula"]}


def _percentile(values: list[int], percent: int) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) * percent + 99) // 100 - 1]


def monthly_summary(
    daily: Sequence[Mapping[str, Any]], attribution: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """按已选观察汇总；重复相同事实幂等，冲突拒绝，不自动选最新观察。"""
    days = {}
    for row in daily:
        key = row["model"], row["day"]
        if key in days and (row["candidate"], row["complete"]) != (
            days[key]["candidate"],
            days[key]["complete"],
        ):
            raise ValueError("Conflicting daily coverage in monthly summary")
        days[key] = row
    items = {}
    for row in attribution:
        key = row["model"], row["day"], row["symbol"]
        if key in items and any(
            row[field] != items[key][field] for field in ("reason", "pieces", "status")
        ):
            raise ValueError("Conflicting missing attribution in monthly summary")
        items[key] = row
    for key, row in days.items():
        if row["candidate"] - row["complete"] != sum(item[:2] == key for item in items):
            raise ValueError("Monthly attribution denominator does not reconcile")
    if any(key[:2] not in days for key in items):
        raise ValueError("Monthly attribution lacks a daily denominator")
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in days.values():
        groups[row["model"], row["day"][:7]].append(row)
    result = []
    for (model, month), rows in sorted(groups.items()):
        selected = [row for key, row in items.items() if key[0] == model and key[1][:7] == month]
        reasons = sorted({row["reason"] for row in selected})
        metrics = {
            reason: {
                "missing_security_days": sum(row["reason"] == reason for row in selected),
                "unique_missing_instruments": len(
                    {row["symbol"] for row in selected if row["reason"] == reason}
                ),
            }
            for reason in reasons
        }
        result.append(
            {
                "model": model,
                "month": month,
                "model_days": len(rows),
                "candidate_security_days": sum(row["candidate"] for row in rows),
                "complete_security_days": sum(row["complete"] for row in rows),
                "missing_security_days": len(selected),
                "unique_missing_instruments": len({row["symbol"] for row in selected}),
                "days_with_missing": sum(row["candidate"] > row["complete"] for row in rows),
                "reason_metrics": metrics,
                "unknown_reason_count": sum(row["reason"] == "unknown_reason" for row in selected),
                "existing_identity_anomaly_count": sum(
                    row["existing_identity_gate_required"] for row in selected
                ),
            }
        )
    return result


def derive_baseline(
    ledger: Sequence[Mapping[str, Any]], missing: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """从已验收记录重新计算每日、每月、逐证券归因和独立次日审计。

    数据规模为数千模型日／缺失行，内存 O(日数+缺失行数)。原数据库局部 ID
    与快照 ID 可不同；完整代码负责关联，run_id 只核对同一来源导出的一致性。
    """
    days = {}
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in ledger:
        key = row["model"], _day(row["day"])
        if (
            key in days
            or row["model"] not in MODELS
            or type(row["candidate"]) is not int
            or row["candidate"] <= 0
            or type(row["complete"]) is not int
            or not 0 <= row["complete"] <= row["candidate"]
        ):
            raise ValueError("Baseline ledger has invalid or duplicate model-days")
        days[key] = dict(row)
    if not days:
        raise ValueError("Baseline ledger is empty")
    unique = set()
    for row in missing:
        key = row["model"], _day(row["day"])
        security_key = (*key, symbol_of(row))
        if (
            key not in days
            or security_key in unique
            or row.get("run_id") != days[key].get("run_id")
        ):
            raise ValueError("Baseline missing rows do not match the daily ledger")
        classify_missing(row)
        unique.add(security_key)
        groups[key].append(row)
    daily = []
    for key, row in sorted(days.items(), key=lambda item: (item[0][1], item[0][0])):
        records = groups[key]
        if row["candidate"] - row["complete"] != len(records):
            raise ValueError("Baseline missing denominator does not reconcile")
        attrs = [classify_missing(record) for record in records]
        daily.append(
            {
                **row,
                "missing_count": len(records),
                "missing_fraction": {
                    "numerator": len(records),
                    "denominator": row["candidate"],
                },
                "reason_counts": dict(Counter(item["reason"] for item in attrs)),
                "unknown_reason_count": sum(item["reason"] == "unknown_reason" for item in attrs),
                "existing_identity_anomaly_count": sum(
                    item["existing_identity_gate_required"] for item in attrs
                ),
            }
        )
    envelopes = {}
    for model in sorted({row["model"] for row in daily}):
        rows = [row for row in daily if row["model"] == model]
        counts = [row["missing_count"] for row in rows]
        fraction = max(Fraction(row["missing_count"], row["candidate"]) for row in rows)
        maximum = max(counts)
        envelopes[model] = {
            "model": model,
            "model_days": len(rows),
            "first_day": min(row["day"] for row in rows),
            "last_day": max(row["day"] for row in rows),
            "max_missing_count": maximum,
            "max_missing_fraction": {
                "numerator": fraction.numerator,
                "denominator": fraction.denominator,
            },
            "missing_count_distribution": dict(sorted(Counter(counts).items())),
            "p95_missing_count": _percentile(counts, 95),
            "p99_missing_count": _percentile(counts, 99),
            "percentile_method": "nearest_rank",
            "max_unknown_reason_count_observed": max(row["unknown_reason_count"] for row in rows),
            "unknown_reason_is_rejection_threshold": False,
            "max_count_samples": [row for row in rows if row["missing_count"] == maximum],
            "max_fraction_samples": [
                row for row in rows if Fraction(row["missing_count"], row["candidate"]) == fraction
            ],
        }
    attribution = [
        {
            **classify_missing(row),
            "run_id": row.get("run_id"),
            "source_record_sha256": semantic_hash(row),
        }
        for row in missing
    ]
    monthly = monthly_summary(daily, attribution)
    calendar = {
        model: sorted(day for model_key, day in days if model_key == model) for model in envelopes
    }
    recovery = []
    for row in missing:
        model, day, symbol = row["model"], row["day"], symbol_of(row)
        sequence = calendar[model]
        index = sequence.index(day)
        expected = sequence[index + 1] if index + 1 < len(sequence) else None
        confirmed = (
            expected is not None
            and row.get("next_day") == expected
            and row.get("next_day_status") == "included"
            and row.get("next_day_pieces") == dict.fromkeys(INDIVIDUAL, True)
            and (model, expected, symbol) not in unique
        )
        recovery.append(
            {
                "model": model,
                "day": day,
                "symbol": symbol,
                "expected_next_baseline_trading_day": expected,
                "exported_next_day": row.get("next_day"),
                "exported_next_day_status": row.get("next_day_status"),
                "exported_next_day_pieces": row.get("next_day_pieces"),
                "next_day_recovery_confirmed_from_export": confirmed,
                "used_for_runtime_gate": False,
            }
        )
    return {
        "envelopes": envelopes,
        "daily": daily,
        "monthly": monthly,
        "attribution": attribution,
        "unknown": [row for row in attribution if row["reason"] == "unknown_reason"],
        "next_day_audit": recovery,
    }


def build_files(source: Path, output: Path) -> dict[str, str]:
    """只读冻结导出及验收哈希；结果写新目录，不连接任何数据库。"""
    source_evidence = json.loads((source / "source-evidence.json").read_text())
    for name in ("daily-ledger.json", "missing-observations.json"):
        if file_hash(source / name) != source_evidence["files"][name]:
            raise ValueError("Frozen baseline source hash differs")
    if (
        file_hash(Path(source_evidence["full_acceptance_path"]))
        != source_evidence["full_acceptance_sha256"]
    ):
        raise ValueError("Full replay acceptance hash differs")
    ledger = json.loads((source / "daily-ledger.json").read_text())
    missing = json.loads((source / "missing-observations.json").read_text())
    if (
        len(ledger) != source_evidence["model_days"]
        or len(missing) != source_evidence["missing_security_days_by_model"]
    ):
        raise ValueError("Baseline export row counts differ")
    derived = derive_baseline(ledger, missing)
    if (
        len({(row["day"], symbol_of(row)) for row in missing})
        != source_evidence["unique_missing_security_days"]
    ):
        raise ValueError("Baseline unique missing securities differ")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "baseline.json": {
            "schema_version": 1,
            "formula": "min(max_missing_count,ceil(candidate*max_missing_fraction))",
            "models": derived["envelopes"],
            "unknown_reason_is_rejection_threshold": False,
            "next_day_recovery_used_for_runtime_gate": False,
            "p95_p99_are_descriptive_only": True,
            "rounding": "exact_integer_ceiling",
        },
        "daily.json": derived["daily"],
        "monthly.json": derived["monthly"],
        "attribution.json": derived["attribution"],
        "unknown.json": derived["unknown"],
        "next-day-audit.json": derived["next_day_audit"],
    }
    hashes = {}
    for name, value in artifacts.items():
        path = output / name
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Existing baseline artifact differs")
        path.write_bytes(data)
        hashes[name] = file_hash(path)
    evidence = {
        "source": source_evidence,
        "source_evidence_sha256": file_hash(source / "source-evidence.json"),
        "builder_sha256": file_hash(Path(__file__)),
        "artifacts": hashes,
        "scope": "offline coverage evidence only; no source/alias/universe changes",
        "publication_authorized": False,
    }
    path = output / "evidence.json"
    data = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2).encode()
    if path.exists() and path.read_bytes() != data:
        raise ValueError("Existing evidence artifact differs")
    path.write_bytes(data)
    return {**hashes, "evidence.json": file_hash(path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_files(args.source, args.output), sort_keys=True))
