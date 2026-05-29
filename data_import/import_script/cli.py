from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ImportConfig
from .db import execute_sql_files, make_engine
from .importer import ImportContext, ImportMode
from .raw_store import RawDataStore
from .registry import get_importers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_import",
        description="Import yinhe_data_fetcher parquet data into GetRich PostgreSQL tables.",
    )
    parser.add_argument("-c", "--config", help="YAML config path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-schema", help="execute SQL files under sql_script_sample")
    sub.add_parser("scan", help="show local parquet source coverage")

    p_plan = sub.add_parser("plan", help="resolve full/incremental mode for importers")
    p_plan.add_argument("--only", action="append", help="run only this importer")
    p_plan.add_argument(
        "--mode",
        choices=["auto", "full", "incremental"],
        default="auto",
        help="requested import mode",
    )

    p_run = sub.add_parser("run", help="import data into PostgreSQL")
    p_run.add_argument("--only", action="append", help="run only this importer")
    p_run.add_argument(
        "--mode",
        choices=["auto", "full", "incremental"],
        default="auto",
        help="requested import mode",
    )
    p_run.add_argument("--dry-run", action="store_true", help="transform only; do not write")
    return parser


def cmd_scan(cfg: ImportConfig) -> int:
    store = RawDataStore(cfg.data_dir)
    print(f"data_dir = {cfg.data_dir}")
    print(f"calendar files = {len(store.calendar_paths())}")
    for security_type in [
        "EXTRA_STOCK_A_SH_SZ",
        "EXTRA_ETF",
        "EXTRA_IDNEX_A_SH_SZ",
    ]:
        print(f"{security_type} codes = {len(store.hist_codes(security_type))}")
    print(f"kline_day files = {len(store.kline_day_paths())}")
    print(f"backward_factor symbols = {len(store.factor_file_by_code)}")
    return 0


def cmd_plan(cfg: ImportConfig, only: list[str] | None, mode: ImportMode) -> int:
    engine = make_engine(cfg.database_url)
    ctx = ImportContext(cfg, engine, RawDataStore(cfg.data_dir), dry_run=True)
    for importer in get_importers(only):
        resolved = importer.decide_mode(ctx, mode)
        since = None if resolved == "full" else importer.latest_watermark(ctx)
        print(
            f"{importer.name:<20} table={importer.target_table:<22} "
            f"mode={resolved:<11} since={since}"
        )
    return 0


def cmd_run(
    cfg: ImportConfig,
    only: list[str] | None,
    mode: ImportMode,
    dry_run: bool,
) -> int:
    engine = make_engine(cfg.database_url)
    ctx = ImportContext(cfg, engine, RawDataStore(cfg.data_dir), dry_run=dry_run)
    for importer in get_importers(only):
        result = importer.run(ctx, mode)
        suffix = " (dry-run)" if dry_run else ""
        print(
            f"{result.name:<20} table={result.table:<22} "
            f"mode={result.mode:<11} rows={result.rows}{suffix}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "scan" and not args.config:
            cfg = ImportConfig(database_url="postgresql+psycopg://unused/unused")
        else:
            cfg = ImportConfig.load(args.config)

        if args.cmd == "init-schema":
            engine = make_engine(cfg.database_url)
            execute_sql_files(engine, cfg.sql_dir, cfg.schema_files)
            print(f"initialized schema from {Path(cfg.sql_dir)}")
            return 0
        if args.cmd == "scan":
            return cmd_scan(cfg)
        if args.cmd == "plan":
            return cmd_plan(cfg, args.only, args.mode)
        if args.cmd == "run":
            return cmd_run(cfg, args.only, args.mode, args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.cmd}")
    return 2

