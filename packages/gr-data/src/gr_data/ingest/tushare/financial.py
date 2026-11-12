"""年度加权平均ROE；源百分数仅在此转换一次为小数。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl


if TYPE_CHECKING:
    from gr_data.db import DictConnection


def normalize_annual_roe(
    raw: pl.DataFrame, *, symbol_ids: Mapping[str, int], as_of: date, observed_at: datetime
) -> pl.DataFrame:
    """保留当日已公告的完整年度记录及修订；零和负值不是缺失。

    缺失公告日不推算，缺失ROE为NULL；同一主键冲突仅允许明确的update_flag=1修订。
    available_at是本次实际观察时间，不冒充历史当时可得。
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Financial observation timestamp must be timezone aware")
    required = {"ts_code", "end_date", "ann_date", "roe_waa"}
    if not required <= set(raw.columns):
        raise ValueError("Annual ROE source fields are incomplete")
    rows: dict[tuple[int, date, date], tuple[dict, str]] = {}
    for item in raw.filter(pl.col("ts_code").is_in(list(symbol_ids))).iter_rows(named=True):
        if not item["ann_date"] or not item["end_date"]:
            continue
        end = datetime.strptime(str(item["end_date"]), "%Y%m%d").date()
        ann = datetime.strptime(str(item["ann_date"]), "%Y%m%d").date()
        if (end.month, end.day) != (12, 31) or end > as_of or ann > as_of:
            continue
        if ann < end:
            raise ValueError("Annual financial announcement precedes reporting period end")
        value = Decimal(str(item["roe_waa"])) if item["roe_waa"] is not None else None
        if value is not None and value.is_nan():
            value = None
        if value is not None and not value.is_finite():
            raise ValueError("Annual ROE source is non-finite")
        flag = str(item.get("update_flag") or "0")
        row = {
            "instrument_id": symbol_ids[item["ts_code"]],
            "end_date": end,
            "ann_date": ann,
            "roe": value / 100 if value is not None else None,
            "source": "tushare",
            "source_revision": flag,
            "available_at": observed_at,
        }
        key = (row["instrument_id"], end, ann)
        old = rows.get(key)
        if old is not None and old[0]["roe"] != row["roe"]:
            if flag == old[1] or "1" not in (flag, old[1]):
                raise ValueError("Conflicting annual ROE source revisions")
            if old[1] == "1":
                continue
        if old is not None and old[1] == "1" and flag != "1":
            continue
        rows[key] = (row, flag)
    schema = {
        "instrument_id": pl.Int64,
        "end_date": pl.Date,
        "ann_date": pl.Date,
        "roe": pl.Decimal(precision=12, scale=6),
        "source": pl.String,
        "source_revision": pl.String,
        "available_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
    return pl.DataFrame([r[0] for r in rows.values()], schema=schema).sort(
        "instrument_id", "end_date", "ann_date"
    )


async def write_annual_roe(
    conn: DictConnection, frame: pl.DataFrame, *, expected_owner: str | None
) -> None:
    """在发布事务中写年度指标；所有权CAS通过后写入，不自行提交。"""
    from psycopg.pq import TransactionStatus

    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("Annual financial write requires an outer publication transaction")
    await conn.execute("SELECT pg_advisory_xact_lock(7342061105)")
    row = await (
        await conn.execute(
            "SELECT provider FROM ops.table_ownership "
            "WHERE target='fundamental.indicator_q' FOR UPDATE"
        )
    ).fetchone()
    current = row["provider"] if row else None
    if current != expected_owner or current not in (None, "tushare"):
        raise ValueError("Annual financial table ownership differs from preflight")
    if current is None:
        await conn.execute(
            "INSERT INTO ops.table_ownership(target,provider,channel) "
            "VALUES ('fundamental.indicator_q','tushare','ingest')"
        )
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO fundamental.indicator_q "
            "(instrument_id,end_date,ann_date,roe,source,source_revision,available_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(instrument_id,end_date,ann_date) "
            "DO UPDATE SET roe=EXCLUDED.roe,source=EXCLUDED.source,"
            "source_revision=EXCLUDED.source_revision,available_at=EXCLUDED.available_at,"
            "updated_at=now() WHERE "
            "ROW(indicator_q.roe,indicator_q.source,indicator_q.source_revision) IS DISTINCT FROM "
            "ROW(EXCLUDED.roe,EXCLUDED.source,EXCLUDED.source_revision)",
            frame.select(
                "instrument_id",
                "end_date",
                "ann_date",
                "roe",
                "source",
                "source_revision",
                "available_at",
            ).iter_rows(),
        )
