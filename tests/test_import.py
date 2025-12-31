from getrich.apps.data.jobs import DataImportJob
from getrich.libs.clickhouse import ClickHouseConnectionPool

if __name__ == "__main__":
    hdb_path = r"E:\data\hdb"
    pool = ClickHouseConnectionPool()
    import_job = DataImportJob(hdb_base_path=hdb_path, pool=pool, max_workers=5)
    import_job.run_full_import(
        start_year=2025,
        end_year=2025,
        skip_existing=True,
        import_min_bar=True,
        import_day_bar=False,
    )
