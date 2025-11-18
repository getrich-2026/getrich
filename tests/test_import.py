from getrich.data import ClickHouseConnectionPool, DEFAULT_DB_CONFIG, DataImportJob


if __name__ == '__main__':
    pool = ClickHouseConnectionPool(
        host=DEFAULT_DB_CONFIG['host'],
        port=DEFAULT_DB_CONFIG['port'],
        user=DEFAULT_DB_CONFIG['user'],
        password=DEFAULT_DB_CONFIG['password'],
        database=DEFAULT_DB_CONFIG['database']
    )
    HDB_PATH = 'E:/data/bar'
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

    with pool.get_connection() as conn:
        parquet_importer_job = DataImportJob(hdb_base_path=HDB_PATH, pool=pool, max_workers=5)
        parquet_importer_job.run_parquet_import(
            start_date=20251117,
            end_date=20251117
        )
    # from getrich.data.clickhouse import DayBarTable
    # day_bar_table = DayBarTable(pool=pool)
    # day_bar_table.drop()

    # from getrich.data.clickhouse import MinBarTable
    # min_bar_table = MinBarTable(pool=pool)
    # min_bar_table.drop()
