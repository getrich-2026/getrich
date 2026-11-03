"""将四证据推导的期货休市日和去重审计原子写入现有表。"""

from __future__ import annotations

import calendar
import hashlib
from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from gr_data.common.dates import int_to_date, today_int
from gr_data.common.parquet import read_parquet_strict
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.reference import CalendarImporter
from gr_data.raw.tushare.calendar_rules import (
    FUTURE_CLOSED_DAY_RULE,
    calendar_dates,
    complete_future_calendar,
    future_calendar_start,
)
from gr_data.raw.tushare.context import FUTURE_EXCHANGES


class FutureCalendarImporter(CalendarImporter):
    """仅新增推导休市行，不推断供应商开市日的历史夜盘状态。

    first/last是此次完整自然日校验范围；未指定时使用ctx.months，否则覆盖
    供应商已有日历至今天。源日历已有行不在本次写入集合中，raw从不回写。
    """

    DATASET = "future_calendar"

    def __init__(
        self,
        conn: psycopg.Connection,
        ctx: IngestContext,
        client: Any | None = None,
        *,
        first: date | None = None,
        last: date | None = None,
        exchanges: tuple[str, ...] = FUTURE_EXCHANGES,
    ) -> None:
        super().__init__(conn, ctx, client)
        self.first = first
        self.last = last
        self.exchanges = exchanges
        self.inferred: list[dict[str, Any]] = []

    def build(self) -> pd.DataFrame:
        self.inferred = []
        frames = []
        for exchange in self.exchanges:
            path = self.paths.dataset_file("tushare", "future_calendar", exchange)
            raw = read_parquet_strict(path)
            if raw is None or raw.empty:
                raise ValueError(f"Missing future_calendar[{exchange}]")
            dates = calendar_dates(raw)
            first = self.first or min(dates)
            last = self.last or min(max(dates), int_to_date(today_int()))
            if self.ctx.months:
                first = self.first or date.fromisoformat(min(self.ctx.months) + "-01")
                end = date.fromisoformat(max(self.ctx.months) + "-01")
                last = self.last or end.replace(day=calendar.monthrange(end.year, end.month)[1])
            first = future_calendar_start(self.paths, exchange, first)
            if first > last:
                continue
            completed = complete_future_calendar(self.paths, exchange, first, last, frame=raw)
            self.inferred.extend(completed.inferred)
            if completed.inferred:
                canonical = self._build_one(completed.frame, exchange)
                inferred_days = {date.fromisoformat(item["date"]) for item in completed.inferred}
                frames.append(canonical.loc[canonical["trading_day"].isin(inferred_days)])
        if not frames:
            return pd.DataFrame(columns=list(self.contract.columns))
        return (
            pd.concat(frames, ignore_index=True)
            .sort_values(["exchange", "trading_day"])
            .reset_index(drop=True)
        )

    def _check_quality(self, df: pd.DataFrame) -> list[str]:
        # 所有供应商日历完整时没有修复行，这是已完整校验后的合法no-op。
        return [] if df.empty else super()._check_quality(df)

    def _record_run(self, rows_written: int, warnings: list[str]) -> None:
        """复用BaseImporter事务，日历、审计和运行流水一起提交／回滚。"""
        if self.inferred:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (FUTURE_CLOSED_DAY_RULE,),
                )
                cur.execute(
                    "SELECT detail->>'observation_id' FROM ops.data_quality_check WHERE rule=%s",
                    (FUTURE_CLOSED_DAY_RULE,),
                )
                existing = {row[0] for row in cur.fetchall()}
                pending = []
                for detail in self.inferred:
                    identity = hashlib.sha256(
                        f"{FUTURE_CLOSED_DAY_RULE}:{detail['exchange']}:{detail['date']}".encode()
                    ).hexdigest()
                    if identity not in existing:
                        pending.append(
                            (
                                FUTURE_CLOSED_DAY_RULE,
                                "info",
                                Jsonb({**detail, "observation_id": identity}),
                            )
                        )
                        existing.add(identity)
                if pending:
                    cur.executemany(
                        "INSERT INTO ops.data_quality_check(rule,severity,detail) "
                        "VALUES (%s,%s,%s)",
                        pending,
                    )
        super()._record_run(rows_written, warnings)
