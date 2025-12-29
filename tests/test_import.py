from getrich.apps.data.etl.ricequant import INSTRUMENT_TYPES
from getrich.libs.clickhouse import ClickHouseConnectionPool

if __name__ == "__main__":
    pool = ClickHouseConnectionPool()
    with pool.get_connection() as conn:
        for inst_type in INSTRUMENT_TYPES:
            sql = f"select * from ref.instruments where type = '{inst_type}' limit 5;"
            df = conn.query_sql(sql)
            print(df)
    # HDB_PATH = "E:/data/bar"
    # with pool.get_connection() as conn:
    #     importer_job = DataImportJob(hdb_base_path=HDB_PATH, pool=pool, max_workers=5)
    #     importer_job.run_full_import(
    #         start_year=2005,
    #         end_year=2025,
    #         symbols=None,  # None means import all symbols, can also specify like ["SH.*", "SZ.*"]
    #         skip_existing=True,  # Skip existing data (only applies to MinBar)
    #         import_min_bar=True,  # Import minute bar data
    #         import_day_bar=False,  # Import day bar data
    #         import_code_info=True  # Import contract info (imported along with MinBar)
    #     )

    # with pool.get_connection() as conn:
    #     importer_job_incremental = DataImportJob(hdb_base_path=HDB_PATH, pool=pool, max_workers=5)
    #     importer_job_incremental.run_incremental_import(
    #         symbols=None,  # None means import all symbols
    #         import_min_bar=True,  # Import minute bar data
    #         import_day_bar=False,  # Import day bar data
    #         import_code_info=True  # Import contract info
    #     )

    # with pool.get_connection() as conn:
    #     csv_importer_job = DataImportJob(hdb_base_path=HDB_PATH, pool=pool, max_workers=5)
    #     csv_importer_job.run_csv_import(
    #         start_date=20251113,
    #         end_date=20251114
    #     )
