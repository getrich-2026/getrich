"""D-026：按已审核、固定哈希的 ETF 身份事件登记划定当前产品历史。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from urllib.parse import urlsplit

import pandas as pd

from gr_data.ingest.base import IngestGateError
from gr_data.ingest.tushare.importers.reference import parse_date
from gr_data.raw.tushare.asset_rules import source_dates


ETF_IDENTITY_REGISTRY_FILE = "etf_identity_events.v1.json"
ETF_IDENTITY_REGISTRY_SHA256 = "e75ffbef721361f112744afe30da44895774cb9575a62264839dd166ec95fed6"
ETF_TRANSITION_RULE = "tushare_etf_pre_transition_out_of_scope"
ETF_TRANSITION_NOTICE = "ETF pre-transition out of scope "


@dataclass(frozen=True)
class EtfIdentityEvidence:
    """归档公告的URL与原件SHA；审核对照原件，入库时不联网。"""

    url: str
    sha256: str


@dataclass(frozen=True)
class EtfIdentityEvent:
    """同代码转型边界；首次上市日只留证，不改写主数据日期。"""

    event_id: str
    ts_code: str
    first_listing_date: date
    effective_date: date
    previous_target: str
    new_target: str
    evidence: tuple[EtfIdentityEvidence, ...]


@dataclass(frozen=True)
class EtfIdentityRegistry:
    """一次运行固定使用的登记版本与文件哈希。"""

    version: str
    sha256: str
    events: tuple[EtfIdentityEvent, ...]


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestGateError("Invalid ETF identity registry text")
    return value


def _date(value: object) -> date:
    text = _text(value)
    try:
        result = date.fromisoformat(text)
    except ValueError as exc:
        raise IngestGateError("Invalid ETF identity registry date") from exc
    if result.isoformat() != text:
        raise IngestGateError("ETF identity registry date must use YYYY-MM-DD")
    return result


def parse_etf_identity_registry(payload: bytes, expected_sha256: str) -> EtfIdentityRegistry:
    """先验证文件哈希，再验证唯一身份与证据字段，异常在写库前拒绝。

    expected_sha256来自已审核源码，不从登记本身读取；证据SHA在审核时
    对照归档原件，登记文件的固定哈希保护它们不可静默变更。
    """
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise IngestGateError("ETF identity registry SHA256 mismatch")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise IngestGateError("Invalid ETF identity registry JSON") from exc
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("status") != "approved"
        or not isinstance(data.get("events"), list)
        or not data["events"]
    ):
        raise IngestGateError("Invalid ETF identity registry envelope")
    version = _text(data.get("registry_version"))
    events: list[EtfIdentityEvent] = []
    codes: set[str] = set()
    identities: set[str] = set()
    for item in data["events"]:
        if not isinstance(item, dict) or item.get("event_type") != "transformation":
            raise IngestGateError("Unsupported ETF identity event type")
        code = _text(item.get("ts_code"))
        event_id = _text(item.get("event_id"))
        if code in codes or event_id in identities:
            raise IngestGateError("Duplicate ETF identity registry event")
        if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", code):
            raise IngestGateError("Invalid ETF identity registry code")
        first = _date(item.get("official_first_listing_date"))
        effective = _date(item.get("effective_date"))
        if first > effective or event_id != f"{code}:transformation:{effective}":
            raise IngestGateError("Invalid ETF identity event boundary")
        evidence_rows = item.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise IngestGateError("Missing ETF identity event evidence")
        evidence: list[EtfIdentityEvidence] = []
        for row in evidence_rows:
            if not isinstance(row, dict):
                raise IngestGateError("Invalid ETF identity event evidence")
            url = _text(row.get("url"))
            parts = urlsplit(url)
            digest_text = _text(row.get("sha256"))
            if (
                parts.scheme not in {"http", "https"}
                or not parts.netloc
                or parts.username is not None
                or not re.fullmatch(r"[0-9a-f]{64}", digest_text)
            ):
                raise IngestGateError("Invalid ETF identity evidence URL or SHA256")
            evidence.append(EtfIdentityEvidence(url, digest_text))
        events.append(
            EtfIdentityEvent(
                event_id,
                code,
                first,
                effective,
                _text(item.get("previous_target")),
                _text(item.get("new_target")),
                tuple(evidence),
            )
        )
        codes.add(code)
        identities.add(event_id)
    return EtfIdentityRegistry(version, digest, tuple(events))


def load_etf_identity_registry() -> EtfIdentityRegistry:
    """读取随包发布的固定v1登记；缺文件、篡改或无效事件均拒绝。"""
    resource = files("gr_data.ingest.tushare").joinpath("evidence", ETF_IDENTITY_REGISTRY_FILE)
    try:
        payload = resource.read_bytes()
    except OSError as exc:
        raise IngestGateError("Cannot read ETF identity registry") from exc
    return parse_etf_identity_registry(payload, ETF_IDENTITY_REGISTRY_SHA256)


def validate_etf_identity_metadata(metadata: pd.DataFrame, registry: EtfIdentityRegistry) -> None:
    """登记代码出现在主数据时，list_date必须等于获批的新合同生效日。"""
    for event in registry.events:
        rows = metadata.loc[metadata["ts_code"].eq(event.ts_code), "list_date"]
        if not rows.empty and not rows.map(parse_date).eq(event.effective_date).all():
            raise IngestGateError(f"ETF identity registry list_date mismatch code={event.ts_code}")


def exclude_etf_pre_transition(
    frame: pd.DataFrame,
    dataset: str,
    *,
    metadata: pd.DataFrame | None = None,
    registry: EtfIdentityRegistry | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """按登记排除生效日前源交易日，返回副本及逐代码／数据集审计明细。

    生效日当天保留；raw、主数据日期和指数不改。更名／换管理人和未登记
    代码不自动豁免，仍走原上市日期门禁。复杂度O(事件数×行数)。
    """
    if dataset not in {"fund_daily", "fund_adj"}:
        raise IngestGateError("Unsupported ETF transition dataset")
    if metadata is None:
        raise IngestGateError("ETF identity registry requires metadata")
    registry = registry or load_etf_identity_registry()
    validate_etf_identity_metadata(metadata, registry)
    days = source_dates(frame["trade_date"])
    excluded = pd.Series(False, index=frame.index)
    details: list[dict[str, object]] = []
    for event in registry.events:
        mask = frame["ts_code"].eq(event.ts_code) & days.lt(event.effective_date)
        if not mask.any():
            continue
        excluded |= mask
        selected = days.loc[mask]
        details.append(
            {
                "rule": ETF_TRANSITION_RULE,
                "reason": "基金转型前，不在范围内",
                "ts_code": event.ts_code,
                "dataset": dataset,
                "start_date": str(selected.min()),
                "end_date": str(selected.max()),
                "rows": int(mask.sum()),
                "current_product_start": str(event.effective_date),
                "event_id": event.event_id,
                "registry_version": registry.version,
                "registry_sha256": registry.sha256,
                "evidence": [item.url for item in event.evidence],
                "evidence_sha256": [item.sha256 for item in event.evidence],
            }
        )
    return frame.loc[~excluded].reset_index(drop=True), details
