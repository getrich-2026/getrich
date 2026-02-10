from getrich.apps.data.etl.fromrq import export_all_instruments, init_rq
from getrich.apps.data.jobs import DataImportJob
from getrich.libs.clickhouse import ClickHouseConnectionPool


def import_rq_instruments(save_to_db: bool = True) -> None:
    init_rq()
    export_all_instruments(r"D:\data\ricequant", save_to_db=save_to_db)


def import_hdb_minbars() -> None:
    HDB_PATH = r"E:\data\hdb"
    pool = ClickHouseConnectionPool()
    import_job = DataImportJob(hdb_base_path=HDB_PATH, pool=pool, max_workers=4)
    import_job.run_full_import(
        start_year=2026,
        end_year=2026,
        skip_existing=True,
        skip_mode="latest",  # check all existing dates
        import_min_bar=True,
    )


if __name__ == "__main__":
    # import_hdb_minbars()
    import_rq_instruments()
