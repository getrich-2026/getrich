from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

from getrich_data_import.adapters.registry import get_history_source, provider_names
from getrich_data_import.adapters.insight_p1 import (
    P1_DEFAULT_SAMPLE_DATASETS,
    P1_SAMPLE_DATASETS,
    export_insight_p1_samples,
)
from getrich_data_import.common.config import Settings
from getrich_data_import.common.logger import configure_logging, get_logger
from getrich_data_import.catalog import (
    dataset_specs_for_provider,
    registered_dataset_specs,
)
from getrich_data_import.db.health import check_database
from getrich_data_import.db.migrations import apply_migrations
from getrich_data_import.db.postgres import execute_schema, make_engine
from getrich_data_import.db.schema_check import check_schema
from getrich_data_import.extract import BAR_ASSETS, BAR_FREQUENCIES, BAR_MODES
from getrich_data_import.export import export_bars_to_parquet
from getrich_data_import.orchestration.pipeline import ImportPipeline


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="getrich-import",
        description="Import source data into the GetRich PostgreSQL database.",
    )
    parser.add_argument("--config", help="external TOML config path")
    parser.add_argument(
        "--provider",
        choices=provider_names(),
        help="history provider to use; defaults to config provider",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-schema", help="execute design-version backend DDL")
    sub.add_parser(
        "migrate-schema", help="apply backend DDL files with checksum tracking"
    )
    sub.add_parser(
        "check-db", help="check PostgreSQL connectivity and TimescaleDB extension"
    )
    sub.add_parser(
        "verify-schema", help="verify expected tables, hypertables, and migrations"
    )
    sub.add_parser("scan", help="show upstream parquet coverage")
    p_list = sub.add_parser("list-datasets", help="list registered import datasets")
    p_list.add_argument(
        "--all", action="store_true", help="show datasets for every provider"
    )
    p_show_job = sub.add_parser("show-job", help="show recent import job runs")
    p_show_job.add_argument("--run-id", type=int, help="specific run id")
    p_show_job.add_argument("--dataset", help="filter by dataset name")
    p_show_job.add_argument(
        "--limit", type=int, default=10, help="maximum rows when --run-id is omitted"
    )
    p_checkpoints = sub.add_parser(
        "list-checkpoints", help="list import checkpoints"
    )
    p_checkpoints.add_argument("--dataset", help="filter by dataset name")
    p_checkpoints.add_argument("--partition-key", help="filter by partition key")
    p_checkpoints.add_argument("--limit", type=int, default=20, help="maximum rows")
    p_fetch = sub.add_parser(
        "fetch-dataset", help="fetch one registered dataset into local parquet staging"
    )
    p_fetch.add_argument(
        "--dataset", required=True, help="registered dataset name, e.g. stock_bar_1d"
    )
    p_fetch.add_argument("--start-date", help="inclusive YYYY-MM-DD source date")
    p_fetch.add_argument("--end-date", help="inclusive YYYY-MM-DD source date")
    p_fetch.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="source symbol; can be repeated",
    )
    p_load_dataset = sub.add_parser(
        "load-dataset", help="load one staged parquet dataset into canonical tables"
    )
    p_load_dataset.add_argument(
        "--dataset", required=True, help="registered dataset name, e.g. stock_bar_1d"
    )
    p_load_dataset.add_argument(
        "--start-date", help="inclusive YYYY-MM-DD manifest date"
    )
    p_load_dataset.add_argument("--end-date", help="inclusive YYYY-MM-DD manifest date")
    p_load_dataset.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="source symbol; can be repeated",
    )
    p_load_dataset.add_argument(
        "--reload",
        action="store_true",
        help="explicitly reload staged files that are already marked loaded",
    )
    p_import_dataset = sub.add_parser(
        "import-dataset", help="fetch and load one registered dataset"
    )
    p_import_dataset.add_argument(
        "--dataset", required=True, help="registered dataset name, e.g. fund_nav"
    )
    p_import_dataset.add_argument("--start-date", help="inclusive YYYY-MM-DD date")
    p_import_dataset.add_argument("--end-date", help="inclusive YYYY-MM-DD date")
    p_import_dataset.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="source symbol; can be repeated",
    )
    p_import_dataset.add_argument(
        "--reload",
        action="store_true",
        help="load staged files even if they are already marked loaded",
    )
    p_p1_samples = sub.add_parser(
        "export-insight-p1-samples",
        help="export raw INSIGHT P1 sample datasets to local parquet",
    )
    p_p1_samples.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        choices=P1_SAMPLE_DATASETS,
        help="P1 dataset to export; can be repeated",
    )
    p_p1_samples.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p_p1_samples.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p_p1_samples.add_argument("--output-dir", help="local parquet output root")
    p_p1_samples.add_argument(
        "--stock-symbol", default="000001.SZ", help="stock sample symbol"
    )
    p_p1_samples.add_argument(
        "--index-symbol", default="000300.SH", help="index sample symbol"
    )
    p_p1_samples.add_argument(
        "--fund-symbol", default="161725.SZ", help="fund sample symbol"
    )
    p_p1_samples.add_argument(
        "--etf-symbol", default="510300.SH", help="ETF sample symbol"
    )
    sub.add_parser("load-metadata", help="load calendar, instruments, and symbol map")

    p_import = sub.add_parser("import-bars", help="import historical bars")
    p_import.add_argument("--asset", choices=BAR_ASSETS, required=True)
    p_import.add_argument("--freq", choices=BAR_FREQUENCIES, required=True)
    p_import.add_argument("--start-date", help="inclusive YYYY-MM-DD source date")
    p_import.add_argument("--end-date", help="inclusive YYYY-MM-DD source date")
    p_import.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="source symbol to import; can be repeated",
    )
    p_import.add_argument(
        "--mode",
        choices=BAR_MODES,
        default="auto",
        help="auto/full currently read the requested source range and rely on idempotent upsert",
    )

    p_export = sub.add_parser(
        "export-bars", help="export historical bars from PostgreSQL to parquet"
    )
    p_export.add_argument("--asset", choices=BAR_ASSETS, required=True)
    p_export.add_argument("--freq", choices=BAR_FREQUENCIES, required=True)
    p_export.add_argument("--start-date", help="inclusive YYYY-MM-DD trading day")
    p_export.add_argument("--end-date", help="inclusive YYYY-MM-DD trading day")
    p_export.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="canonical symbol; can be repeated",
    )
    p_export.add_argument(
        "--reload",
        action="store_true",
        help="overwrite the output parquet file if it already exists",
    )
    p_export.add_argument("--output", required=True, help="output parquet path")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings.load(args.config)
        provider = args.provider or settings.provider
        if args.cmd == "init-schema":
            engine = make_engine(settings.database_url)
            execute_schema(engine, settings.sql_dir)
            print(f"initialized schema from {settings.sql_dir}")
            return 0
        if args.cmd == "migrate-schema":
            engine = make_engine(settings.database_url)
            for result in apply_migrations(engine, settings.sql_dir):
                print(f"{result.file_name} {result.status}")
            return 0
        if args.cmd == "check-db":
            engine = make_engine(settings.database_url)
            health = check_database(engine)
            print(f"ok = {health.ok}")
            print(f"server_version = {health.server_version}")
            print(f"timescaledb_installed = {health.timescaledb_installed}")
            print(f"timescaledb_version = {health.timescaledb_version}")
            print(f"timescaledb_license = {health.timescaledb_license}")
            return 0
        if args.cmd == "verify-schema":
            engine = make_engine(settings.database_url)
            result = check_schema(engine)
            print(f"ok = {result.ok}")
            print(f"missing_tables = {list(result.missing_tables)}")
            print(f"missing_hypertables = {list(result.missing_hypertables)}")
            print(f"missing_migrations = {list(result.missing_migrations)}")
            print(f"missing_views = {list(result.missing_views)}")
            return 0 if result.ok else 1
        if args.cmd == "export-bars":
            engine = make_engine(settings.database_url)
            result = export_bars_to_parquet(
                engine,
                output_path=Path(args.output),
                asset=args.asset,
                freq=args.freq,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
                reload=args.reload,
            )
            print(f"exported {result.rows} rows to {result.path}")
            return 0
        if args.cmd == "list-datasets":
            specs = (
                registered_dataset_specs()
                if args.all
                else dataset_specs_for_provider(provider)
            )
            sys.stdout.write(_format_dataset_specs(specs))
            return 0
        if args.cmd == "show-job":
            engine = make_engine(settings.database_url)
            rows = _fetch_job_rows(
                engine,
                provider=provider,
                run_id=args.run_id,
                dataset_name=args.dataset,
                limit=args.limit,
            )
            sys.stdout.write(_format_job_rows(rows))
            return 0
        if args.cmd == "list-checkpoints":
            engine = make_engine(settings.database_url)
            rows = _fetch_checkpoint_rows(
                engine,
                provider=provider,
                dataset_name=args.dataset,
                partition_key=args.partition_key,
                limit=args.limit,
            )
            sys.stdout.write(_format_checkpoint_rows(rows))
            return 0

        source = get_history_source(provider, settings)
        if args.cmd == "scan":
            coverage = source.scan()
            print(f"provider = {provider}")
            if provider == "yinhe":
                print(f"data_dir = {settings.yinhe.data_dir}")
            print(f"calendar_files = {coverage.calendar_files}")
            for name, count in sorted(coverage.instruments.items()):
                print(f"{name} instruments = {count}")
            print(f"kline_day_files = {coverage.kline_day_files}")
            print(f"kline_min1_files = {coverage.kline_min1_files}")
            return 0

        engine = make_engine(settings.database_url)
        pipeline = ImportPipeline(settings=settings, engine=engine, source=source)
        if args.cmd == "load-metadata":
            result = pipeline.load_metadata()
            print(
                f"{result.job_name} status={result.status} rows={result.rows_written}"
            )
            return 0
        if args.cmd == "fetch-dataset":
            result = pipeline.fetch_dataset(
                dataset_name=args.dataset,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
            )
            print(
                f"{result.job_name} status={result.status} rows={result.rows_written}"
            )
            return 0
        if args.cmd == "load-dataset":
            result = pipeline.load_dataset(
                dataset_name=args.dataset,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
                reload=args.reload,
            )
            print(
                f"{result.job_name} status={result.status} rows={result.rows_written}"
            )
            return 0
        if args.cmd == "import-dataset":
            fetch_result = pipeline.fetch_dataset(
                dataset_name=args.dataset,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
            )
            print(
                f"{fetch_result.job_name} status={fetch_result.status} "
                f"rows={fetch_result.rows_written}"
            )
            load_result = pipeline.load_dataset(
                dataset_name=args.dataset,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
                reload=args.reload,
            )
            print(
                f"{load_result.job_name} status={load_result.status} "
                f"rows={load_result.rows_written}"
            )
            return 0
        if args.cmd == "export-insight-p1-samples":
            if provider != "insight":
                raise ValueError(
                    "export-insight-p1-samples requires --provider insight"
                )
            output_dir = (
                Path(args.output_dir).expanduser()
                if args.output_dir
                else settings.insight.staging_dir / "p1_samples"
            )
            samples = export_insight_p1_samples(
                source,  # type: ignore[arg-type]
                root_dir=output_dir,
                start_date=_parse_required_date(args.start_date),
                end_date=_parse_required_date(args.end_date),
                stock_symbol=args.stock_symbol,
                index_symbol=args.index_symbol,
                fund_symbol=args.fund_symbol,
                etf_symbol=args.etf_symbol,
                dataset_names=tuple(args.datasets or P1_DEFAULT_SAMPLE_DATASETS),
            )
            sys.stdout.write(_format_p1_samples(samples))
            return 0
        if args.cmd == "import-bars":
            result = pipeline.import_bars(
                asset=args.asset,
                freq=args.freq,
                mode=args.mode,
                start_date=_parse_date(args.start_date),
                end_date=_parse_date(args.end_date),
                symbols=args.symbols,
            )
            print(
                f"{result.job_name} status={result.status} rows={result.rows_written}"
            )
            return 0
    except Exception as exc:
        logger.error("command failed: %s", exc)
        return 1

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_required_date(value: str) -> date:
    return date.fromisoformat(value)


def _format_dataset_specs(specs: tuple[object, ...]) -> str:
    if not specs:
        return "No datasets registered.\n"
    headers = (
        "provider",
        "dataset",
        "status",
        "phase",
        "storage",
        "target",
        "asset",
        "freq",
    )
    rows = [
        (
            str(getattr(spec, "provider")),
            str(getattr(spec, "name")),
            str(getattr(spec, "status")),
            str(getattr(spec, "phase")),
            str(getattr(spec, "storage")),
            str(getattr(spec, "target")),
            str(getattr(spec, "asset") or "-"),
            str(getattr(spec, "freq") or "-"),
        )
        for spec in specs
    ]
    return _format_table(headers, rows)


def _fetch_job_rows(
    engine,
    *,
    provider: str,
    run_id: int | None,
    dataset_name: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = ["provider = :provider"]
    params: dict[str, object] = {"provider": provider, "limit": max(1, limit)}
    if run_id is not None:
        clauses.append("run_id = :run_id")
        params["run_id"] = run_id
    if dataset_name:
        clauses.append("dataset_name = :dataset_name")
        params["dataset_name"] = dataset_name
    limit_sql = "" if run_id is not None else "LIMIT :limit"
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT run_id,
                       job_name,
                       provider,
                       dataset_name,
                       start_date,
                       end_date,
                       status,
                       rows_written,
                       warning_count,
                       request,
                       checkpoint,
                       error,
                       started_at,
                       finished_at
                FROM ops.etl_job_run
                WHERE {" AND ".join(clauses)}
                ORDER BY run_id DESC
                {limit_sql}
                """
            ),
            params,
        ).mappings()
        return [dict(row) for row in rows]


def _fetch_checkpoint_rows(
    engine,
    *,
    provider: str,
    dataset_name: str | None,
    partition_key: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = ["provider = :provider"]
    params: dict[str, object] = {"provider": provider, "limit": max(1, limit)}
    if dataset_name:
        clauses.append("dataset_name = :dataset_name")
        params["dataset_name"] = dataset_name
    if partition_key:
        clauses.append("partition_key = :partition_key")
        params["partition_key"] = partition_key
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT provider,
                       dataset_name,
                       partition_key,
                       watermark_date,
                       watermark_ts,
                       state,
                       updated_at
                FROM ops.import_checkpoint
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC, dataset_name, partition_key
                LIMIT :limit
                """
            ),
            params,
        ).mappings()
        return [dict(row) for row in rows]


def _format_job_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No job runs found.\n"
    headers = (
        "run_id",
        "job_name",
        "dataset",
        "status",
        "range",
        "rows",
        "warnings",
        "request",
        "checkpoint",
    )
    table_rows = [
        (
            str(row["run_id"]),
            str(row["job_name"]),
            str(row.get("dataset_name") or ""),
            str(row["status"]),
            _date_range(row.get("start_date"), row.get("end_date")),
            str(row["rows_written"]),
            str(row["warning_count"]),
            _compact_json(row.get("request")),
            _compact_json(row.get("checkpoint")),
        )
        for row in rows
    ]
    return _format_table(headers, table_rows)


def _format_checkpoint_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No checkpoints found.\n"
    headers = (
        "provider",
        "dataset",
        "partition",
        "watermark_date",
        "watermark_ts",
        "state",
        "updated_at",
    )
    table_rows = [
        (
            str(row["provider"]),
            str(row["dataset_name"]),
            str(row["partition_key"]),
            str(row.get("watermark_date") or ""),
            str(row.get("watermark_ts") or ""),
            _compact_json(row.get("state")),
            str(row.get("updated_at") or ""),
        )
        for row in rows
    ]
    return _format_table(headers, table_rows)


def _date_range(start: object | None, end: object | None) -> str:
    if start and end:
        return f"{start}..{end}"
    if start:
        return str(start)
    if end:
        return str(end)
    return ""


def _compact_json(value: object) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _format_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _format_p1_samples(samples: tuple[object, ...]) -> str:
    """Render P1 sample export results.

    Time Complexity:
        O(n * c), where n is sample count and c is column count per sample.
    Space Complexity:
        O(n * c), for the rendered output.
    """

    lines = []
    for sample in samples:
        dataset_name = getattr(sample, "dataset_name")
        symbol = getattr(sample, "symbol")
        rows = getattr(sample, "rows")
        columns = ",".join(getattr(sample, "columns"))
        error = getattr(sample, "error")
        staged_file = getattr(sample, "staged_file")
        if error:
            lines.append(f"{dataset_name} symbol={symbol} status=error error={error}")
            continue
        path = getattr(staged_file, "path", "") if staged_file else ""
        status = "written" if staged_file else "empty"
        lines.append(
            f"{dataset_name} symbol={symbol} status={status} rows={rows} path={path}"
        )
        lines.append(f"{dataset_name} columns={columns}")
    return "\n".join(lines) + ("\n" if lines else "")


if __name__ == "__main__":
    raise SystemExit(main())
