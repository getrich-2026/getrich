from getrich.libs.clickhouse import ClickHouseClient
from lntools.utils import Logger
from getrich.config import settings

logger = Logger(module_name="ImportRiceQuantJob")

def run_instrument_export() -> None:
    """
    导出 RiceQuant 合约信息到 ClickHouse 或 Parquet
    """
    if not settings.ricequant.enabled:
        logger.info("RiceQuant is disabled in settings, skipping instrument export.")
        return

    try:
        from ..etl.fromrq import export_all_instruments, init_rq

        logger.info("RiceQuant is enabled, exporting instruments...")
        api = init_rq()
        
        # We save directly to DB
        export_all_instruments(
            output_dir=None,
            save_to_db=True,
            api=api,
        )
        logger.info("RiceQuant instruments exported successfully")
    except Exception as e:
        logger.error(f"Failed to export RiceQuant instruments: {e}")

if __name__ == "__main__":
    run_instrument_export()
