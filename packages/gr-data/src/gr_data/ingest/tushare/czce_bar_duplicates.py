"""仅核销 CZCE/20260902 两组已核实的跨代重复行情，不改身份或 raw。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from gr_data.common.paths import RawPaths
from gr_data.raw.czce.options import digest


RULE = "tushare_czce_sr707_duplicate_20260902_v1"
NOTICE = "CZCE duplicate bar cancellation "
DAY = "20260902"
PAIRS = (("SR707C6000.ZCE", "SR2707C6000.ZCE"), ("SR707P6000.ZCE", "SR2707P6000.ZCE"))
OFFICIAL_SHA256 = "2a7620ba9eb82717ddfe2951483ac17f89204acb54815d5d0fd3030150a81bb3"
# 随源码固定的证据登记；临时调查目录不进入运行依赖。
MANIFEST_SHA256 = "3bc31467ea76eb999f43f4cc91ac9f14b3d32a58bd8d3517df22fb1becd6d516"


def load_evidence(paths: RawPaths) -> dict[str, Any]:
    """核对永久归档清单及每份官方原件，任何缺失或变化都失败。"""
    root = paths.dataset_dir("czce", "option_bar_duplicates_v1")
    if digest(root / "manifest.json") != MANIFEST_SHA256:
        raise ValueError("Changed CZCE duplicate bar evidence manifest")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("rule") != RULE:
        raise ValueError("Invalid CZCE duplicate bar evidence rule")
    for item in manifest["files"]:
        p = root / item["path"]
        if not p.resolve().is_relative_to(root.resolve()) or digest(p) != item["sha256"]:
            raise ValueError("Changed CZCE duplicate bar official evidence")
    if digest(root / "20260902.txt") != OFFICIAL_SHA256:
        raise ValueError("CZCE duplicate bar official SHA mismatch")
    return {"sha256": OFFICIAL_SHA256, "manifest_sha256": MANIFEST_SHA256}


def reconcile(
    raw: pd.DataFrame, metadata: pd.DataFrame, *, evidence: dict[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """只在精确交易所日排除旧行；全部原始字段严格相等且两代身份可证。

    Args:
        raw: 保留供应商字段、值及缺失的行情，不修改输入。
        metadata: 按源代码唯一的权威主数据，须含生命周期和交易所 symbol。
        evidence: 调用方已校验的官方证据哈希。

    Returns:
        派生行情及逐代码对核销明细。没有旧行时不核销。

    Raises:
        ValueError: 缺新行、多行、字段冲突、身份或生命周期不成立。
    """
    scoped = raw["exchange"].eq("CZCE") & raw["trade_date"].astype(str).eq(DAY)
    drop = pd.Series(False, index=raw.index)
    reports = []
    for old, new in PAIRS:
        old_mask = scoped & raw.ts_code.eq(old)
        new_mask = scoped & raw.ts_code.eq(new)
        if not old_mask.any():
            continue
        if int(old_mask.sum()) != 1 or int(new_mask.sum()) != 1:
            raise ValueError(f"CZCE duplicate bar cardinality old={old} new={new}")
        left = raw.loc[old_mask].drop(columns="ts_code").reset_index(drop=True)
        right = raw.loc[new_mask].drop(columns="ts_code").reset_index(drop=True)
        if not (left.eq(right).fillna(False) | (left.isna() & right.isna())).all().all():
            raise ValueError(f"CZCE duplicate bar field mismatch old={old} new={new}")
        identities = []
        for code in (old, new):
            rows = metadata.loc[metadata.ts_code.eq(code)]
            if len(rows) != 1:
                raise ValueError(f"CZCE duplicate bar ambiguous identity code={code}")
            identities.append(rows.iloc[0])
        before, after = identities
        for field in ("symbol", "exchange", "call_put", "exercise_price"):
            if pd.isna(before[field]) or pd.isna(after[field]) or before[field] != after[field]:
                raise ValueError(f"CZCE duplicate bar identity mismatch field={field}")
        cp = "C" if old == "SR707C6000.ZCE" else "P"
        if (
            before["exchange"] != "CZCE"
            or before["symbol"] != f"SR707{cp}6000"
            or before["call_put"] != cp
            or before["exercise_price"] != 6000
        ):
            raise ValueError("CZCE duplicate bar unexpected identity")
        if before["opt_code"] != "OPSR1707.ZCE" or after["opt_code"] != "OPSR2707.ZCE":
            raise ValueError("CZCE duplicate bar underlying mismatch")
        dates = [str(row[field]) for row in identities for field in ("list_date", "delist_date")]
        if dates != ["20170428", "20170523", "20260902", "20270611"]:
            raise ValueError("CZCE duplicate bar lifecycle mismatch")
        drop |= old_mask
        reports.append(
            {
                "rule": RULE,
                "exchange": "CZCE",
                "trade_date": DAY,
                "old_code": old,
                "kept_code": new,
                "rows": 1,
                "evidence": evidence,
            }
        )
    return raw.loc[~drop].copy() if reports else raw, reports


def apply(
    raw: pd.DataFrame, metadata: pd.DataFrame, paths: RawPaths
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """在受错误身份影响的校验之前调用；无触发旧行则保持原视图。"""
    target = (
        raw.exchange.eq("CZCE")
        & raw.trade_date.astype(str).eq(DAY)
        & raw.ts_code.isin([p[0] for p in PAIRS])
    )
    if not target.any():
        return raw, []
    return reconcile(raw, metadata, evidence=load_evidence(paths))


def record_audit(conn: psycopg.Connection, reports: list[dict[str, Any]], target: str) -> None:
    """同行情共享当前事务，持规则锁并按完整内容去重，不提交或回滚。"""
    if not reports:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (RULE,))
        for report in reports:
            detail = {**report, "month": "2026-09", "target": target}
            identity = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
            cur.execute(
                "SELECT 1 FROM ops.data_quality_check WHERE rule=%s "
                "AND detail->>'observation_id'=%s",
                (RULE, identity),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES(%s,%s,%s)",
                    (RULE, "info", Jsonb({**detail, "observation_id": identity})),
                )


def verify_accounting(
    raw: pd.DataFrame, effective: pd.DataFrame, reports: list[dict[str, Any]]
) -> None:
    """独立验收精确行差：每一行差都须有批准代码对及证据，其他字段逐值不变。"""
    removed = pd.Series(False, index=raw.index)
    seen = set()
    for report in reports:
        pair = (report["old_code"], report["kept_code"])
        if (
            pair not in PAIRS
            or pair in seen
            or report["rule"] != RULE
            or report["rows"] != 1
            or type(report["rows"]) is not int
            or report["exchange"] != "CZCE"
            or report["trade_date"] != DAY
            or report["evidence"] != {"sha256": OFFICIAL_SHA256, "manifest_sha256": MANIFEST_SHA256}
        ):
            raise ValueError("Unexplained CZCE duplicate bar accounting")
        seen.add(pair)
        match = (
            raw.exchange.eq("CZCE") & raw.trade_date.astype(str).eq(DAY) & raw.ts_code.eq(pair[0])
        )
        if int(match.sum()) != 1:
            raise ValueError("CZCE duplicate bar accounting cardinality")
        kept = (
            raw.exchange.eq("CZCE") & raw.trade_date.astype(str).eq(DAY) & raw.ts_code.eq(pair[1])
        )
        if int(kept.sum()) != 1:
            raise ValueError("CZCE duplicate bar accounting kept cardinality")
        before = raw.loc[match].drop(columns="ts_code").reset_index(drop=True)
        after = raw.loc[kept].drop(columns="ts_code").reset_index(drop=True)
        if not (before.eq(after).fillna(False) | (before.isna() & after.isna())).all().all():
            raise ValueError("CZCE duplicate bar accounting field mismatch")
        removed |= match
    if len(raw) - len(effective) != len(reports):
        raise ValueError("Unexplained CZCE duplicate bar row difference")
    pd.testing.assert_frame_equal(
        raw.loc[~removed].reset_index(drop=True), effective.reset_index(drop=True), check_exact=True
    )


def parse_notice(value: str) -> dict[str, Any] | None:
    """恢复候选队列只认可精确代码对、日期、计数及批准证据的核销明细。"""
    if not value.startswith(NOTICE):
        return None
    try:
        report = json.loads(value[len(NOTICE) :])
        for old, new in PAIRS:
            expected = {
                "rule": RULE,
                "exchange": "CZCE",
                "trade_date": DAY,
                "old_code": old,
                "kept_code": new,
                "rows": 1,
                "evidence": {"sha256": OFFICIAL_SHA256, "manifest_sha256": MANIFEST_SHA256},
            }
            if report == expected and type(report["rows"]) is int:
                return report
    except (ValueError, TypeError, KeyError):
        return None
    return None
