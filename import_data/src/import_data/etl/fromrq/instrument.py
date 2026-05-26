from __future__ import annotations

from pathlib import Path

from import_data.core.logger import Logger
from import_data.core.utils import handle_path

from import_data.gateways.ricequant.client import RQDataAPI
from import_data.db.clickhouse.database import ClickHouseClient

from import_data.etl.transforms import (
    clean_dataframe_for_clickhouse,
)
from import_data.etl.fromrq.constants import INSTRUMENT_TYPES

log = Logger(module_name="RiceQuantInstrumentETL")


def export_all_instruments(
    output_dir: str | None = None,
    save_to_parquet: bool = False,
    save_to_db: bool = True,
    inst_types: list[str] | None = None,
    api: RQDataAPI | None = None,
) -> dict[str, bool]:
    """
    Export all instrument types from RiceQuant to Parquet files and/or ClickHouse.

    Args:
        output_dir: Directory to save the parquet files. Required if save_to_parquet=True.
        save_to_parquet: Whether to save data as parquet files locally.
        save_to_db: Whether to save data to ClickHouse database.
        inst_types: List of instrument types to export. Defaults to all INSTRUMENT_TYPES.
        api: Optional RQDataAPI instance. If None, a new one will be created and login called.

    Returns:
        Dict mapping instrument type to export success status.

    Raises:
        ValueError: If save_to_parquet=True but output_dir is not provided.
        ValueError: If both save_to_parquet and save_to_db are False.
    """
    # 参数验证
    if save_to_parquet and output_dir is None:
        raise ValueError("output_dir is required when save_to_parquet=True")

    if not save_to_parquet and not save_to_db:
        raise ValueError("At least one of save_to_parquet or save_to_db must be True")

    # 初始化 API
    if api is None:
        api = RQDataAPI()
        api.login()

    # 只在需要保存 parquet 时处理 output_dir
    root: Path | None = None
    if save_to_parquet:
        assert output_dir is not None  # 类型检查辅助
        root = handle_path(output_dir)
        log.info(f"Starting export to {root}...")
    else:
        log.info("Starting export (database only)...")

    types_to_export = inst_types or INSTRUMENT_TYPES

    client: ClickHouseClient | None = None
    if save_to_db:
        client = ClickHouseClient()

    results: dict[str, bool] = {}

    for inst_type in types_to_export:
        try:
            log.info(f"Fetching {inst_type}...")
            # Use RQDataAPI instead of direct rqdatac call
            df = api.get_all_instruments(inst_type=inst_type, date=None, market="cn")

            if df.is_empty():
                log.warning(f"No data found for {inst_type}")
                results[inst_type] = False
                continue

            # Convert to pandas for downstream compatibility (parquet, clickhouse clean)
            df_pandas = df.to_pandas()

            # Save as Parquet locally (if enabled)
            if save_to_parquet:
                assert root is not None  # 类型检查辅助
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
    log.info(
        f"Export completed: {success_count}/{len(types_to_export)} types succeeded"
    )

    return results


if __name__ == "__main__":
    # Initialize RiceQuant using new API
    api = RQDataAPI()
    api.login()

    # 示例 1: 只保存到数据库
    # export_all_instruments(save_to_db=True)

    # 示例 2: 只保存 parquet
    # export_all_instruments(output_dir=r"E:\data\ricequant", save_to_parquet=True, save_to_db=False)

    # 示例 3: 两者都保存
    export_all_instruments(
        output_dir=r"D:\data\ricequant", save_to_parquet=True, save_to_db=True, api=api
    )
