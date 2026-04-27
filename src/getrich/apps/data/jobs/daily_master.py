from datetime import datetime
from lntools.utils import Logger

from .import_hdb import DataImportJob
from .import_ricequant import run_instrument_export
from .import_wind import import_wind_data_from_parquet

logger = Logger(module_name="DailyMasterJob")

def run_daily_jobs():
    """
    Unified daily master job that orchestrates all data source imports.
    """
    logger.info("=" * 80)
    logger.info(f"Starting unified daily jobs at {datetime.now()}")
    logger.info("=" * 80)

    # 1. Export RiceQuant Instruments (if enabled)
    logger.info("--- Step 1: Exporting RiceQuant Instruments ---")
    try:
        run_instrument_export()
    except Exception as e:
        logger.error(f"Failed in RiceQuant export step: {e}")

    # 2. HDB Import (Day Bar and Min Bar)
    logger.info("--- Step 2: Running HDB Import Jobs ---")
    try:
        # Assuming defaults or configuring via config.py
        hdb_base_path = "D:/data/hdb" # Replace with config value later if needed
        hdb_job = DataImportJob(hdb_base_path=hdb_base_path)
        
        # Incremental min bar import
        logger.info("Running incremental min bar import...")
        hdb_job.run_incremental_import()

        # Incremental day bar import
        current_year = datetime.now().year
        logger.info(f"Running day bar import for {current_year}...")
        hdb_job.run_day_bar_import(start_year=current_year, end_year=current_year)

    except Exception as e:
        logger.error(f"Failed in HDB import step: {e}")

    # 3. Wind Import
    logger.info("--- Step 3: Running Wind Parquet Import ---")
    try:
        import_wind_data_from_parquet()
    except Exception as e:
        logger.error(f"Failed in Wind import step: {e}")
        
    logger.info("=" * 80)
    logger.info("All daily jobs finished.")
    logger.info("=" * 80)

if __name__ == "__main__":
    run_daily_jobs()
