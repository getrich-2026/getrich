from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine

from getrich_data_import.adapters.base import HistoryDataSource
from getrich_data_import.common.config import Settings
from getrich_data_import.common.logger import get_logger
from getrich_data_import.db.postgres import max_value, qident
from getrich_data_import.extract import BarsExtractionPlan
from getrich_data_import.load.postgres import (
    attach_instrument_ids,
    finish_job_run,
    insert_job_run,
    upsert_dataframe,
)
from getrich_data_import.quality.rules import QualityIssue, has_error, validate_bars, write_quality_issues
from getrich_data_import.transform.bars import to_market_frame


logger = get_logger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    job_name: str
    rows_written: int
    status: str


class ImportPipeline:
    def __init__(self, *, settings: Settings, engine: Engine, source: HistoryDataSource) -> None:
        self.settings = settings
        self.engine = engine
        self.source = source
        self.source_name = str(getattr(source, "provider", source.name))

    def load_metadata(self) -> PipelineResult:
        job_name = "load_metadata"
        rows = 0
        with self.engine.begin() as conn:
            run_id = insert_job_run(conn, job_name=job_name)
        logger.info("job started", extra={"job_name": job_name, "run_id": run_id, "provider": self.source_name})
        try:
            with self.engine.begin() as conn:
                for frame in self.source.calendar_frames():
                    written = upsert_dataframe(
                        conn,
                        frame,
                        schema="meta",
                        table="trading_calendar",
                        primary_keys=("exchange", "trading_day"),
                        batch_rows=self.settings.batch_rows,
                    )
                    rows += written
                    logger.info(
                        "loaded calendar batch",
                        extra={"job_name": job_name, "run_id": run_id, "rows_written": written},
                    )
                instruments = self.source.instrument_frame()
                rows += upsert_dataframe(
                    conn,
                    instruments,
                    schema="meta",
                    table="instruments",
                    primary_keys=("asset", "exchange", "symbol"),
                    batch_rows=self.settings.batch_rows,
                )
                rows += self._upsert_symbol_map(conn)
                rows += self._upsert_future_contracts(conn)
                rows += self._upsert_option_contracts(conn)
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info("job finished", extra={"job_name": job_name, "run_id": run_id, "rows_written": rows})
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="failed", rows_written=rows, error=str(exc))
            logger.exception("job failed", extra={"job_name": job_name, "run_id": run_id, "rows_written": rows})
            raise
        return PipelineResult(job_name, rows, "success")

    def import_bars(
        self,
        *,
        asset: str,
        freq: str,
        mode: str = "auto",
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> PipelineResult:
        plan = BarsExtractionPlan.from_import_bars_args(
            asset=asset,
            freq=freq,
            mode=mode,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        table = plan.table_name
        job_name = plan.job_name
        rows = 0
        with self.engine.begin() as conn:
            run_id = insert_job_run(
                conn,
                job_name=job_name,
                asset=plan.request.asset,
                freq=plan.request.freq,
            )
        logger.info(
            "job started",
            extra={
                "job_name": job_name,
                "run_id": run_id,
                "provider": self.source_name,
                "asset": plan.request.asset,
                "freq": plan.request.freq,
            },
        )
        try:
            with self.engine.begin() as conn:
                since = None
                if plan.uses_watermark:
                    since = max_value(conn, "market", table, "trading_day")

                for source_frame in self.source.bar_frames(
                    **plan.source_kwargs(watermark=since),
                ):
                    frame = attach_instrument_ids(
                        conn,
                        source_frame,
                        source=self.source_name,
                    )
                    frame = to_market_frame(frame, freq=plan.request.freq)
                    issues = validate_bars(
                        frame,
                        freq=plan.request.freq,
                        price_jump_warn_pct=self.settings.quality.price_jump_warn_pct,
                        expected_minutes_per_day=self.settings.quality.expected_minutes_per_day,
                    )
                    self._write_quality_issues(run_id=run_id, issues=issues)
                    if self.settings.quality.fail_on_error and has_error(issues):
                        raise ValueError(f"{job_name}: quality errors: {[issue.rule for issue in issues]}")
                    written = upsert_dataframe(
                        conn,
                        frame,
                        schema="market",
                        table=table,
                        primary_keys=("instrument_id", "dt"),
                        batch_rows=self.settings.batch_rows,
                    )
                    rows += written
                    logger.info(
                        "loaded bar batch",
                        extra={"job_name": job_name, "run_id": run_id, "rows_written": written, "table": table},
                    )

            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info("job finished", extra={"job_name": job_name, "run_id": run_id, "rows_written": rows})
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="failed", rows_written=rows, error=str(exc))
            logger.exception("job failed", extra={"job_name": job_name, "run_id": run_id, "rows_written": rows})
            raise
        return PipelineResult(job_name, rows, "success")

    def _write_quality_issues(self, *, run_id: int, issues: list[QualityIssue]) -> None:
        if not issues:
            return
        with self.engine.begin() as conn:
            write_quality_issues(conn, run_id=run_id, issues=issues)

    def _upsert_symbol_map(self, conn: Connection) -> int:
        symbol_map = self.source.symbol_map_frame()
        if symbol_map.empty:
            return 0
        tmp_name = f"getrich_symbol_map_stage_{uuid.uuid4().hex[:12]}"
        symbol_map.to_sql(
            tmp_name,
            con=conn,
            schema="pg_temp",
            if_exists="replace",
            index=False,
            method="multi",
        )
        conn.execute(
            text(
                f"""
                INSERT INTO meta.symbol_map (instrument_id, source, source_symbol)
                SELECT i.instrument_id, sm.source, sm.source_symbol
                FROM (
                    SELECT DISTINCT asset, exchange, symbol, source, source_symbol
                    FROM pg_temp.{qident(tmp_name)}
                ) sm
                JOIN meta.instruments i
                  ON i.asset = sm.asset
                 AND i.exchange = sm.exchange
                 AND i.symbol = sm.symbol
                ON CONFLICT (source, source_symbol) DO UPDATE
                SET instrument_id = EXCLUDED.instrument_id,
                    updated_at = now()
                """
            )
        )
        return len(symbol_map)

    def _upsert_future_contracts(self, conn: Connection) -> int:
        frame = self.source.future_contract_frame()
        if frame.empty:
            return 0
        frame = self._attach_contract_instrument_ids(conn, frame)
        for column in ["multiplier", "price_tick"]:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return upsert_dataframe(
            conn,
            frame,
            schema="meta",
            table="future_contracts",
            primary_keys=("instrument_id",),
            batch_rows=self.settings.batch_rows,
        )

    def _upsert_option_contracts(self, conn: Connection) -> int:
        frame = self.source.option_contract_frame()
        if frame.empty:
            return 0
        frame = self._attach_contract_instrument_ids(conn, frame)
        for column in ["strike", "multiplier"]:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return upsert_dataframe(
            conn,
            frame,
            schema="meta",
            table="option_contracts",
            primary_keys=("instrument_id",),
            batch_rows=self.settings.batch_rows,
        )

    def _attach_contract_instrument_ids(self, conn: Connection, frame):
        identities = frame.loc[:, ["asset", "exchange", "symbol"]].drop_duplicates()
        rows = (
            conn.execute(
                text(
                    """
                    SELECT instrument_id, asset, exchange, symbol
                    FROM meta.instruments
                    WHERE asset = ANY(:assets)
                      AND exchange = ANY(:exchanges)
                      AND symbol = ANY(:symbols)
                    """
                ),
                {
                    "assets": sorted(identities["asset"].dropna().astype(str).unique()),
                    "exchanges": sorted(identities["exchange"].dropna().astype(str).unique()),
                    "symbols": sorted(identities["symbol"].dropna().astype(str).unique()),
                },
            )
            .mappings()
            .all()
        )
        mapping = {
            (str(row["asset"]), str(row["exchange"]), str(row["symbol"])): int(row["instrument_id"])
            for row in rows
        }
        out = frame.copy()
        out["instrument_id"] = out.apply(
            lambda row: mapping.get((str(row["asset"]), str(row["exchange"]), str(row["symbol"]))),
            axis=1,
        )
        missing = out[out["instrument_id"].isna()]
        if not missing.empty:
            sample = missing.loc[:, ["asset", "exchange", "symbol"]].head(5).to_dict(orient="records")
            raise LookupError(f"contract instruments missing from meta.instruments: {sample}")
        return out
