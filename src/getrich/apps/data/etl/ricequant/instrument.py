# pylint: disable=no-member  # rqdatac uses dynamic API binding
from __future__ import annotations

from pathlib import Path

import pandas as pd
import rqdatac as rq
from lntools import Logger, handle_path

from getrich.libs.clickhouse.database import ClickHouseClient

from ..transforms import (
    clean_dataframe_for_clickhouse,
)
from .auth import init_rq
from .constants import INSTRUMENT_TYPES

log = Logger(module_name="RiceQuantInstrumentETL")


def export_all_instruments(
    output_dir: str, save_to_db: bool = True, inst_types: list[str] | None = None
) -> dict[str, bool]:
    """
    Export all instrument types from RiceQuant to Parquet files and optionally to ClickHouse.

    Args:
        output_dir: Directory to save the parquet files.
        save_to_db: Whether to also save data to ClickHouse database.
        inst_types: List of instrument types to export. Defaults to all INSTRUMENT_TYPES.

    Returns:
        Dict mapping instrument type to export success status.
    """
    root: Path = handle_path(output_dir)
    types_to_export = inst_types or INSTRUMENT_TYPES
    log.info(f"Starting export to {root}...")

    client: ClickHouseClient | None = None
    if save_to_db:
        client = ClickHouseClient()

    results: dict[str, bool] = {}

    for inst_type in types_to_export:
        try:
            log.info(f"Fetching {inst_type}...")
            # Fetch data (returns pandas DataFrame)
            df_pandas: pd.DataFrame = rq.all_instruments(type=inst_type, date=None, market="cn")

            if df_pandas.empty:
                log.warning(f"No data found for {inst_type}")
                results[inst_type] = False
                continue

            # Save as Parquet locally
            file_path = root / f"all_instruments_{inst_type}.parquet"
            df_pandas.to_parquet(file_path)
            log.info(f"Saved {inst_type} to {file_path} (Rows: {len(df_pandas)})")

            # Save to ClickHouse
            if save_to_db and client is not None:
                # Clean data before insertion
                df_cleaned = clean_dataframe_for_clickhouse(df_pandas)
                table_name = f"rq.instruments_{inst_type.lower()}"
                success = client.insert_data(table_name, df_cleaned)
                if success:
                    log.info(f"Inserted {len(df_cleaned)} rows into {table_name}")
                else:
                    log.error(f"Failed to insert {inst_type} into database")
                results[inst_type] = success
            else:
                results[inst_type] = True

        except Exception as e:
            log.error(f"Error exporting {inst_type}: {e}")
            results[inst_type] = False

    # Summary
    success_count = sum(results.values())
    log.info(f"Export completed: {success_count}/{len(types_to_export)} types succeeded")

    return results


if __name__ == "__main__":
    init_rq()
    export_all_instruments(r"E:\data\ricequant", save_to_db=True, inst_types=["Option"])
