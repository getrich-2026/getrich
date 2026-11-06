"""把封闭的郑商所主数据补充接入 Tushare ingest；不改归属或事务边界。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from gr_data.common.paths import RawPaths
from gr_data.raw.czce.metadata import DATASET, RULE, MetadataSupplement, approved_codes
from gr_data.raw.tushare.asset_rules import read_asset_observation


def merge_metadata(paths: RawPaths, raw: pd.DataFrame) -> pd.DataFrame:
    """只在内存合并补充身份；恢复的 Tushare 行经严格比对后优先使用。"""
    if (
        not (paths.dataset_dir("czce", DATASET) / "manifest.json").exists()
        and not set(raw["ts_code"]) & approved_codes()
    ):
        return raw
    return MetadataSupplement(paths).merge(raw)


def monthly_reports(paths: RawPaths, raw: pd.DataFrame, month: str) -> list[dict[str, Any]]:
    """按本月实际行情计算补齐代码数，不能把清单全集计作本月使用。"""
    if not set(raw["ts_code"]) & approved_codes():
        return []
    metadata, _ = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    if metadata is None:
        raise ValueError("Missing Tushare metadata for CZCE supplemental audit")
    supplement = MetadataSupplement(paths)
    supplement.compare_tushare(metadata)
    return supplement.reports(raw, metadata, month)


def record_audit(conn: psycopg.Connection, reports: list[dict[str, Any]], target: str) -> None:
    """沿当前连接写审计，和行情共享事务；按内容去重，不提交或回滚。"""
    if not reports:
        return
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (RULE,))
        for report in reports:
            value = {**report, "target": target}
            identity = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            cur.execute(
                "SELECT 1 FROM ops.data_quality_check WHERE rule=%s "
                "AND detail->>'observation_id'=%s",
                (RULE, identity),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES(%s,%s,%s)",
                    (RULE, "info", Jsonb({**value, "observation_id": identity})),
                )
