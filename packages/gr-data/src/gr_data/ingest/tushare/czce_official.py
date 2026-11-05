"""连接 Tushare 交易所回执、日历与郑商所官方覆盖；审计沿用调用方事务。"""

from __future__ import annotations

import calendar
import hashlib
import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd
import polars as pl
import psycopg
from psycopg.types.json import Jsonb

from gr_data.common.paths import RawPaths
from gr_data.ingest.base import IngestGateError
from gr_data.raw.czce.options import (
    FIRST,
    NOTICE,
    RULE,
    OfficialOptionHistory,
    atomic_parquet,
    digest,
)
from gr_data.raw.tushare.asset_rules import source_dates
from gr_data.raw.tushare.calendar_rules import complete_future_calendar
from gr_data.raw.tushare.fetchers.reference import read_open_days


FIRST_DAY = date.fromisoformat(FIRST)


def reconcile_czce_official(
    raw: pd.DataFrame,
    month: str | None,
    receipt_scope: dict[str, Any],
    paths: RawPaths,
    manifest_sha256: str,
    *,
    soft_notice: Callable[[str], None] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], pl.DataFrame]:
    """按 CZCE 自身回执范围核对日历，再返回源单位覆盖副本及审计证据。

    月份是 YYYY-MM，缺省时沿用原 raw 首日所在月份。上市前月份不要求
    CZCE 范围；此后范围缺失或 pending 立即失败。可选回调保留 importer
    原有软告警收集与输出顺序，不在此处配置日志或改动原始 DataFrame。
    """
    history = OfficialOptionHistory(paths, manifest_sha256)
    first = (
        date.fromisoformat(month + "-01")
        if month
        else source_dates(raw.trade_date).min().replace(day=1)
    )
    month_end = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    selected = raw.loc[raw.exchange.eq("CZCE")]
    expected = None
    if month_end >= FIRST_DAY:
        scope = receipt_scope.get("exchange_scopes", {}).get("CZCE")
        if not isinstance(scope, dict) or not {"start", "end"} <= scope.keys():
            raise IngestGateError("Missing CZCE exchange scope in option receipt")
        start, end = (date.fromisoformat(scope[k]) for k in ("start", "end"))
        if not first <= start <= end <= month_end or start < FIRST_DAY:
            raise IngestGateError("Invalid CZCE exchange scope in option receipt")
        if scope.get("pending_days"):
            raise IngestGateError("Pending CZCE option trading days")
        cal = complete_future_calendar(paths, "CZCE", start, end).frame
        expected = {d.strftime("%Y%m%d") for d in read_open_days(cal, "CZCE") if start <= d <= end}
        if expected and selected.empty:
            raise IngestGateError("Missing CZCE option trading days")
    out, reports, diffs = history.reconcile(raw, expected)
    if soft_notice is not None:
        for detail in reports:
            soft_notice(NOTICE + json.dumps(detail, ensure_ascii=False, sort_keys=True))
    return out, reports, diffs


def record_czce_official_audit(
    conn: psycopg.Connection,
    paths: RawPaths,
    manifest_sha256: str,
    reports: list[dict[str, Any]],
    diffs: pl.DataFrame | None,
    target: str,
) -> None:
    """记录交易所日审计及按年差异，使用当前连接，不提交或回滚。

    与原实现持有同一 RULE advisory xact lock；由 BaseImporter 在业务
    写入、审计和 ETL 记录全部完成后提交。差异文件只证明输入观察，PG
    同事务审计才证明业务提交。重复导入仍按 observation_id 去重。
    """
    history = OfficialOptionHistory(paths, manifest_sha256)
    diff_info = {}
    if diffs is not None and not diffs.is_empty():
        for key, part in (
            diffs.with_columns(pl.col("trade_date").str.slice(0, 4).alias("_year"))
            .partition_by("_year", as_dict=True)
            .items()
        ):
            part = part.drop("_year")
            # 文件是输入观察证据；是否提交以同事务的PG审计为准。
            identity = hashlib.sha256(part.write_json().encode()).hexdigest()
            path = history.root / "differences" / str(key[0]) / (identity + ".parquet")
            if not path.exists():
                atomic_parquet(path, part)
            diff_info[str(key[0])] = {
                "path": str(path.relative_to(history.root)),
                "sha256": digest(path),
                "rows": part.height,
            }
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (RULE,))
        for detail in reports:
            value = {
                **detail,
                "difference_evidence": diff_info.get(detail["trade_date"][:4]),
                "target": target,
            }
            identity = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            cur.execute(
                "SELECT 1 FROM ops.data_quality_check WHERE rule=%s "
                "AND detail->>'observation_id'=%s",
                (RULE, identity),
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES(%s,%s,%s)",
                    (
                        RULE,
                        "info",
                        Jsonb({**value, "observation_id": identity}),
                    ),
                )
