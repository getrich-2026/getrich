import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from Data.clickhouse.etl.extract import read_day_bar_from_local
from Data.clickhouse.table.load import ClickHouseLoader
from lntools.utils.log import Logger


class MinBarImportJob:
    """
    用于导入分钟 K 线数据的任务。
    """

    def __init__(self, hdb_base_path: str, clickhouse_config: dict, max_workers: int = 4):
        """
        初始化 MinBarImportJob。

        Args:
            hdb_base_path (str): HDB 数据文件的根目录。
            clickhouse_config (dict): ClickHouse 连接配置。
            max_workers (int): 并行处理的最大工作线程数。
        """
        self.hdb_base_path = hdb_base_path
        self.clickhouse_config = clickhouse_config
        self.max_workers = max_workers
        self.logger = Logger(module_name=__name__)

    def _process_single_day(self, date_to_process: datetime):
        """
        处理单日的数据导入。

        Args:
            date_to_process (datetime): 要处理的日期。
        """
        year = date_to_process.year
        # HDB 文件路径通常是 bar/min_bar_YYYYMMDD
        db_path = os.path.join(self.hdb_base_path, 'bar')
        
        self.logger.info(f"[{date_to_process.strftime('%Y-%m-%d')}] 开始处理...")

        try:
            # 1. 从 HDB 读取数据
            min_bar_df, code_info_df = read_day_bar_from_local(
                db_path=db_path,
                year=year, # 注意：read_day_bar_from_local 目前按年读取，这里需要调整或按天读取
                symbols=["*"]
            )
            
            # 筛选出当天的数据
            trading_day_int = int(date_to_process.strftime('%Y%m%d'))
            min_bar_df = min_bar_df[min_bar_df['trading_day'] == trading_day_int]

            if min_bar_df.empty and code_info_df.empty:
                self.logger.info(f"[{date_to_process.strftime('%Y-%m-%d')}] 未找到数据，跳过。")
                return

            # 2. 导入到 ClickHouse
            loader = ClickHouseLoader(**self.clickhouse_config)
            if not min_bar_df.empty:
                loader.bulk_insert('min_bar', min_bar_df)
            if not code_info_df.empty:
                # 对于 code_info，我们可能只想在它有变化时才插入
                # 这里的示例是每次都插入，依赖 ReplacingMergeTree 去重
                loader.bulk_insert('code_info', code_info_df)
            loader.close()
            
            self.logger.info(f"[{date_to_process.strftime('%Y-%m-%d')}] 处理完成。")

        except FileNotFoundError:
            self.logger.warning(f"[{date_to_process.strftime('%Y-%m-%d')}] HDB 文件未找到，跳过。")
        except Exception as e:
            self.logger.error(f"[{date_to_process.strftime('%Y-%m-%d')}] 处理失败: {e}")

    def run(self, start_date: str, end_date: str):
        """
        在指定的日期范围内并行执行导入任务。

        Args:
            start_date (str): 开始日期 (格式: YYYY-MM-DD)。
            end_date (str): 结束日期 (格式: YYYY-MM-DD)。
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        dates_to_process = [start + timedelta(days=i) for i in range((end - start).days + 1)]

        self.logger.info(f"开始执行导入任务，日期范围: {start_date} 到 {end_date}，共 {len(dates_to_process)} 天。")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._process_single_day, date) for date in dates_to_process]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"一个工作线程出现严重错误: {e}")

        self.logger.info("所有日期的导入任务已完成。")


if __name__ == '__main__':
    # 任务使用示例
    main_logger = Logger(module_name='daily_import_main')
    
    # 1. HDB 数据路径
    HDB_PATH = "E:\\BaiduNetdiskDownload\\data" # 指向包含 bar/ 目录的根路径

    # 2. ClickHouse 连接配置
    # 确保您的 ClickHouse 服务正在运行
    CLICKHOUSE_CONF = {
        'host': 'localhost',
        'port': 8123,
        'database': 'getrich',
        # 'user': 'your_user', # 如果需要用户名
        # 'password': 'your_password' # 如果需要密码
    }

    # 3. 初始化并运行任务
    # 假设我们要导入 2005 年 1 月份的数据
    importer_job = MinBarImportJob(
        hdb_base_path=HDB_PATH,
        clickhouse_config=CLICKHOUSE_CONF,
        max_workers=4  # 根据您的 CPU 核心数和 IO 能力调整
    )
    
    importer_job.run(start_date='2005-01-01', end_date='2005-01-31')
