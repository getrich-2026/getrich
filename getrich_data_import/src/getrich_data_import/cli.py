from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

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
        "--fund-symbol", default="510300.SH", help="fund or ETF sample symbol"
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
