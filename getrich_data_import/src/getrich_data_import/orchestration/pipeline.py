from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date
from datetime import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine

from getrich_data_import.adapters.base import HistoryDataSource
from getrich_data_import.catalog import get_dataset_spec
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
from getrich_data_import.quality.rules import (
    QualityIssue,
    has_error,
    validate_bars,
    write_quality_issues,
)
from getrich_data_import.services import TradingCalendarService
from getrich_data_import.staging import (
    file_sha256,
    parquet_schema_fingerprint,
    write_staging_parquet,
)
from getrich_data_import.transform.bars import to_market_frame


logger = get_logger(__name__)
NIGHT_SESSION_CUTOFF = time(21, 0)


@dataclass(frozen=True)
class PipelineResult:
    job_name: str
    rows_written: int
    status: str


class ImportPipeline:
    def __init__(
        self, *, settings: Settings, engine: Engine, source: HistoryDataSource
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.source = source
        self.source_name = str(getattr(source, "provider", source.name))

    def load_metadata(self) -> PipelineResult:
        job_name = "load_metadata"
        rows = 0
        with self.engine.begin() as conn:
            run_id = insert_job_run(conn, job_name=job_name)
        logger.info(
            "job started",
            extra={
                "job_name": job_name,
                "run_id": run_id,
                "provider": self.source_name,
            },
        )
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
                        extra={
                            "job_name": job_name,
                            "run_id": run_id,
                            "rows_written": written,
                        },
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
                rows += self._upsert_symbol_map(conn, instruments)
                rows += self._upsert_future_contracts(conn)
                rows += self._upsert_option_contracts(conn)
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info(
                "job finished",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    rows_written=rows,
                    error=str(exc),
                )
            logger.exception(
                "job failed",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
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
                    if plan.request.freq == "1m":
                        frame = self._assign_minute_trading_days(conn, frame)
                    expected_trading_days = self._expected_trading_days(
                        conn,
                        frame,
                        start_date=plan.request.start_date,
                        end_date=plan.request.end_date,
                    )
                    frame = to_market_frame(frame, freq=plan.request.freq)
                    issues = validate_bars(
                        frame,
                        freq=plan.request.freq,
                        price_jump_warn_pct=self.settings.quality.price_jump_warn_pct,
                        expected_minutes_per_day=self.settings.quality.expected_minutes_per_day,
                        expected_trading_days=expected_trading_days,
                    )
                    self._write_quality_issues(run_id=run_id, issues=issues)
                    if self.settings.quality.fail_on_error and has_error(issues):
                        raise ValueError(
                            f"{job_name}: quality errors: {[issue.rule for issue in issues]}"
                        )
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
                        extra={
                            "job_name": job_name,
                            "run_id": run_id,
                            "rows_written": written,
                            "table": table,
                        },
                    )

            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info(
                "job finished",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    rows_written=rows,
                    error=str(exc),
                )
            logger.exception(
                "job failed",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
            raise
        return PipelineResult(job_name, rows, "success")

    def fetch_dataset(
        self,
        *,
        dataset_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> PipelineResult:
        """Fetch one ready dataset into local Parquet staging.

        Args:
            dataset_name: Registered dataset name.
            start_date: Inclusive source start date.
            end_date: Inclusive source end date.
            symbols: Optional source symbols.

        Time Complexity:
            O(n * c), where n is fetched row count and c is column count.
        Space Complexity:
            O(b * c), where b is the largest source batch held in memory.
        """

        spec = get_dataset_spec(self.source_name, dataset_name)
        if spec.status != "ready":
            raise ValueError(
                f"dataset is not ready for fetch: {self.source_name}.{dataset_name}"
            )
        if (
            spec.asset is None
            or spec.freq is None
            or spec.source_method != "InsightSource.bar_frames"
        ):
            raise ValueError(
                f"fetch-dataset currently supports ready bar datasets only: {dataset_name}"
            )

        job_name = f"fetch_{spec.name}_parquet"
        rows = 0
        files = 0
        with self.engine.begin() as conn:
            run_id = insert_job_run(
                conn, job_name=job_name, asset=spec.asset, freq=spec.freq
            )
        logger.info(
            "job started",
            extra={
                "job_name": job_name,
                "run_id": run_id,
                "provider": self.source_name,
                "dataset": spec.name,
            },
        )
        try:
            for batch_index, source_frame in enumerate(
                self.source.bar_frames(
                    asset=spec.asset,
                    freq=spec.freq,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                ),
                start=1,
            ):
                if source_frame.empty:
                    continue
                frame_start, frame_end = _frame_date_range(source_frame)
                staged = write_staging_parquet(
                    source_frame,
                    root_dir=self.settings.insight.staging_dir,
                    provider=self.source_name,
                    dataset_name=spec.name,
                    asset=spec.asset,
                    freq=spec.freq,
                    start_date=start_date or frame_start,
                    end_date=end_date or frame_end,
                    partition_key=_staging_partition_key(
                        source_frame, batch_index=batch_index
                    ),
                )
                manifest = pd.DataFrame(
                    [
                        staged.manifest_row(
                            provider=self.source_name,
                            dataset_name=spec.name,
                            asset=spec.asset,
                            freq=spec.freq,
                            start_date=start_date or frame_start,
                            end_date=end_date or frame_end,
                            fetch_run_id=run_id,
                            metadata={
                                "columns": list(map(str, source_frame.columns)),
                                "source_symbols": _source_symbols(source_frame),
                            },
                        )
                    ]
                )
                with self.engine.begin() as conn:
                    upsert_dataframe(
                        conn,
                        manifest,
                        schema="staging",
                        table="parquet_file",
                        primary_keys=("provider", "dataset_name", "source_path"),
                        batch_rows=self.settings.batch_rows,
                    )
                rows += staged.row_count
                files += 1
                logger.info(
                    "staged parquet batch",
                    extra={
                        "job_name": job_name,
                        "run_id": run_id,
                        "rows_written": staged.row_count,
                        "files_written": files,
                        "path": str(staged.path),
                    },
                )
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info(
                "job finished",
                extra={
                    "job_name": job_name,
                    "run_id": run_id,
                    "rows_written": rows,
                    "files_written": files,
                },
            )
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    rows_written=rows,
                    error=str(exc),
                )
            logger.exception(
                "job failed",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
            raise
        return PipelineResult(job_name, rows, "success")

    def load_dataset(
        self,
        *,
        dataset_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        reload: bool = False,
    ) -> PipelineResult:
        """Load one ready staged Parquet dataset into canonical tables.

        Args:
            dataset_name: Registered dataset name.
            start_date: Optional inclusive manifest start-date filter.
            end_date: Optional inclusive manifest end-date filter.
            symbols: Optional source-symbol filter applied after reading staged files.
            reload: Whether to explicitly reload files that are already marked loaded.

        Time Complexity:
            O(n * c), where n is staged row count and c is column count.
        Space Complexity:
            O(b * c), where b is the largest staged file held in memory.
        """

        spec = get_dataset_spec(self.source_name, dataset_name)
        if spec.status != "ready":
            raise ValueError(
                f"dataset is not ready for load: {self.source_name}.{dataset_name}"
            )
        if (
            spec.asset is None
            or spec.freq is None
            or spec.source_method != "InsightSource.bar_frames"
        ):
            raise ValueError(
                f"load-dataset currently supports ready bar datasets only: {dataset_name}"
            )

        table = f"{spec.asset}_bar_{spec.freq}"
        job_name = f"load_{spec.name}_parquet"
        rows = 0
        with self.engine.begin() as conn:
            run_id = insert_job_run(
                conn, job_name=job_name, asset=spec.asset, freq=spec.freq
            )
            staged_files = _staged_parquet_files(
                conn,
                provider=self.source_name,
                dataset_name=spec.name,
                start_date=start_date,
                end_date=end_date,
                include_loaded=reload,
            )
        logger.info(
            "job started",
            extra={
                "job_name": job_name,
                "run_id": run_id,
                "provider": self.source_name,
                "dataset": spec.name,
                "files": len(staged_files),
            },
        )
        try:
            for staged_file in staged_files:
                try:
                    _validate_staged_parquet_file(staged_file)
                except Exception as exc:
                    with self.engine.begin() as conn:
                        _mark_staged_file_failed(
                            conn, file_id=int(staged_file["file_id"]), error=str(exc)
                        )
                    raise
                source_frame = pd.read_parquet(staged_file["source_path"])
                source_frame = _filter_frame_by_date_range(
                    source_frame,
                    start_date=start_date,
                    end_date=end_date,
                )
                if symbols and "source_symbol" in source_frame.columns:
                    wanted = {str(symbol) for symbol in symbols}
                    source_frame = source_frame[
                        source_frame["source_symbol"].astype(str).isin(wanted)
                    ]
                if source_frame.empty:
                    continue
                with self.engine.begin() as conn:
                    frame = attach_instrument_ids(
                        conn, source_frame, source=self.source_name
                    )
                    if spec.freq == "1m":
                        frame = self._assign_minute_trading_days(conn, frame)
                    expected_trading_days = self._expected_trading_days(
                        conn,
                        frame,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    frame = to_market_frame(frame, freq=spec.freq)
                    issues = validate_bars(
                        frame,
                        freq=spec.freq,
                        price_jump_warn_pct=self.settings.quality.price_jump_warn_pct,
                        expected_minutes_per_day=self.settings.quality.expected_minutes_per_day,
                        expected_trading_days=expected_trading_days,
                    )
                    self._write_quality_issues(run_id=run_id, issues=issues)
                    if self.settings.quality.fail_on_error and has_error(issues):
                        raise ValueError(
                            f"{job_name}: quality errors: {[issue.rule for issue in issues]}"
                        )
                    written = upsert_dataframe(
                        conn,
                        frame,
                        schema="market",
                        table=table,
                        primary_keys=("instrument_id", "dt"),
                        batch_rows=self.settings.batch_rows,
                    )
                    _mark_staged_file_loaded(
                        conn, file_id=int(staged_file["file_id"]), load_run_id=run_id
                    )
                rows += written
                logger.info(
                    "loaded staged parquet file",
                    extra={
                        "job_name": job_name,
                        "run_id": run_id,
                        "rows_written": written,
                        "file_id": staged_file["file_id"],
                    },
                )
            with self.engine.begin() as conn:
                finish_job_run(conn, run_id=run_id, status="success", rows_written=rows)
            logger.info(
                "job finished",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
        except Exception as exc:
            with self.engine.begin() as conn:
                finish_job_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    rows_written=rows,
                    error=str(exc),
                )
            logger.exception(
                "job failed",
                extra={"job_name": job_name, "run_id": run_id, "rows_written": rows},
            )
            raise
        return PipelineResult(job_name, rows, "success")

    def _write_quality_issues(self, *, run_id: int, issues: list[QualityIssue]) -> None:
        if not issues:
            return
        with self.engine.begin() as conn:
            write_quality_issues(conn, run_id=run_id, issues=issues)

    def _upsert_symbol_map(self, conn: Connection, instruments: pd.DataFrame) -> int:
        if instruments.empty:
            return 0
        symbol_map = instruments.loc[:, ["asset", "exchange", "symbol"]].copy()
        symbol_map["source"] = self.source_name
        symbol_map["source_symbol"] = symbol_map["symbol"]
        if symbol_map.empty:
            return 0
        tmp_name = f"getrich_symbol_map_stage_{uuid.uuid4().hex[:12]}"
        safe_chunk = min(
            self.settings.batch_rows, max(1, 60_000 // max(1, len(symbol_map.columns)))
        )
        symbol_map.to_sql(
            tmp_name,
            con=conn,
            schema="pg_temp",
            if_exists="replace",
            index=False,
            chunksize=safe_chunk,
            method="multi",
        )
        result = conn.execute(
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
        rows = int(result.rowcount or 0)
        conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{qident(tmp_name)}"))
        return rows

    def _assign_minute_trading_days(
        self, conn: Connection, frame: pd.DataFrame
    ) -> pd.DataFrame:
        if frame.empty or not {"exchange", "dt"}.issubset(frame.columns):
            return frame
        service = TradingCalendarService(conn)
        out = frame.copy()
        out["trading_day"] = [
            service.assign_trading_day(str(exchange), timestamp, NIGHT_SESSION_CUTOFF)
            for exchange, timestamp in zip(
                out["exchange"], pd.to_datetime(out["dt"]), strict=False
            )
        ]
        return out

    def _expected_trading_days(
        self,
        conn: Connection,
        frame: pd.DataFrame,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[date] | None:
        if (
            frame.empty
            or "exchange" not in frame.columns
            or "trading_day" not in frame.columns
        ):
            return None
        exchanges = sorted(
            {str(exchange) for exchange in frame["exchange"].dropna().unique()}
        )
        if len(exchanges) != 1:
            return None
        start = start_date or min(frame["trading_day"])
        end = end_date or max(frame["trading_day"])
        rows = conn.execute(
            text(
                """
                SELECT trading_day
                FROM meta.trading_calendar
                WHERE exchange = :exchange
                  AND is_open = true
                  AND trading_day >= :start_date
                  AND trading_day <= :end_date
                ORDER BY trading_day
                """
            ),
            {"exchange": exchanges[0], "start_date": start, "end_date": end},
        ).scalars()
        days = [day for day in rows]
        return days or None

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
                    "exchanges": sorted(
                        identities["exchange"].dropna().astype(str).unique()
                    ),
                    "symbols": sorted(
                        identities["symbol"].dropna().astype(str).unique()
                    ),
                },
            )
            .mappings()
            .all()
        )
        mapping = {
            (str(row["asset"]), str(row["exchange"]), str(row["symbol"])): int(
                row["instrument_id"]
            )
            for row in rows
        }
        out = frame.copy()
        out["instrument_id"] = out.apply(
            lambda row: mapping.get(
                (str(row["asset"]), str(row["exchange"]), str(row["symbol"]))
            ),
            axis=1,
        )
        missing = out[out["instrument_id"].isna()]
        if not missing.empty:
            sample = (
                missing.loc[:, ["asset", "exchange", "symbol"]]
                .head(5)
                .to_dict(orient="records")
            )
            raise LookupError(
                f"contract instruments missing from meta.instruments: {sample}"
            )
        return out


def _source_symbols(frame: pd.DataFrame) -> list[str]:
    if "source_symbol" not in frame.columns:
        return []
    return sorted(frame["source_symbol"].dropna().astype(str).unique().tolist())


def _staging_partition_key(frame: pd.DataFrame, *, batch_index: int) -> str:
    symbols = _source_symbols(frame)
    digest_source = ",".join(symbols) if symbols else str(batch_index)
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    return f"batch_{batch_index:05d}_{digest}"


def _frame_date_range(frame: pd.DataFrame) -> tuple[date | None, date | None]:
    if "trading_day" not in frame.columns or frame.empty:
        return None, None
    days = pd.to_datetime(frame["trading_day"], errors="coerce").dropna()
    if days.empty:
        return None, None
    return days.min().date(), days.max().date()


def _staged_parquet_files(
    conn: Connection,
    *,
    provider: str,
    dataset_name: str,
    start_date: date | None,
    end_date: date | None,
    include_loaded: bool,
) -> list[dict[str, object]]:
    statuses = ("written", "loaded") if include_loaded else ("written",)
    clauses = [
        "provider = :provider",
        "dataset_name = :dataset_name",
        "status = ANY(:statuses)",
    ]
    params: dict[str, object] = {"provider": provider, "dataset_name": dataset_name}
    params["statuses"] = list(statuses)
    if start_date is not None:
        clauses.append("(end_date IS NULL OR end_date >= :start_date)")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append("(start_date IS NULL OR start_date <= :end_date)")
        params["end_date"] = end_date
    rows = conn.execute(
        text(
            f"""
            SELECT file_id,
                   source_path,
                   content_hash,
                   file_size_bytes,
                   schema_fingerprint,
                   start_date,
                   end_date,
                   row_count
            FROM staging.parquet_file
            WHERE {" AND ".join(clauses)}
            ORDER BY start_date NULLS FIRST, end_date NULLS FIRST, file_id
            """
        ),
        params,
    ).mappings()
    out: list[dict[str, object]] = []
    for row in rows:
        path = Path(str(row["source_path"])).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"staged parquet file does not exist: {path}")
        out.append({**dict(row), "source_path": path})
    return out


def _filter_frame_by_date_range(
    frame: pd.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
) -> pd.DataFrame:
    if frame.empty or (start_date is None and end_date is None):
        return frame
    date_col = (
        "trading_day"
        if "trading_day" in frame.columns
        else "dt"
        if "dt" in frame.columns
        else None
    )
    if date_col is None:
        raise ValueError(
            "staged parquet file cannot be date-filtered without trading_day or dt column"
        )
    days = pd.to_datetime(frame[date_col], errors="coerce").dt.date
    mask = pd.Series(True, index=frame.index)
    if start_date is not None:
        mask &= days >= start_date
    if end_date is not None:
        mask &= days <= end_date
    return frame.loc[mask.fillna(False)].copy()


def _validate_staged_parquet_file(staged_file: dict[str, object]) -> None:
    path = Path(str(staged_file["source_path"])).expanduser()
    expected_size = staged_file.get("file_size_bytes")
    if expected_size is not None and path.stat().st_size != int(expected_size):
        raise ValueError(f"staged parquet file size changed: {path}")
    expected_hash = staged_file.get("content_hash")
    if expected_hash and file_sha256(path) != str(expected_hash):
        raise ValueError(f"staged parquet file content hash mismatch: {path}")
    expected_schema = staged_file.get("schema_fingerprint")
    if expected_schema and parquet_schema_fingerprint(path) != str(expected_schema):
        raise ValueError(f"staged parquet schema fingerprint mismatch: {path}")


def _mark_staged_file_loaded(
    conn: Connection, *, file_id: int, load_run_id: int
) -> None:
    conn.execute(
        text(
            """
            UPDATE staging.parquet_file
            SET status = 'loaded',
                load_run_id = :load_run_id,
                loaded_at = now()
            WHERE file_id = :file_id
            """
        ),
        {"file_id": file_id, "load_run_id": load_run_id},
    )


def _mark_staged_file_failed(conn: Connection, *, file_id: int, error: str) -> None:
    conn.execute(
        text(
            """
            UPDATE staging.parquet_file
            SET status = 'failed',
                error = :error
            WHERE file_id = :file_id
            """
        ),
        {"file_id": file_id, "error": error},
    )
