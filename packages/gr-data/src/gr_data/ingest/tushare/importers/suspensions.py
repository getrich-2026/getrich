"""停复牌事件、覆盖与已有行情派生状态的原子刷新。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from gr_data.common import contracts
from gr_data.common.ownership import OwnershipManager
from gr_data.common.trading_status import event_flags, resolve_trading_status
from gr_data.db.copy import upsert_rows
from gr_data.ingest.base import BaseImporter, IngestResult
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.suspensions import read_suspensions


class SuspensionImporter(BaseImporter):
    """按有证据的日期替换事件，保留其他日期；空响应可撤销旧事件。

    所有输入及标的映射必须完整，失败整体回滚。没有覆盖凭据的旧 raw 须重抓。
    单次内存 O(所选月份事件数 + 已有行情行数)，历史回补按月运行。
    """

    PROVIDER = "tushare"
    DATASET = "suspend_d"
    CONTRACT = contracts.STOCK_SUSPEND_EVENT

    def build(self) -> pd.DataFrame:
        months = self.ctx.months
        if months is None:
            adapter = TushareAdapter(self.paths)
            months = tuple(adapter.list_months("suspend_d"))
            # 残留 *.tmp-* 等软告警并入运行结果，与其他 Tushare importer 一致。
            self.soft_warnings.extend(adapter.notices)
        if not months:
            raise ValueError("No suspension partitions selected")
        raw, self.coverage = read_suspensions(self.paths, months, required=True)
        cur = self.conn.execute(
            "SELECT source_symbol, instrument_id FROM meta.symbol_map WHERE source = %s",
            (self.PROVIDER,),
        )
        mapping = dict(cur.fetchall())
        ids = raw["ts_code"].map(mapping)
        if ids.isna().any():
            raise ValueError(f"Unmapped suspension symbols: {int(ids.isna().sum())}")
        result = raw.rename(columns={"ts_code": "source_symbol", "trade_date": "trading_day"})
        result["instrument_id"] = ids.astype("int64")
        result["source"] = self.PROVIDER
        return result[list(self.contract.columns)]

    def run(self) -> IngestResult:
        """事件替换、覆盖、状态刷新及 ETL 流水同一事务提交。"""
        try:
            owner = OwnershipManager(self.conn)
            for target in (self.contract.qualified, contracts.STOCK_SUSPEND_COVERAGE.qualified):
                owner.claim(
                    target, self.PROVIDER, channel=self.ctx.channel, force=self.ctx.force_ownership
                )
            owner.check("market.stock_bar_1d", self.PROVIDER)
            events = self.build()
            days = self.coverage["trading_day"].tolist()
            # 串行化事件替换；在 READ COMMITTED 下后到者仍须检查观察时间。
            self.conn.execute(
                "LOCK TABLE market.stock_suspend_coverage IN SHARE ROW EXCLUSIVE MODE"
            )
            current = dict(
                self.conn.execute(
                    "SELECT trading_day, observed_at FROM market.stock_suspend_coverage "
                    "WHERE source=%s AND trading_day=ANY(%s)",
                    (self.PROVIDER, days),
                ).fetchall()
            )
            if any(
                current.get(row.trading_day, row.observed_at) > row.observed_at
                for row in self.coverage.itertuples()
            ):
                raise ValueError("Older suspension observation cannot replace newer data")
            self.conn.execute(
                "DELETE FROM market.stock_suspend_event WHERE source=%s AND trading_day=ANY(%s)",
                (self.PROVIDER, days),
            )
            rows = self._df_to_rows(events)
            written = upsert_rows(self.conn, self.contract, rows)
            coverage_rows = list(self.coverage.itertuples(index=False, name=None))
            upsert_rows(self.conn, contracts.STOCK_SUSPEND_COVERAGE, coverage_rows)
            self._refresh_bars(events, days)
            warnings = self.collect_soft_warnings()
            self._record_run(written, warnings)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self.log.info("Suspension import completed: events=%d covered_days=%d", written, len(days))
        return IngestResult(self.DATASET, self.contract.qualified, written, warnings)

    def _refresh_bars(self, events: pd.DataFrame, days: list[date]) -> None:
        cur = self.conn.execute(
            "SELECT instrument_id, dt AS trading_day FROM market.stock_bar_1d "
            "WHERE source=%s AND dt=ANY(%s)",
            (self.PROVIDER, days),
        )
        keys = ["instrument_id", "trading_day"]
        bars = pd.DataFrame(cur.fetchall(), columns=keys)
        if bars.empty:
            return
        evidence = bars.merge(event_flags(events, keys), on=keys, how="left")
        evidence["has_bar"] = True
        evidence["covered"] = True
        statuses = resolve_trading_status(evidence.drop(columns=keys))
        self.conn.execute(
            "UPDATE market.stock_bar_1d AS b SET trading_status=v.status "
            "FROM unnest(%s::bigint[], %s::date[], %s::text[]) AS v(id, day, status) "
            "WHERE b.instrument_id=v.id AND b.dt=v.day AND b.source=%s "
            "AND b.trading_status IS DISTINCT FROM v.status",
            (
                bars.instrument_id.tolist(),
                bars.trading_day.tolist(),
                statuses.tolist(),
                self.PROVIDER,
            ),
        )
