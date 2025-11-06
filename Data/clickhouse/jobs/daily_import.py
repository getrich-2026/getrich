from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from lntools import Logger

from Data.clickhouse.etl.extract import read_min_bar_from_local
from Data.clickhouse.table.bar import MinBarTable


class MinBarImportJob:
    """
    用于导入分钟 K 线数据的任务，支持全量导入和增量导入。
    """

    def __init__(self, hdb_base_path: str, clickhouse_config: dict, max_workers: int = 4):
        """
        初始化 MinBarImportJob。

        Args:
            hdb_base_path (str): HDB 数据文件的根目录，例如: E:\\BaiduNetdiskDownload\\data\\bar\\bar\\min_bar
            clickhouse_config (dict): ClickHouse 连接配置。
            max_workers (int): 并行处理的最大工作线程数。
        """
        self.hdb_base_path = hdb_base_path
        self.clickhouse_config = clickhouse_config
        self.max_workers = max_workers
        self.logger = Logger(module_name="MinBarImportJob")

        # 初始化 MinBarTable 实例
        self.min_bar_table = MinBarTable(**clickhouse_config)

        # 确保表已创建
        self.min_bar_table.create(if_not_exists=True)

    def _get_hdb_file_path(self, date_to_process: datetime) -> Optional[str]:
        """
        根据日期获取对应的 HDB 文件路径。

        Args:
            date_to_process: 要处理的日期

        Returns:
            HDB 文件路径，如果不存在则返回 None
        """
        year = date_to_process.year
        date_str = date_to_process.strftime('%Y%m%d')
        file_name = f"min_bar_{date_str}"

        # 文件路径格式为 hdb_base_path/year/min_bar_yyyymmdd.hdat 和 .hidx
        year_path = Path(self.hdb_base_path) / str(year)
        hdat_file = year_path / f"{file_name}.hdat"
        hidx_file = year_path / f"{file_name}.hidx"

        if not hdat_file.exists() or not hidx_file.exists():
            if not hdat_file.exists():
                self.logger.debug(f"HDB data file not found: {hdat_file}")
            if not hidx_file.exists():
                self.logger.debug(f"HDB index file not found: {hidx_file}")
                return None

        # 返回不带扩展名的文件路径
        return str(year_path / file_name)

    def _process_single_file(
        self, file_path: str, symbols: Optional[list[str]] = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        处理单个 HDB 文件的数据读取。

        Args:
            file_path: HDB 文件路径（不含 .hdat 扩展名）
            symbols: 要读取的标的代码列表, None 表示读取所有

        Returns:
            (min_bar_df, code_info_df) 元组
        """
        if symbols is None:
            symbols = ["*"]

        try:
            # 从 HDB 文件读取数据
            min_bar_df, code_info_df = read_min_bar_from_local(
                db_path=str(Path(file_path).parent.parent),  # 到 min_bar 目录
                file_path=Path(file_path).name,
                symbols=symbols
            )

            # 数据预处理：转换时间格式
            if not min_bar_df.empty and 'local_time' in min_bar_df.columns:
                # 确保 local_time 是 datetime 类型
                if not pd.api.types.is_datetime64_any_dtype(min_bar_df['local_time']):
                    min_bar_df['local_time'] = pd.to_datetime(min_bar_df['local_time'])

            return min_bar_df, code_info_df

        except Exception as e:
            self.logger.error(f"读取文件 {file_path} 失败: {e}")
            return pd.DataFrame(), pd.DataFrame()

    def _process_single_day(self, date_to_process: datetime, symbols: Optional[list[str]] = None):
        """
        处理单日的数据导入。

        Args:
            date_to_process (datetime): 要处理的日期。
            symbols (list[str]): 要导入的标的代码列表，None 表示所有标的。
        """
        date_str = date_to_process.strftime('%Y-%m-%d')
        year = date_to_process.year
        file_date = date_to_process.strftime('%Y%m%d')
        
        self.logger.info(f"[{date_str}] 开始处理...")

        try:
            # 1. 检查 HDB 文件是否存在
            year_path = Path(self.hdb_base_path) / str(year)
            file_name = f"min_bar_{file_date}"
            
            if not year_path.exists():
                self.logger.warning(f"[{date_str}] 年份目录不存在: {year_path}")
                return
            
            # 2. 从 HDB 读取数据
            min_bar_df, code_info_df = self._process_single_file(
                str(year_path / file_name),
                symbols=symbols
            )

            if min_bar_df.empty:
                self.logger.info(f"[{date_str}] 未找到数据，跳过。")
                return

            # 3. 导入到 ClickHouse
            if not min_bar_df.empty:
                success = self.min_bar_table.insert(min_bar_df)
                if success:
                    self.logger.info(f"[{date_str}] 成功导入 {len(min_bar_df)} 条分钟线数据。")
                else:
                    self.logger.error(f"[{date_str}] 数据导入失败。")
            
            # NOTE: code_info 的处理可以根据需要单独实现
            _ = code_info_df  # 暂时未使用
            
        except FileNotFoundError as e:
            self.logger.warning(f"[{date_str}] HDB 文件未找到: {e}")
        except Exception as e:
            self.logger.error(f"[{date_str}] 处理失败: {e}")

    def get_latest_date_in_db(self) -> Optional[datetime]:
        """
        获取数据库中最新的数据日期。
        
        Returns:
            最新日期，如果表为空则返回 None
        """
        try:
            query = f"""
                SELECT max(toDate(local_time)) as max_date
                FROM {self.min_bar_table.table_name}
            """
            result = self.min_bar_table.query(query)
            
            if result is not None and not result.empty and result['max_date'].iloc[0] is not None:
                max_date = pd.to_datetime(result['max_date'].iloc[0])
                self.logger.info(f"数据库中最新日期: {max_date.strftime('%Y-%m-%d')}")
                return max_date
            
            self.logger.info("数据库为空，无最新日期")
            return None
            
        except Exception as e:
            self.logger.error(f"查询最新日期失败: {e}")
            return None
    
    def run_full_import(self, start_year: int = 2005, end_year: int = 2025,
                        symbols: Optional[list[str]] = None, skip_existing: bool = True):
        """
        全量导入：导入指定年份范围内的所有数据。
        
        Args:
            start_year: 开始年份
            end_year: 结束年份
            symbols: 要导入的标的代码列表，None 表示所有标的
            skip_existing: 是否跳过数据库中已存在的日期
        """
        self.logger.info("=" * 80)
        self.logger.info(f"开始全量导入：{start_year} - {end_year} 年")
        self.logger.info("=" * 80)
        
        # 获取数据库中已有的最新日期
        latest_date = None
        if skip_existing:
            latest_date = self.get_latest_date_in_db()
        
        # 收集所有需要处理的文件
        files_to_process = []
        
        for year in range(start_year, end_year + 1):
            year_path = Path(self.hdb_base_path) / str(year)
            
            if not year_path.exists():
                self.logger.warning(f"年份目录不存在: {year_path}")
                continue
            
            # 查找该年份下的所有 min_bar_*.hdat 文件
            hdat_files = list(year_path.glob("min_bar_*.hdat"))
            
            for hdat_file in hdat_files:
                # 提取日期
                try:
                    date_str = hdat_file.stem.replace("min_bar_", "")  # 去掉 min_bar_ 前缀
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                    
                    # 如果需要跳过已存在的数据
                    if skip_existing and latest_date and file_date <= latest_date:
                        self.logger.debug(f"跳过已存在的日期: {file_date.strftime('%Y-%m-%d')}")
                        continue
                    
                    files_to_process.append(file_date)
                    
                except ValueError:
                    self.logger.warning(f"无法解析文件名中的日期: {hdat_file.name}")
                    continue
        
        if not files_to_process:
            self.logger.info("没有需要导入的文件")
            return
        
        files_to_process.sort()  # 按日期排序
        
        self.logger.info(f"共找到 {len(files_to_process)} 个文件需要导入")
        start_date = files_to_process[0].strftime('%Y-%m-%d')
        end_date = files_to_process[-1].strftime('%Y-%m-%d')
        self.logger.info(f"日期范围: {start_date} 到 {end_date}")
        
        # 并行处理
        success_count = 0
        fail_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_single_day, date, symbols): date
                for date in files_to_process
            }
            
            for future in as_completed(futures):
                date = futures[future]
                try:
                    future.result()
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    self.logger.error(f"处理日期 {date.strftime('%Y-%m-%d')} 失败: {e}")
        
        self.logger.info("=" * 80)
        self.logger.info(f"全量导入完成！成功: {success_count}, 失败: {fail_count}")
        self.logger.info("=" * 80)
    
    def run_incremental_import(self, target_date: Optional[datetime] = None,
                               symbols: Optional[list[str]] = None):
        """
        增量导入：导入指定日期的数据，如果不指定日期则导入数据库最新日期之后的所有数据。
        
        Args:
            target_date: 目标日期，None 表示导入最新日期之后的所有数据
            symbols: 要导入的标的代码列表，None 表示所有标的
        """
        self.logger.info("=" * 80)
        self.logger.info("开始增量导入")
        self.logger.info("=" * 80)
        
        if target_date is None:
            # 获取数据库中的最新日期
            latest_date = self.get_latest_date_in_db()
            
            if latest_date is None:
                self.logger.warning("数据库为空，请先执行全量导入")
                return
            
            # 从最新日期的下一天开始导入
            start_date = latest_date + timedelta(days=1)
            end_date = datetime.now()
            
            self.logger.info(f"数据库最新日期: {latest_date.strftime('%Y-%m-%d')}")
            self.logger.info(f"将导入 {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')} 的数据")
            
            # 生成日期列表
            dates_to_process = []
            current = start_date
            while current <= end_date:
                dates_to_process.append(current)
                current += timedelta(days=1)
        else:
            # 导入指定日期
            dates_to_process = [target_date]
            self.logger.info(f"将导入指定日期: {target_date.strftime('%Y-%m-%d')}")
        
        if not dates_to_process:
            self.logger.info("没有需要导入的数据")
            return
        
        # 并行处理
        success_count = 0
        fail_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_single_day, date, symbols): date
                for date in dates_to_process
            }

            for future in as_completed(futures):
                date = futures[future]
                try:
                    future.result()
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    self.logger.error(f"处理日期 {date.strftime('%Y-%m-%d')} 失败: {e}")
        
        self.logger.info("=" * 80)
        self.logger.info(f"增量导入完成！成功: {success_count}, 失败: {fail_count}")
        self.logger.info("=" * 80)
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self, 'min_bar_table'):
            self.min_bar_table.close_connection()
            self.logger.info("数据库连接已关闭")


if __name__ == '__main__':
    # 任务使用示例
    main_logger = Logger(module_name='daily_import_main')

    # 1. HDB 数据路径 - 指向 min_bar 目录
    # 该目录下应该有按年份组织的子目录，如 2005/, 2006/, ..., 2025/
    HDB_PATH = r"E:\BaiduNetdiskDownload\data\bar\bar\min_bar"

    # 2. ClickHouse 连接配置
    # 确保您的 ClickHouse 服务正在运行
    CLICKHOUSE_CONF = {
        'host': 'localhost',
        'port': 8123,
        'database': 'default',
        'user': 'default',
        'password': 'getrich',
        'table_name': 'min_bar'
    }

    try:
        # 3. 初始化导入任务
        importer_job = MinBarImportJob(
            hdb_base_path=HDB_PATH,
            clickhouse_config=CLICKHOUSE_CONF,
            max_workers=4  # 根据您的 CPU 核心数和 IO 能力调整
        )

        # 使用场景 1: 全量导入（首次导入）
        # 导入 2005-2025 年的所有数据，跳过已存在的数据
        main_logger.info("开始全量导入...")
        importer_job.run_full_import(
            start_year=2005,
            end_year=2025,
            symbols=None,  # None 表示导入所有标的，也可以指定如 ["SH.*", "SZ.*"]
            skip_existing=True  # 跳过已存在的数据
        )

        # 使用场景 2: 增量导入（日常更新）
        # 自动导入数据库最新日期之后的所有数据
        # main_logger.info("开始增量导入...")
        # importer_job.run_incremental_import()

        # 使用场景 3: 导入指定日期的数据
        # target_date = datetime(2025, 11, 3)
        # main_logger.info(f"导入指定日期: {target_date.strftime('%Y-%m-%d')}")
        # importer_job.run_incremental_import(target_date=target_date)

    except Exception as e:
        main_logger.error(f"导入任务执行失败: {e}")

    finally:
        # 4. 关闭数据库连接
        if 'importer_job' in locals():
            importer_job.close()
            main_logger.info("导入任务结束")
