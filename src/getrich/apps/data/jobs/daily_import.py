from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from lntools.utils import Logger

from getrich.libs.clickhouse import ClickHouseClient, ClickHouseConnectionPool

from ..etl.import_hdb import process_hdb_df, read_min_bar_from_local, symbol_cache
from ..table import MinBarTable


class DataImportJob:
    """
    数据导入任务，支持 MinBar、DayBar 的全量和增量导入。

    功能：
    - 分钟线数据导入 (MinBar): 一天一个文件，存放在 hdb_base_path/min_bar/ 下
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
                - MinBar 数据存放在: hdb_base_path/min_bar/min_bar_yyyymmdd
            client (Optional[ClickHouseClient]): ClickHouse 客户端实例（与 pool、clickhouse_config 互斥）
            pool (Optional[ClickHouseConnectionPool]): ClickHouse 连接池实例（与 client、clickhouse_config 互斥，优先级最高）
            clickhouse_config (Optional[dict]): ClickHouse 连接配置字典（当 client 和 pool 都为 None 时使用）
            max_workers (int): 并行处理的最大工作线程数
        """
        self.hdb_base_path = Path(hdb_base_path)
        self.min_bar_path = self.hdb_base_path / "min_bar"
        self.max_workers = max_workers
        self.logger = Logger(module_name="DataImportJob")
        self.known_symbols = set()  # To track what we've already loaded/saved

        self._pool = None
        self._client = None

        # Mode 1: Using connection pool (highest priority)
        if pool is not None:
            self.min_bar_table = MinBarTable(pool=pool)
            self._pool = pool

        # Mode 2: Using client instance
        elif client is not None:
            self.min_bar_table = MinBarTable(client=client)
            self._client = client

        # Mode 3: Using configuration dict to create new client
        elif clickhouse_config is not None:
            self.min_bar_table = MinBarTable(**clickhouse_config)
            self._client = ClickHouseClient(**clickhouse_config)

        # Mode 4: Using default configuration
        else:
            self.min_bar_table = MinBarTable()
            self._client = ClickHouseClient()

        # Ensure tables are created
        self.min_bar_table.create(if_not_exists=True)
        self._ensure_mapping_table_exists()

        # Load existing symbol mappings into cache
        self._load_symbol_mappings()

        self.logger.info("DataImportJob initialized successfully")

    @contextmanager
    def _db_connection(self):
        """Context manager to get a DB client (from pool or instance)."""
        if self._pool:
            with self._pool.connection() as client:
                yield client
        else:
            if self._client is None:
                raise RuntimeError("Database client is not initialized")
            yield self._client

    def _ensure_mapping_table_exists(self):
        """Ensure ref.symbol_mapping table exists."""
        try:
            with self._db_connection() as client:
                client.execute("CREATE DATABASE IF NOT EXISTS ref")

                query = """
                CREATE TABLE IF NOT EXISTS ref.symbol_mapping (
                    symbol String COMMENT '标准代码, 如 RB2405',
                    provider LowCardinality(String) COMMENT '数据源标识, 如 hdb, rq, wind',
                    mapped_symbol String COMMENT '数据源对应的代码',
                    update_time DateTime DEFAULT now() COMMENT '更新时间'
                )
                ENGINE = ReplacingMergeTree(update_time)
                ORDER BY (provider, mapped_symbol)
                SETTINGS index_granularity = 8192;
                """
                client.execute(query)
        except Exception as e:
            self.logger.error(f"Failed to ensure symbol mapping table exists: {e}")

    def _load_symbol_mappings(self, provider: str = "gtja"):
        """Load symbol mappings from DB to memory cache."""
        try:
            query = f"""
            SELECT mapped_symbol, symbol
            FROM ref.symbol_mapping
            FINAL
            WHERE provider = '{provider}'
            """

            with self._db_connection() as client:
                df = client.query(query)

            if not df.empty:
                mappings = dict(zip(df["mapped_symbol"], df["symbol"], strict=False))
                symbol_cache.update(mappings)
                self.known_symbols.update(mappings.keys())

        except Exception as e:
            self.logger.error(f"Failed to load symbol mappings: {e}")

    def _sync_new_mappings(self, provider: str = "gtja"):
        """Identify and save new mappings generated during processing."""
        current_keys = set(symbol_cache.keys())
        new_keys = current_keys - self.known_symbols

        if new_keys:
            try:
                new_mappings = {k: symbol_cache[k] for k in new_keys}
                df = pd.DataFrame(
                    [
                        {
                            "symbol": sym,
                            "provider": provider,
                            "mapped_symbol": mapped,
                            "update_time": datetime.now(),
                        }
                        for mapped, sym in new_mappings.items()
                    ]
                )

                with self._db_connection() as client:
                    client.insert_data("ref.symbol_mapping", df)

                self.known_symbols.update(new_keys)
            except Exception as e:
                self.logger.error(f"Failed to sync new symbol mappings: {e}")

    def _get_min_bar_file_path(self, date_to_process: datetime) -> str | None:
        """
        根据日期获取对应的 MinBar HDB 文件路径。

        Args:
            date_to_process: 要处理的日期

        Returns:
            MinBar HDB 文件路径，如果不存在则返回 None
        """
        date_str = date_to_process.strftime("%Y%m%d")
        file_name = f"min_bar_{date_str}"

        # 文件路径格式为 hdb_base_path/min_bar/min_bar_yyyymmdd.hdat 和 .hidx
        hdat_file = self.min_bar_path / f"{file_name}.hdat"
        hidx_file = self.min_bar_path / f"{file_name}.hidx"

        if not hdat_file.exists() or not hidx_file.exists():
            if not hdat_file.exists():
                self.logger.debug(f"MinBar data file not found: {hdat_file}")
            if not hidx_file.exists():
                self.logger.debug(f"MinBar index file not found: {hidx_file}")
            return None

        # 返回不带扩展名的文件路径
        return str(self.min_bar_path / file_name)

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
            # db_path is the directory: min_bar/
            min_bar_df = read_min_bar_from_local(
                db_path=str(self.min_bar_path), trade_date=trade_date, symbols=symbols
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

        try:
            # 1. 检查文件是否存在
            if self._get_min_bar_file_path(date_to_process) is None:
                # _get_min_bar_file_path 已经打印了 debug 日志
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

                # Sync any new symbol mappings found during processing
                self._sync_new_mappings()

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

            if not result.empty and result["max_date"].iloc[0] is not None:
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
            if not result.empty:
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

            if not self.min_bar_path.exists():
                self.logger.error(f"MinBar directory does not exist: {self.min_bar_path}")
                return

            # Find all min_bar_*.hdat files directly under min_bar/
            hdat_files = list(self.min_bar_path.glob("min_bar_*.hdat"))

            for hdat_file in hdat_files:
                # Extract date
                try:
                    date_str = hdat_file.stem.replace("min_bar_", "")
                    file_date = datetime.strptime(date_str, "%Y%m%d")

                    # Filter by year range
                    if not start_year <= file_date.year <= end_year:
                        continue

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
