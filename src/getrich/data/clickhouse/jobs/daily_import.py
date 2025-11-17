from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from lntools import Logger

from getrich.data.clickhouse.etl import (
    read_min_bar_from_local,
    read_day_bar_from_local,
    read_day_bar_from_csv,
    read_day_bar_from_parquet,
)
from getrich.data.clickhouse.table import MinBarTable, DayBarTable, CodeInfoTable
from getrich.data.clickhouse.database import ClickHouseClient
from getrich.data.clickhouse.pool import ClickHouseConnectionPool


class DataImportJob:
    """
    数据导入任务，支持 MinBar、DayBar、CodeInfo 的全量和增量导入。

    功能：
    - 分钟线数据导入 (MinBar): 一天一个文件，存放在 hdb_base_path/min_bar/year/ 下
    - 日线数据导入 (DayBar): 一年一个文件，存放在 hdb_base_path/day_bar/ 下
    - 合约信息导入 (CodeInfo): 读取 MinBar 文件时同步更新
    - 支持全量/增量导入
    - 支持并发处理

    初始化方式：
        方式1 - 使用客户端实例（推荐，共享连接）：
            client = ClickHouseClient()
            job = DataImportJob(hdb_base_path='...', client=client)

        方式2 - 使用连接池（高并发场景）：
            pool = ClickHouseConnectionPool(min_size=2, max_size=10)
            job = DataImportJob(hdb_base_path='...', pool=pool)

        方式3 - 传入配置字典（自动创建客户端）：
            config = {'host': 'localhost', 'port': 9000, 'database': 'default'}
            job = DataImportJob(hdb_base_path='...', clickhouse_config=config)

        方式4 - 使用默认配置：
            job = DataImportJob(hdb_base_path='...')
    """

    def __init__(
        self,
        hdb_base_path: str,
        client: Optional[ClickHouseClient] = None,
        pool: Optional[ClickHouseConnectionPool] = None,
        clickhouse_config: Optional[dict] = None,
        max_workers: int = 4
    ):
        """
        初始化 DataImportJob。

        Args:
            hdb_base_path (str): HDB 数据文件的根目录
                - MinBar 数据存放在: hdb_base_path/min_bar/year/min_bar_yyyymmdd
                - DayBar 数据存放在: hdb_base_path/day_bar/day_bar_yyyy
            client (Optional[ClickHouseClient]): ClickHouse 客户端实例（与 pool、clickhouse_config 互斥）
            pool (Optional[ClickHouseConnectionPool]): ClickHouse 连接池实例（与 client、clickhouse_config 互斥，优先级最高）
            clickhouse_config (Optional[dict]): ClickHouse 连接配置字典（当 client 和 pool 都为 None 时使用）
            max_workers (int): 并行处理的最大工作线程数
        """
        self.hdb_base_path = Path(hdb_base_path)
        self.min_bar_path = self.hdb_base_path / "min_bar"
        self.day_bar_path = self.hdb_base_path / "day_bar"
        self.max_workers = max_workers
        self.logger = Logger(module_name="DataImportJob")

        # Initialize table instances - supports 3 modes
        # Mode 1: Using connection pool (highest priority)
        if pool is not None:
            self.logger.info("Using connection pool for table initialization")
            self.min_bar_table = MinBarTable(pool=pool)
            self.day_bar_table = DayBarTable(pool=pool)
            self.code_info_table = CodeInfoTable(pool=pool)

        # Mode 2: Using client instance
        elif client is not None:
            self.logger.info("Using provided ClickHouse client for table initialization")
            self.min_bar_table = MinBarTable(client=client)
            self.day_bar_table = DayBarTable(client=client)
            self.code_info_table = CodeInfoTable(client=client)

        # Mode 3: Using configuration dict to create new client
        elif clickhouse_config is not None:
            self.logger.info("Creating tables with provided configuration")
            self.min_bar_table = MinBarTable(**clickhouse_config)
            self.day_bar_table = DayBarTable(**clickhouse_config)
            self.code_info_table = CodeInfoTable(**clickhouse_config)

        # Mode 4: Using default configuration
        else:
            self.logger.info("Creating tables with default configuration")
            self.min_bar_table = MinBarTable()
            self.day_bar_table = DayBarTable()
            self.code_info_table = CodeInfoTable()

        # Ensure tables are created
        self.min_bar_table.create(if_not_exists=True)
        self.day_bar_table.create(if_not_exists=True)
        self.code_info_table.create(if_not_exists=True)

        self.logger.info("DataImportJob initialized successfully")
        self.logger.info(f"MinBar data path: {self.min_bar_path}")
        self.logger.info(f"DayBar data path: {self.day_bar_path}")

    def _get_min_bar_file_path(self, date_to_process: datetime) -> Optional[str]:
        """
        根据日期获取对应的 MinBar HDB 文件路径。

        Args:
            date_to_process: 要处理的日期

        Returns:
            MinBar HDB 文件路径，如果不存在则返回 None
        """
        year = date_to_process.year
        date_str = date_to_process.strftime('%Y%m%d')
        file_name = f"min_bar_{date_str}"

        # 文件路径格式为 hdb_base_path/min_bar/year/min_bar_yyyymmdd.hdat 和 .hidx
        year_path = self.min_bar_path / str(year)
        hdat_file = year_path / f"{file_name}.hdat"
        hidx_file = year_path / f"{file_name}.hidx"

        if not hdat_file.exists() or not hidx_file.exists():
            if not hdat_file.exists():
                self.logger.debug(f"MinBar data file not found: {hdat_file}")
            if not hidx_file.exists():
                self.logger.debug(f"MinBar index file not found: {hidx_file}")
            return None

        # 返回不带扩展名的文件路径
        return str(year_path / file_name)

    def _process_single_file(
        self, trade_date: datetime, symbols: Optional[list[str]] = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Process single HDB file data reading.

        Args:
            trade_date: Trading date to process
            symbols: List of symbol codes to read, None means read all

        Returns:
            (min_bar_df, code_info_df) tuple
        """
        if symbols is None:
            symbols = []

        try:
            # Read data from HDB file
            # db_path is the year directory: min_bar/year/
            year = trade_date.year
            year_path = self.min_bar_path / str(year)

            min_bar_df, code_info_df = read_min_bar_from_local(
                db_path=str(year_path),
                trade_date=trade_date,
                symbols=symbols
            )

            return min_bar_df, code_info_df

        except Exception as e:
            self.logger.error(f"Failed to read data for {trade_date.strftime('%Y-%m-%d')}: {e}")
            return pd.DataFrame(), pd.DataFrame()

    def _process_day_bar_year(self, year: int, symbols: Optional[list[str]] = None) -> bool:
        """
        Process day bar data import for specified year.

        Args:
            year: Year to process
            symbols: List of symbol codes to import, None means all symbols

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Processing day bar data for year {year}...")

        try:
            # Read day bar data from HDB
            day_bar_df = read_day_bar_from_local(
                db_path=str(self.day_bar_path),
                year=year,
                symbols=symbols
            )

            if day_bar_df.empty:
                self.logger.info(f"No day bar data found for year {year}, skipping.")
                return False

            # Import day bar data to ClickHouse
            success = self.day_bar_table.insert(day_bar_df)
            if success:
                self.logger.info(f"Successfully imported {len(day_bar_df)} day bar records for year {year}.")
                return True
            else:
                self.logger.error(f"Failed to import day bar data for year {year}.")
                return False

        except FileNotFoundError as e:
            self.logger.warning(f"Day bar file not found for year {year}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to process day bar data for year {year}: {e}")
            return False

    def _process_day_bar_incremental(self, year: int, symbols: Optional[list[str]] = None) -> bool:
        """
        Incrementally update day bar data for specified year (read latest records).

        Args:
            year: Year to process
            symbols: List of symbol codes to import, None means all symbols

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Starting incremental update for day bar data of year {year}...")

        try:
            # 1. Get the latest date in database for this year
            query = f"""
                SELECT max(toDate(local_time)) as max_date
                FROM {self.day_bar_table.table_name}
                WHERE toYear(local_time) = {year}
            """
            result = self.day_bar_table.query(query)

            latest_date_in_db = None
            if result is not None and not result.empty and result['max_date'].iloc[0] is not None:
                latest_date_in_db = pd.to_datetime(result['max_date'].iloc[0])
                self.logger.info(f"Latest date in database for year {year}: {latest_date_in_db.strftime('%Y-%m-%d')}")

            # 2. Read all day bar data for this year from HDB
            day_bar_df = read_day_bar_from_local(
                db_path=str(self.day_bar_path),
                year=year,
                symbols=symbols
            )

            if day_bar_df.empty:
                self.logger.info(f"No day bar data found for year {year}, skipping.")
                return False

            # 3. Filter out records that are not in database
            if latest_date_in_db is not None:
                day_bar_df = day_bar_df[day_bar_df['local_time'] > latest_date_in_db]

            if day_bar_df.empty:
                self.logger.info(f"No new day bar data to import for year {year}.")
                return True

            # 4. Import new data to ClickHouse
            success = self.day_bar_table.insert(day_bar_df)
            if success:
                record_count = len(day_bar_df)
                self.logger.info(f"Successfully imported {record_count} incremental day bar records for year {year}.")
                return True
            else:
                self.logger.error(f"Failed to incrementally import day bar data for year {year}.")
                return False

        except Exception as e:
            self.logger.error(f"Failed to incrementally update day bar data for year {year}: {e}")
            return False

    def _process_day_bar_csv(self, date: datetime | str | int) -> bool:
        """
        Process day bar data import from CSV file for specified date.

        Args:
            date: Date to process, supports datetime, string (e.g., "2024-01-01"), or int (e.g., 20240101)

        Returns:
            True if successful, False otherwise
        """
        # Convert to string format for logging
        if isinstance(date, datetime):
            date_str = date.strftime('%Y-%m-%d')
        elif isinstance(date, int):
            date_obj = datetime.strptime(str(date), "%Y%m%d")
            date_str = date_obj.strftime('%Y-%m-%d')
        else:
            date_str = str(date).replace("-", "")
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            date_str = date_obj.strftime('%Y-%m-%d')

        self.logger.info(f"Processing day bar CSV data for date {date_str}...")

        try:
            # Read day bar data from CSV
            day_bar_df = read_day_bar_from_csv(
                csv_path=str(self.day_bar_path),
                date=date
            )

            if day_bar_df.empty:
                self.logger.info(f"No day bar data found for date {date_str}, skipping.")
                return False

            # Import day bar data to ClickHouse
            success = self.day_bar_table.insert(day_bar_df)
            if success:
                self.logger.info(f"Successfully imported {len(day_bar_df)} day bar records for date {date_str}.")
                return True
            else:
                self.logger.error(f"Failed to import day bar data for date {date_str}.")
                return False

        except FileNotFoundError as e:
            self.logger.warning(f"Day bar CSV file not found for date {date_str}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to process day bar CSV data for date {date_str}: {e}")
            return False

    def _process_day_bar_parquet(self, date: datetime | str | int) -> bool:
        """
        Process day bar data import from Parquet file for specified date.

        Args:
            date: Date to process, supports datetime, string (e.g., "2024-01-01"), or int (e.g., 20240101)

        Returns:
            True if successful, False otherwise
        """
        # Convert to string format for logging
        if isinstance(date, datetime):
            date_str = date.strftime('%Y-%m-%d')
        elif isinstance(date, int):
            date_obj = datetime.strptime(str(date), "%Y%m%d")
            date_str = date_obj.strftime('%Y-%m-%d')
        else:
            date_str = str(date).replace("-", "")
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            date_str = date_obj.strftime('%Y-%m-%d')

        self.logger.info(f"Processing day bar Parquet data for date {date_str}...")

        try:
            # Read day bar data from Parquet
            day_bar_df = read_day_bar_from_parquet(
                parquet_path=str(self.day_bar_path),
                date=date
            )

            if day_bar_df.empty:
                self.logger.info(f"No day bar data found for date {date_str}, skipping.")
                return False

            # Import day bar data to ClickHouse
            success = self.day_bar_table.insert(day_bar_df)
            if success:
                self.logger.info(f"Successfully imported {len(day_bar_df)} day bar records for date {date_str}.")
                return True
            else:
                self.logger.error(f"Failed to import day bar data for date {date_str}.")
                return False

        except FileNotFoundError as e:
            self.logger.warning(f"Day bar Parquet file not found for date {date_str}: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to process day bar Parquet data for date {date_str}: {e}")
            return False

    def _process_single_day(
        self,
        date_to_process: datetime,
        symbols: Optional[list[str]] = None,
        import_min_bar: bool = True,
        import_code_info: bool = True
    ):
        """
        Process MinBar and CodeInfo data import for a single day.

        Note: DayBar data uses independent yearly processing method.

        Args:
            date_to_process: Date to process
            symbols: List of symbol codes to import, None means all symbols
            import_min_bar: Whether to import minute bar data
            import_code_info: Whether to import contract info
        """
        date_str = date_to_process.strftime('%Y-%m-%d')
        year = date_to_process.year

        self.logger.info(f"[{date_str}] Processing MinBar...")

        try:
            # 1. Check if MinBar HDB file exists
            year_path = self.min_bar_path / str(year)

            if not year_path.exists():
                self.logger.warning(f"[{date_str}] MinBar year directory does not exist: {year_path}")
                return

            # 2. Read MinBar and CodeInfo data from HDB
            min_bar_df, code_info_df = self._process_single_file(
                date_to_process,
                symbols=symbols
            )

            if min_bar_df.empty and code_info_df.empty:
                self.logger.info(f"[{date_str}] No data found, skipping.")
                return

            # 3. Import minute bar data to ClickHouse
            if import_min_bar and not min_bar_df.empty:
                success = self.min_bar_table.insert(min_bar_df)
                if success:
                    self.logger.info(f"[{date_str}] Successfully imported {len(min_bar_df)} minute bar records.")
                else:
                    self.logger.error(f"[{date_str}] Failed to import minute bar data.")

            # 4. Import contract info to ClickHouse
            if import_code_info and not code_info_df.empty:
                success = self.code_info_table.insert(code_info_df)
                if success:
                    self.logger.info(f"[{date_str}] Successfully imported {len(code_info_df)} contract info records.")
                else:
                    self.logger.error(f"[{date_str}] Failed to import contract info.")

        except FileNotFoundError as e:
            self.logger.warning(f"[{date_str}] HDB file not found: {e}")
        except Exception as e:
            self.logger.error(f"[{date_str}] Processing failed: {e}")

    def get_latest_date_in_db(self) -> Optional[datetime]:
        """
        Get the latest data date in database.

        Returns:
            Latest date, or None if table is empty
        """
        try:
            query = f"""
                SELECT max(toDate(local_time)) as max_date
                FROM {self.min_bar_table.table_name}
            """
            result = self.min_bar_table.query(query)

            if result is not None and not result.empty and result['max_date'].iloc[0] is not None:
                max_date = pd.to_datetime(result['max_date'].iloc[0])
                self.logger.info(f"Latest date in database: {max_date.strftime('%Y-%m-%d')}")
                return max_date

            self.logger.info("Database is empty, no latest date")
            return None

        except Exception as e:
            self.logger.error(f"Failed to query latest date: {e}")
            return None

    def run_full_import(
        self,
        start_year: int = 2005,
        end_year: int = 2025,
        symbols: Optional[list[str]] = None,
        skip_existing: bool = True,
        import_min_bar: bool = True,
        import_day_bar: bool = True,
        import_code_info: bool = True
    ):
        """
        全量导入：导入指定年份范围内的所有数据。

        Args:
            start_year: 开始年份
            end_year: 结束年份
            symbols: 要导入的标的代码列表, None 表示所有标的
            skip_existing: 是否跳过数据库中已存在的日期（仅对 MinBar 有效）
            import_min_bar: 是否导入分钟线数据（按日导入）
            import_day_bar: 是否导入日线数据（按年导入）
            import_code_info: 是否导入合约信息（随 MinBar 一起导入）
        """
        self.logger.info("=" * 80)
        self.logger.info(f"Starting full import: {start_year} - {end_year}")
        options_msg = f"Import options: MinBar={import_min_bar}, DayBar={import_day_bar}, CodeInfo={import_code_info}"
        self.logger.info(options_msg)
        self.logger.info("=" * 80)

        # ========== 1. Import DayBar data (by year) ==========
        if import_day_bar:
            self.logger.info("\n" + "=" * 80)
            self.logger.info("Starting day bar data import...")
            self.logger.info("=" * 80)

            day_bar_success = 0
            day_bar_fail = 0

            for year in range(start_year, end_year + 1):
                try:
                    if self._process_day_bar_year(year, symbols):
                        day_bar_success += 1
                    else:
                        day_bar_fail += 1
                except Exception as e:
                    day_bar_fail += 1
                    self.logger.error(f"Failed to import day bar data for year {year}: {e}")

            self.logger.info("=" * 80)
            result_msg = f"Day bar import completed! Success: {day_bar_success} years, Failed: {day_bar_fail} years"
            self.logger.info(result_msg)
            self.logger.info("=" * 80)

        # ========== 2. Import MinBar and CodeInfo data (by day) ==========
        if import_min_bar or import_code_info:
            self.logger.info("\n" + "=" * 80)
            self.logger.info("Starting minute bar (MinBar) and contract info (CodeInfo) import...")
            self.logger.info("=" * 80)

            # Get the latest date already in database
            latest_date = None
            if skip_existing and import_min_bar:
                latest_date = self.get_latest_date_in_db()

            # Collect all MinBar files that need to be processed
            files_to_process = []

            for year in range(start_year, end_year + 1):
                year_path = self.min_bar_path / str(year)

                if not year_path.exists():
                    self.logger.warning(f"MinBar year directory does not exist: {year_path}")
                    continue

                # Find all min_bar_*.hdat files under this year
                hdat_files = list(year_path.glob("min_bar_*.hdat"))

                for hdat_file in hdat_files:
                    # Extract date
                    try:
                        date_str = hdat_file.stem.replace("min_bar_", "")
                        file_date = datetime.strptime(date_str, "%Y%m%d")

                        # Skip existing data if needed
                        if skip_existing and latest_date and file_date <= latest_date:
                            self.logger.debug(f"Skipping existing date: {file_date.strftime('%Y-%m-%d')}")
                            continue

                        files_to_process.append(file_date)

                    except ValueError:
                        self.logger.warning(f"Cannot parse date from filename: {hdat_file.name}")
                        continue

            if not files_to_process:
                self.logger.info("No MinBar files need to be imported")
            else:
                files_to_process.sort()  # Sort by date

                self.logger.info(f"Found {len(files_to_process)} MinBar files to import")
                start_date = files_to_process[0].strftime('%Y-%m-%d')
                end_date = files_to_process[-1].strftime('%Y-%m-%d')
                self.logger.info(f"Date range: {start_date} to {end_date}")

                # Parallel processing
                min_bar_success = 0
                min_bar_fail = 0

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(
                            self._process_single_day,
                            date,
                            symbols,
                            import_min_bar,
                            import_code_info
                        ): date
                        for date in files_to_process
                    }

                    for future in as_completed(futures):
                        date = futures[future]
                        try:
                            future.result()
                            min_bar_success += 1
                        except Exception as e:
                            min_bar_fail += 1
                            self.logger.error(f"Failed to process date {date.strftime('%Y-%m-%d')}: {e}")

                self.logger.info("=" * 80)
                result_msg = f"Minute bar import completed! Success: {min_bar_success}, Failed: {min_bar_fail}"
                self.logger.info(result_msg)
                self.logger.info("=" * 80)

        self.logger.info("\n" + "=" * 80)
        self.logger.info("Full import task completed!")
        self.logger.info("=" * 80)

    def run_incremental_import(
        self,
        target_date: Optional[datetime] = None,
        symbols: Optional[list[str]] = None,
        import_min_bar: bool = True,
        import_day_bar: bool = True,
        import_code_info: bool = True
    ):
        """
        增量导入：导入最新的数据。
        - MinBar: 导入指定日期或数据库最新日期之后的所有日期的数据
        - DayBar: 读取当前年份文件，导入数据库中没有的最新记录

        Args:
            target_date: 目标日期, None 表示导入最新日期之后的所有数据
            symbols: 要导入的标的代码列表, None 表示所有标的
            import_min_bar: 是否导入分钟线数据
            import_day_bar: 是否导入日线数据
            import_code_info: 是否导入合约信息（随 MinBar 一起导入）
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting incremental import")
        options_msg = f"Import options: MinBar={import_min_bar}, DayBar={import_day_bar}, CodeInfo={import_code_info}"
        self.logger.info(options_msg)
        self.logger.info("=" * 80)

        current_year = datetime.now().year

        # ========== 1. Incrementally import DayBar data (current year) ==========
        if import_day_bar:
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"Starting incremental import for day bar data of year {current_year}...")
            self.logger.info("=" * 80)

            try:
                self._process_day_bar_incremental(current_year, symbols)
            except Exception as e:
                self.logger.error(f"Failed to incrementally import day bar data for year {current_year}: {e}")

            self.logger.info("=" * 80)
            self.logger.info("Day bar incremental import completed!")
            self.logger.info("=" * 80)

        # ========== 2. Incrementally import MinBar and CodeInfo data ==========
        if import_min_bar or import_code_info:
            self.logger.info("\n" + "=" * 80)
            self.logger.info("Starting incremental import for minute bar (MinBar) and contract info (CodeInfo)...")
            self.logger.info("=" * 80)

            if target_date is None:
                # Get the latest date in database
                latest_date = self.get_latest_date_in_db()

                if latest_date is None:
                    self.logger.warning("MinBar database is empty, please run full import first")
                    return

                # Import starting from the day after the latest date
                start_date = latest_date + timedelta(days=1)
                end_date = datetime.now()

                self.logger.info(f"Latest date in MinBar database: {latest_date.strftime('%Y-%m-%d')}")
                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')
                self.logger.info(f"Will import data from {start_str} to {end_str}")

                # Generate date list
                dates_to_process = []
                current = start_date
                while current <= end_date:
                    dates_to_process.append(current)
                    current += timedelta(days=1)
            else:
                # Import specified date
                dates_to_process = [target_date]
                self.logger.info(f"Will import specified date: {target_date.strftime('%Y-%m-%d')}")

            if not dates_to_process:
                self.logger.info("No MinBar data needs to be imported")
            else:
                # Parallel processing
                min_bar_success = 0
                min_bar_fail = 0

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(
                            self._process_single_day,
                            date,
                            symbols,
                            import_min_bar,
                            import_code_info
                        ): date
                        for date in dates_to_process
                    }

                    for future in as_completed(futures):
                        date = futures[future]
                        try:
                            future.result()
                            min_bar_success += 1
                        except Exception as e:
                            min_bar_fail += 1
                            self.logger.error(f"Failed to process date {date.strftime('%Y-%m-%d')}: {e}")

                self.logger.info("=" * 80)
                msg = f"Minute bar incremental import completed! Success: {min_bar_success}, Failed: {min_bar_fail}"
                self.logger.info(msg)
                self.logger.info("=" * 80)

        self.logger.info("\n" + "=" * 80)
        self.logger.info("Incremental import task completed!")
        self.logger.info("=" * 80)

    def run_csv_import(
        self,
        start_date: datetime | str | int,
        end_date: Optional[datetime | str | int] = None
    ):
        """
        Import day bar data from CSV files for specified date range.

        Args:
            start_date: Start date, supports datetime, string, or int format
            end_date: End date, None means only import start_date
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting CSV import for day bar data")
        self.logger.info("=" * 80)

        # Convert dates to datetime objects
        if isinstance(start_date, datetime):
            start_dt = start_date
        elif isinstance(start_date, int):
            start_dt = datetime.strptime(str(start_date), "%Y%m%d")
        else:
            date_str = str(start_date).replace("-", "")
            start_dt = datetime.strptime(date_str, "%Y%m%d")

        if end_date is None:
            dates_to_process = [start_dt]
        else:
            if isinstance(end_date, datetime):
                end_dt = end_date
            elif isinstance(end_date, int):
                end_dt = datetime.strptime(str(end_date), "%Y%m%d")
            else:
                date_str = str(end_date).replace("-", "")
                end_dt = datetime.strptime(date_str, "%Y%m%d")

            # Generate date list
            dates_to_process = []
            current = start_dt
            while current <= end_dt:
                dates_to_process.append(current)
                current += timedelta(days=1)

        self.logger.info(f"Will process {len(dates_to_process)} CSV files")

        success_count = 0
        fail_count = 0

        for date in dates_to_process:
            try:
                if self._process_day_bar_csv(date):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                self.logger.error(f"Failed to import CSV for date {date.strftime('%Y-%m-%d')}: {e}")

        self.logger.info("=" * 80)
        self.logger.info(f"CSV import completed! Success: {success_count}, Failed: {fail_count}")
        self.logger.info("=" * 80)

    def run_parquet_import(
        self,
        start_date: datetime | str | int,
        end_date: Optional[datetime | str | int] = None
    ):
        """
        Import day bar data from Parquet files for specified date range.

        Args:
            start_date: Start date, supports datetime, string, or int format
            end_date: End date, None means only import start_date
        """
        self.logger.info("=" * 80)
        self.logger.info("Starting Parquet import for day bar data")
        self.logger.info("=" * 80)

        # Convert dates to datetime objects
        if isinstance(start_date, datetime):
            start_dt = start_date
        elif isinstance(start_date, int):
            start_dt = datetime.strptime(str(start_date), "%Y%m%d")
        else:
            date_str = str(start_date).replace("-", "")
            start_dt = datetime.strptime(date_str, "%Y%m%d")

        if end_date is None:
            dates_to_process = [start_dt]
        else:
            if isinstance(end_date, datetime):
                end_dt = end_date
            elif isinstance(end_date, int):
                end_dt = datetime.strptime(str(end_date), "%Y%m%d")
            else:
                date_str = str(end_date).replace("-", "")
                end_dt = datetime.strptime(date_str, "%Y%m%d")

            # Generate date list
            dates_to_process = []
            current = start_dt
            while current <= end_dt:
                dates_to_process.append(current)
                current += timedelta(days=1)

        self.logger.info(f"Will process {len(dates_to_process)} Parquet files")

        success_count = 0
        fail_count = 0

        for date in dates_to_process:
            try:
                if self._process_day_bar_parquet(date):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                self.logger.error(f"Failed to import Parquet for date {date.strftime('%Y-%m-%d')}: {e}")

        self.logger.info("=" * 80)
        self.logger.info(f"Parquet import completed! Success: {success_count}, Failed: {fail_count}")
        self.logger.info("=" * 80)

    def close(self):
        """Close database connections"""
        if hasattr(self, 'min_bar_table'):
            self.min_bar_table.close()
        if hasattr(self, 'day_bar_table'):
            self.day_bar_table.close()
        if hasattr(self, 'code_info_table'):
            self.code_info_table.close()
        self.logger.info("Database connections closed")


if __name__ == '__main__':
    # Task usage examples
    main_logger = Logger(module_name='data_import_main')

    # 1. HDB data path configuration
    # HDB_BASE_PATH is the root directory of data
    # Directory structure should be:
    #   - HDB_BASE_PATH/min_bar/2005/min_bar_20050101.hdat, min_bar_20050101.hidx, ...
    #   - HDB_BASE_PATH/min_bar/2006/...
    #   - HDB_BASE_PATH/day_bar/day_bar_2005.hdat, day_bar_2005.hidx
    #   - HDB_BASE_PATH/day_bar/day_bar_2006.hdat, ...
    HDB_BASE_PATH = r"E:\data\bar"

    try:
        # ========== Initialization Examples ==========

        # Method 1: Use default configuration (simplest)
        # importer_job = DataImportJob(
        #     hdb_base_path=HDB_BASE_PATH,
        #     max_workers=4  # Adjust based on your CPU cores and IO capability
        # )

        # Method 2: Use configuration dict
        # clickhouse_config = {
        #     'host': 'localhost',
        #     'port': 9000,
        #     'user': 'default',
        #     'password': '',
        #     'database': 'default'
        # }
        # importer_job = DataImportJob(
        #     hdb_base_path=HDB_BASE_PATH,
        #     clickhouse_config=clickhouse_config,
        #     max_workers=4
        # )

        # Method 3: Use client instance (recommended, shared connection across tables)
        client = ClickHouseClient()
        importer_job = DataImportJob(
            hdb_base_path=HDB_BASE_PATH,
            client=client,
            max_workers=4
        )

        # Method 4: Use connection pool (high concurrency scenario)
        # from ..pool import ClickHouseConnectionPool
        # pool = ClickHouseConnectionPool(
        #     min_size=2,
        #     max_size=10,
        #     host='localhost',
        #     database='default'
        # )
        # importer_job = DataImportJob(
        #     hdb_base_path=HDB_BASE_PATH,
        #     pool=pool,
        #     max_workers=4
        # )

        # ========== Use Case 1: Full Import (Initial Import) ==========
        # Import all data from 2005-2025 (minute bar + day bar + contract info)
        main_logger.info("Starting full import...")
        importer_job.run_full_import(
            start_year=2005,
            end_year=2005,
            symbols=None,  # None means import all symbols, can also specify like ["SH.*", "SZ.*"]
            skip_existing=True,  # Skip existing data (only applies to MinBar)
            import_min_bar=True,  # Import minute bar data
            import_day_bar=False,  # Import day bar data
            import_code_info=True  # Import contract info (imported along with MinBar)
        )

        # ========== Use Case 2: Incremental Import (Daily Update) ==========
        # MinBar: Auto import all dates after latest date in database
        # DayBar: Read current year file (e.g. day_bar_2025), import latest records
        # main_logger.info("Starting incremental import...")
        # importer_job.run_incremental_import(
        #     import_min_bar=True,
        #     import_day_bar=True,
        #     import_code_info=True
        # )

        # ========== Use Case 3: Import MinBar Data for Specific Date ==========
        # target_date = datetime(2025, 11, 3)
        # main_logger.info(f"Importing MinBar for specific date: {target_date.strftime('%Y-%m-%d')}")
        # importer_job.run_incremental_import(
        #     target_date=target_date,
        #     import_min_bar=True,
        #     import_day_bar=False,  # Don't import day bar
        #     import_code_info=True
        # )

        # ========== Use Case 4: Import DayBar Data Only ==========
        # main_logger.info("Importing day bar data only...")
        # importer_job.run_full_import(
        #     start_year=2005,
        #     end_year=2025,
        #     skip_existing=False,
        #     import_min_bar=False,
        #     import_day_bar=True,
        #     import_code_info=False
        # )

        # ========== Use Case 5: Import Contract Info Only ==========
        # main_logger.info("Importing contract info only...")
        # importer_job.run_full_import(
        #     start_year=2005,
        #     end_year=2025,
        #     skip_existing=False,
        #     import_min_bar=False,  # Don't import minute bar data
        #     import_day_bar=False,  # Don't import day bar data
        #     import_code_info=True  # Import contract info only (reads MinBar files but only imports CodeInfo)
        # )

    except Exception as e:
        main_logger.error(f"Import task execution failed: {e}")

    finally:
        # 4. Close database connections
        if 'importer_job' in locals():
            importer_job.close()
            main_logger.info("Import task finished")
