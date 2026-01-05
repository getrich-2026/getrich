from getrich.apps.data.jobs import DataImportJob
from getrich.libs.clickhouse import ClickHouseConnectionPool

if __name__ == "__main__":
    hdb_path = r"D:\data\hdb"
    pool = ClickHouseConnectionPool()
    import_job = DataImportJob(hdb_base_path=hdb_path, pool=pool, max_workers=5)
    import_job.run_full_import(
        start_year=2005,
        end_year=2025,
        skip_existing=True,
        skip_mode="all",  # check all existing dates
        import_min_bar=True,
    )

    # TODO: 再跑一遍，补足导入错误的历史数据
