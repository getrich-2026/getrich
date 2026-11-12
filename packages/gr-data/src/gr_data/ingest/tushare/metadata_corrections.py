"""复用已验收的封闭日期订正审计，阻止供应商旧快照回退主数据。"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from gr_data.common.parquet import write_parquet
from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestGateError


logger = logging.getLogger(__name__)
_REGISTRY = Path(__file__).with_name("evidence") / "verified_metadata_dates.v1.json"
_REGISTRY_SHA256 = "8cfb9ab2af3f7bc5c712b34eb69fe494aeb37d591822a394e01fdd20e004f2d7"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, Any]]:
    payload = _REGISTRY.read_bytes()
    if hashlib.sha256(payload).hexdigest() != _REGISTRY_SHA256:
        raise IngestGateError("Verified metadata date registry hash mismatch")
    data = json.loads(payload)
    records = data["records"]
    if data["version"] != 1 or len(records) != 14:
        raise IngestGateError("Invalid verified metadata date registry")
    result = {record["symbol"]: record for record in records}
    if len(result) != len(records) or sum(len(r["target_fields"]) for r in records) != 16:
        raise IngestGateError("Duplicate or incomplete verified metadata date registry")
    return result


def _source_date(value: object) -> str | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdecimal():
        raise ValueError("Expected source YYYYMMDD date")
    return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()


def _preserve_conflict(
    paths: RawPaths, raw: pd.DataFrame, asset: str, issues: list[dict[str, object]]
) -> Path:
    """失败证据独立于数据库事务，原始 raw 文件不变。"""
    observed = datetime.now(timezone.utc)
    folder = (
        paths.dataset_dir("tushare", "validation")
        / "metadata_corrections"
        / (observed.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex)
    )
    folder.mkdir(parents=True, exist_ok=False)
    codes = {str(issue["symbol"]) for issue in issues}
    rows = raw.loc[raw["ts_code"].isin(codes)].copy()
    parquet = folder / "source_rows.parquet"
    write_parquet(rows, parquet)
    receipt = {
        "provider": "tushare",
        "dataset": "instruments",
        "asset": asset,
        "observed_at": observed.isoformat(),
        "evidence_kind": "ingest_input_conflict_not_new_supplier_request",
        "registry_sha256": _REGISTRY_SHA256,
        "rows": len(rows),
        "source_rows_sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
        "issues": issues,
        "formal_writes_permitted": False,
    }
    path = folder / "receipt.json"
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str))
    os.replace(temporary, path)
    return path


def protect_metadata_dates(
    conn: psycopg.Connection, paths: RawPaths, raw: pd.DataFrame, asset: str
) -> pd.DataFrame:
    """仅在派生视图采用已核实日期，旧值回退与新冲突严格区分。

    Args:
        conn: 当前 importer 连接；本函数只读，不提交或回滚。
        paths: 当前输入的 RawPaths；冲突完整行在 validation 下原子留证。
        raw: 仍保留供应商 YYYYMMDD 日期的主数据，不就地修改。
        asset: 仅 future 或 option，其他资产保持原行为。

    Returns:
        原 DataFrame 或仅把封闭记录 delist_date 换成核实日期的副本。

    Raises:
        IngestGateError: 审计缺失、被修改、身份不符或供应商返回新冲突；写库前停止。
    """
    if asset not in {"future", "option"} or raw.empty:
        return raw
    registry = _registry()
    selected = {
        code: registry[code]
        for code in raw["ts_code"]
        if code in registry and registry[code]["asset"] == asset
    }
    if not selected:
        return raw
    codes = sorted(selected)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT rule,detail FROM ops.data_quality_check WHERE rule=ANY(%s) AND (")
            + sql.SQL(" OR ").join(sql.SQL("detail @> %s") for _ in codes)
            + sql.SQL(")"),
            (
                sorted({r["rule"] for r in selected.values()}),
                *(Jsonb({"symbol": code}) for code in codes),
            ),
        )
        audits = cur.fetchall()
        cur.execute(
            "SELECT m.source_symbol,i.instrument_id,i.asset,i.exchange,i.list_date,"
            "i.delist_date,o.last_trade_date,o.maturity_date,i.symbol "
            "FROM meta.symbol_map m JOIN meta.instruments i USING(instrument_id) "
            "LEFT JOIN meta.option_contracts o USING(instrument_id) "
            "WHERE m.source='tushare' AND m.source_symbol=ANY(%s)",
            (codes,),
        )
        identities = cur.fetchall()
    issues: list[dict[str, object]] = []
    replacements: dict[str, str] = {}
    for code, expected in selected.items():
        problem: str | None = None
        matching = [(rule, detail) for rule, detail in audits if detail.get("symbol") == code]
        current = [row for row in identities if row[0] == code]
        source = raw.loc[raw["ts_code"].eq(code)]
        if len(matching) != 1:
            problem = "missing_or_duplicate_verified_audit"
        elif (
            matching[0][0] != expected["rule"]
            or _digest(matching[0][1]) != expected["audit_detail_sha256"]
            or matching[0][1].get("plan_sha256") != expected["plan_sha256"]
        ):
            problem = "verified_audit_changed"
        elif len(current) != 1 or len(source) != 1:
            problem = "missing_or_ambiguous_identity"
        elif (
            current[0][1] != matching[0][1]["instrument_id"]
            or current[0][8] != code
            or current[0][2:4] != (asset, expected["exchange"])
            or str(current[0][4]) != expected["list_date"]
            or str(current[0][5]) != expected["verified_date"]
            or (
                asset == "option"
                and (
                    str(current[0][6]) != expected["verified_date"]
                    or str(current[0][7]) != expected["maturity_date"]
                )
            )
        ):
            problem = "stored_verified_identity_or_date_changed"
        else:
            try:
                row = source.iloc[0]
                value = _source_date(row["delist_date"])
                source_exchange = "SZSE" if expected["exchange"] == "XSHE" else expected["exchange"]
                if row["exchange"] != source_exchange:
                    problem = "supplier_exchange_changed"
                elif _source_date(row["list_date"]) != expected["list_date"]:
                    problem = "supplier_lifecycle_identity_changed"
                elif asset == "option" and (
                    _source_date(row["maturity_date"]) != expected["maturity_date"]
                ):
                    problem = "supplier_planned_maturity_changed"
                elif value not in {expected["original_date"], expected["verified_date"]}:
                    problem = "new_supplier_last_trade_date_conflict"
                elif value == expected["original_date"]:
                    replacements[code] = expected["verified_date"].replace("-", "")
            except (KeyError, TypeError, ValueError):
                problem = "invalid_supplier_lifecycle_date"
        if problem is not None:
            issues.append(
                {
                    "symbol": code,
                    "rule": expected["rule"],
                    "failure": problem,
                    "verified_date": expected["verified_date"],
                    "approved_original_date": expected["original_date"],
                    "supplier_values": source.get("delist_date", pd.Series(dtype=object)).tolist(),
                    "plan_sha256": expected["plan_sha256"],
                }
            )
    if issues:
        evidence = _preserve_conflict(paths, raw, asset, issues)
        raise IngestGateError(
            f"Verified metadata correction conflict asset={asset} count={len(issues)} "
            f"samples={[i['symbol'] for i in issues[:5]]} evidence={evidence}"
        )
    if not replacements:
        return raw
    out = raw.copy()
    mask = out["ts_code"].isin(replacements)
    out.loc[mask, "delist_date"] = out.loc[mask, "ts_code"].map(replacements)
    logger.info(
        "Preserved verified metadata dates asset=%s rows=%d symbols=%s registry=%s",
        asset,
        len(replacements),
        sorted(replacements),
        _REGISTRY_SHA256,
    )
    return out
