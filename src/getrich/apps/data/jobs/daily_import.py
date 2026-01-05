from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from lntools import Logger

from getrich.libs.clickhouse import ClickHouseClient, ClickHouseConnectionPool

from ..etl.import_hdb import process_hdb_df, read_min_bar_from_local
from ..table import MinBarTable


class DataImportJob:
    """
    数据导入任务，支持 MinBar、DayBar 的全量和增量导入。

    功能：
    - 分钟线数据导入 (MinBar): 一天一个文件，存放在 hdb_base_path/min_bar/year/ 下
    - 日线数据导入 (DayBar): 一年一个文件，存放在 hdb_base_path/day_bar/ 下
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
        client: ClickHouseClient | None = None,
        pool: ClickHouseConnectionPool | None = None,
        clickhouse_config: dict[str, Any] | None = None,
        max_workers: int = 4,
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
        self.max_workers = max_workers
        self.logger = Logger(module_name="DataImportJob")

        # Mode 1: Using connection pool (highest priority)
        if pool is not None:
            self.min_bar_table = MinBarTable(pool=pool)

        # Mode 2: Using client instance
        elif client is not None:
            self.min_bar_table = MinBarTable(client=client)

        # Mode 3: Using configuration dict to create new client
        elif clickhouse_config is not None:
            self.min_bar_table = MinBarTable(**clickhouse_config)

        # Mode 4: Using default configuration
        else:
            self.min_bar_table = MinBarTable()

        # Ensure tables are created
        self.min_bar_table.create(if_not_exists=True)

        self.logger.info("DataImportJob initialized successfully")

    def _get_min_bar_file_path(self, date_to_process: datetime) -> str | None:
        """
        根据日期获取对应的 MinBar HDB 文件路径。

        Args:
            date_to_process: 要处理的日期

        Returns:
            MinBar HDB 文件路径，如果不存在则返回 None
        """
        year = date_to_process.year
        date_str = date_to_process.strftime("%Y%m%d")
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
        self, trade_date: datetime, symbols: list[str] | None = None
    ) -> pd.DataFrame:
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

            min_bar_df = read_min_bar_from_local(
                db_path=str(year_path), trade_date=trade_date, symbols=symbols
            )
            return process_hdb_df(min_bar_df)

        except Exception as e:
            self.logger.error(f"Failed to read data for {trade_date.strftime('%Y-%m-%d')}: {e}")
            return pd.DataFrame()

    def _process_single_day(
        self,
        date_to_process: datetime,
        symbols: list[str] | None = None,
        import_min_bar: bool = True,
    ):
        """
        处理单日的 MinBar 导入。
        """
        date_str = date_to_process.strftime("%Y-%m-%d")
        year = date_to_process.year

        try:
            # 1. 检查目录
            year_path = self.min_bar_path / str(year)
            if not year_path.exists():
                self.logger.warning(
                    f"[{date_str}] MinBar year directory does not exist: {year_path}"
                )
                return

            # 2. 读取数据
            min_bar_df = self._process_single_file(date_to_process, symbols=symbols)

            if min_bar_df.empty:
                self.logger.info(f"[{date_str}] No data found in HDB, skipping.")
                return

            # 3. 导入 ClickHouse
            if import_min_bar:
                success = self.min_bar_table.insert(min_bar_df)
                if not success:
                    # 【关键点】这里必须抛出异常，否则 run_full_import 会认为导入成功
                    raise RuntimeError(f"ClickHouse insert failed for {date_str}")

                self.logger.info(f"[{date_str}] Successfully imported {len(min_bar_df)} records.")

        except Exception as e:
            self.logger.error(f"[{date_str}] Processing failed: {str(e)}")
            raise

    def get_latest_date_in_db(self) -> datetime | None:
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

            if result is not None and not result.empty and result["max_date"].iloc[0] is not None:
                max_date = pd.to_datetime(result["max_date"].iloc[0])
                self.logger.info(f"Latest date in database: {max_date.strftime('%Y-%m-%d')}")
                return max_date

            return None

        except Exception as e:
            self.logger.error(f"Failed to query latest date: {e}")
            return None

    def get_all_existing_dates(self) -> set[datetime]:
        """获取数据库中所有已存在的日期集合"""
        try:
            query = f"SELECT DISTINCT toDate(local_time) as trade_date FROM {self.min_bar_table.table_name}"
            result = self.min_bar_table.query(query)
            if result is not None and not result.empty:
                # 转换为 datetime 对象集合，方便后续比对
                return set(pd.to_datetime(result["trade_date"]).tolist())
            return set()
        except Exception as e:
            self.logger.error(f"Failed to query all existing dates: {e}")
            return set()

    def run_full_import(
        self,
        start_year: int = 2005,
        end_year: int = 2025,
        symbols: list[str] | None = None,
        skip_existing: bool = True,
        skip_mode: Literal["latest", "all"] = "latest",
        import_min_bar: bool = True,
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
        self.logger.info("=" * 80)

        # ========== 2. Import MinBar and CodeInfo data (by day) ==========
        if import_min_bar:
            # Get the latest date or all existing dates already in database
            existing_dates_set = set()
            latest_date = None
            if skip_existing:
                if skip_mode == "all":
                    self.logger.info("Fetching all existing dates from DB...")
                    existing_dates_set = self.get_all_existing_dates()
                    self.logger.info(f"Found {len(existing_dates_set)} existing dates.")
                else:
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
                        if skip_existing:
                            if skip_mode == "all":
                                # 模式1: 只要数据库里有这个日期，就跳过
                                if file_date in existing_dates_set:
                                    continue
                            else:
                                # 模式2: 只导入比最大日期大的文件
                                if latest_date and file_date <= latest_date:
                                    continue

                        files_to_process.append(file_date)

                    except ValueError:
                        self.logger.warning(f"Cannot parse date from filename: {hdat_file.name}")
                        continue

            if not files_to_process:
                self.logger.info("No MinBar files need to be imported")
                return

            files_to_process.sort()  # Sort by date
            self.logger.info(f"Found {len(files_to_process)} MinBar files to import")

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
                    ): date
                    for date in files_to_process
                }

                for future in as_completed(futures):
                    try:
                        future.result()
                        min_bar_success += 1
                    except Exception:
                        min_bar_fail += 1

            self.logger.info("=" * 80)
            self.logger.info(
                f"Minute bar import completed! Success: {min_bar_success}, Failed: {min_bar_fail}"
            )
            self.logger.info("=" * 80)

    def run_incremental_import(
        self, target_date: datetime | None = None, symbols: list[str] | None = None
    ):
        """
        便捷入口：增量导入。
        - 如果指定 target_date，只导入该日期。
        - 如果未指定，自动扫描今年并补录最新数据。
        """
        if target_date:
            self.logger.info(f"Importing specified date: {target_date.strftime('%Y-%m-%d')}")
            self._process_single_day(target_date, symbols)
        else:
            # 默认扫描今年，跳过已存在的（增量模式）
            self.run_full_import(
                start_year=datetime.now().year,
                end_year=datetime.now().year,
                symbols=symbols,
                skip_existing=True,
                skip_mode="latest",
            )
