# 生成min_bar的类,包括创建表、读取文件、插入数据、查询数据等方法
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING
import pandas as pd

from Data.clickhouse.table.base import ClickHouseTable

if TYPE_CHECKING:  # 避免循环导入问题
    from Data.clickhouse.database import ClickHouseClient
    from Data.clickhouse.pool import ClickHouseConnectionPool


class MinBarTable(ClickHouseTable):
    """
    用于操作 min_bar 表的类,负责分钟线数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。

    注意：虽然主键使用 local_time, 但添加了 date 字段的跳数索引以优化日期范围查询。
    """

    def __init__(
        self,
        table_name: str = 'min_bar',
        client: Optional[ClickHouseClient] = None,
        pool: Optional[ClickHouseConnectionPool] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None
    ) -> None:
        """
        初始化 MinBarTable。

        Args:
            table_name: 表名,默认为 'min_bar'
            client: ClickHouse 客户端实例,如果为 None 则自动创建
            pool: ClickHouse 连接池实例(优先级高于 client)
            host: ClickHouse 主机地址(仅在 client=None 且 pool=None 时使用)
            port: ClickHouse 端口(仅在 client=None 且 pool=None 时使用)
            user: 用户名(仅在 client=None 且 pool=None 时使用)
            password: 密码(仅在 client=None 且 pool=None 时使用)
            database: 数据库名(仅在 client=None 且 pool=None 时使用)
        """
        # 调用父类构造函数
        super().__init__(
            table_name=table_name,
            client=client,
            pool=pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            logger_name="MinBarTable"
        )

        # 表结构定义
        self.table_schema = {
            'date': 'UInt32',
            'time': 'Int32',
            'pre_close': 'Int64',
            'open': 'Int64',
            'high': 'Int64',
            'low': 'Int64',
            'close': 'Int64',
            'volume': 'Int64',
            'turnover': 'Int64',
            'open_interest': 'Int64',
            'pre_settle_price': 'Int64',
            'settle_price': 'Int64',
            'symbol': 'String',
            'local_time': 'DateTime64(3)',
            'insert_time': 'DateTime'
        }

    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建 min_bar 表。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        # 使用 local_time 做分区依据,按 symbol+date+local_time 排序
        # 这样既支持按时间顺序查询,也优化了按日期范围查询的性能
        create_sql = f"""
        CREATE TABLE {exists_clause} {self.table_name}
        (
            date UInt32 CODEC(Delta, ZSTD),
            time Int32 CODEC(Delta, ZSTD),
            pre_close Int64 CODEC(Delta, ZSTD),
            open Int64 CODEC(Delta, ZSTD),
            high Int64 CODEC(Delta, ZSTD),
            low Int64 CODEC(Delta, ZSTD),
            close Int64 CODEC(Delta, ZSTD),
            volume Int64 CODEC(Delta, ZSTD),
            turnover Int64 CODEC(Delta, ZSTD),
            open_interest Int64 CODEC(Delta, ZSTD),
            pre_settle_price Int64 CODEC(Delta, ZSTD),
            settle_price Int64 CODEC(Delta, ZSTD),
            symbol String,
            local_time DateTime64(3) CODEC(Delta, ZSTD),
            insert_time DateTime DEFAULT now() CODEC(Delta, ZSTD)
        )
        ENGINE = MergeTree()
        PARTITION BY toYYYYMM(local_time)
        ORDER BY (symbol, date, local_time)
        SETTINGS index_granularity = 8192,
                 min_bytes_for_wide_part = 0,
                 min_rows_for_wide_part = 0,
                 enable_mixed_granularity_parts = 1
        """

        # 使用父类的 execute 方法
        if self.execute(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def read(
        self,
        symbols: Optional[str | list[str]] = None,
        start_date: Optional[datetime | str] = None,
        end_date: Optional[datetime | str] = None,
        order_by: str = "symbol, local_time",
        limit: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """
        读取 min_bar 表中的数据,支持灵活的日期和标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表或 None(读取所有标的)
            start_date: 开始日期,支持 datetime 或字符串格式(如 '2020-01-01'),None 表示从 2005-01-01 开始
            end_date: 结束日期,支持 datetime 或字符串格式(如 '2025-12-31'),None 表示到当前日期
            order_by: 排序字段,默认按 symbol 和 local_time 排序
            limit: 限制返回的记录数,None 表示不限制

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        # 构建条件列表
        conditions = []

        # 处理symbols参数
        if symbols is not None:
            if isinstance(symbols, str):
                # 单个标的
                conditions.append(f"symbol = '{symbols}'")
            elif isinstance(symbols, list) and len(symbols) > 0:
                # 多个标的
                symbols_str = "', '".join(symbols)
                conditions.append(f"symbol IN ('{symbols_str}')")

        # 处理日期范围
        # 如果没有指定start_date,默认从2005-01-01开始
        if start_date is None:
            start_date = '2005-01-01'

        # 转换start_date为字符串格式
        if isinstance(start_date, datetime):
            start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            start_date_str = str(start_date)

        conditions.append(f"local_time >= '{start_date_str}'")

        # 如果没有指定end_date,使用当前日期
        if end_date is None:
            end_date = datetime.now()

        # 转换end_date为字符串格式
        if isinstance(end_date, datetime):
            end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')
        else:
            end_date_str = str(end_date)

        conditions.append(f"local_time <= '{end_date_str}'")

        # 构建完整的查询语句
        query = f"SELECT * FROM {self.table_name}"

        if conditions:
            query += " WHERE " + ' AND '.join(conditions)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 使用父类的 query 方法
        result = self.query(query)

        if result is not None:
            self.logger.info(f"Successfully read {len(result)} records from '{self.table_name}'")
        else:
            self.logger.warning(f"No data found or error occurred while reading from '{self.table_name}'")

        return result


class DayBarTable(ClickHouseTable):
    """
    用于操作 day_bar 表的类,负责日线数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。

    注意：日线数据按 (symbol, date) 排序,因为日线查询主要按日期范围进行。
    """

    def __init__(
        self,
        table_name: str = 'day_bar',
        client: Optional[ClickHouseClient] = None,
        pool: Optional['ClickHouseConnectionPool'] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None
    ) -> None:
        """
        初始化 DayBarTable。

        Args:
            table_name: 表名,默认为 'day_bar'
            client: ClickHouse 客户端实例,如果为 None 则自动创建
            pool: ClickHouse 连接池实例(优先级高于 client)
            host: ClickHouse 主机地址(仅在 client=None 且 pool=None 时使用)
            port: ClickHouse 端口(仅在 client=None 且 pool=None 时使用)
            user: 用户名(仅在 client=None 且 pool=None 时使用)
            password: 密码(仅在 client=None 且 pool=None 时使用)
            database: 数据库名(仅在 client=None 且 pool=None 时使用)
        """
        # 调用父类构造函数
        super().__init__(
            table_name=table_name,
            client=client,
            pool=pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            logger_name="DayBarTable"
        )

        # 表结构定义（与 MinBarTable 相同）
        self.table_schema = {
            'date': 'UInt32',
            'time': 'Int32',
            'pre_close': 'Int64',
            'open': 'Int64',
            'high': 'Int64',
            'low': 'Int64',
            'close': 'Int64',
            'volume': 'Int64',
            'turnover': 'Int64',
            'open_interest': 'Int64',
            'pre_settle_price': 'Int64',
            'settle_price': 'Int64',
            'symbol': 'String',
            'local_time': 'DateTime64(3)',
            'insert_time': 'DateTime'
        }

    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建 day_bar 表。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        # 日线数据按年分区,按 symbol+date 排序以优化按日期范围的查询
        # date 作为主键的一部分,可以高效利用索引
        create_sql = f"""
        CREATE TABLE {exists_clause} {self.table_name}
        (
            date UInt32 CODEC(Delta, ZSTD),
            time Int32 CODEC(Delta, ZSTD),
            pre_close Int64 CODEC(Delta, ZSTD),
            open Int64 CODEC(Delta, ZSTD),
            high Int64 CODEC(Delta, ZSTD),
            low Int64 CODEC(Delta, ZSTD),
            close Int64 CODEC(Delta, ZSTD),
            volume Int64 CODEC(Delta, ZSTD),
            turnover Int64 CODEC(Delta, ZSTD),
            open_interest Int64 CODEC(Delta, ZSTD),
            pre_settle_price Int64 CODEC(Delta, ZSTD),
            settle_price Int64 CODEC(Delta, ZSTD),
            symbol String,
            local_time DateTime64(3) CODEC(Delta, ZSTD),
            insert_time DateTime DEFAULT now() CODEC(Delta, ZSTD)
        )
        ENGINE = MergeTree()
        PARTITION BY toYear(date)
        ORDER BY (symbol, date)
        SETTINGS index_granularity = 8192,
                 min_bytes_for_wide_part = 0,
                 min_rows_for_wide_part = 0,
                 enable_mixed_granularity_parts = 1
        """

        # 使用父类的 execute 方法
        if self.execute(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def read(
        self,
        symbols: Optional[str | list[str]] = None,
        start_date: Optional[int | str] = None,
        end_date: Optional[int | str] = None,
        order_by: str = "symbol, date",
        limit: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """
        读取 day_bar 表中的数据,支持灵活的日期和标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表或 None(读取所有标的)
            start_date: 开始日期,支持整数格式(如 20200101)或字符串格式(如 '2020-01-01'),
                       None 表示从 20050101 开始
            end_date: 结束日期,支持整数格式(如 20251231)或字符串格式(如 '2025-12-31'),
                     None 表示到当前日期
            order_by: 排序字段,默认按 symbol 和 date 排序
            limit: 限制返回的记录数,None 表示不限制

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        # 构建条件列表
        conditions = []

        # 处理symbols参数
        if symbols is not None:
            if isinstance(symbols, str):
                # 单个标的
                conditions.append(f"symbol = '{symbols}'")
            elif isinstance(symbols, list) and len(symbols) > 0:
                # 多个标的
                symbols_str = "', '".join(symbols)
                conditions.append(f"symbol IN ('{symbols_str}')")

        # 处理日期范围 - 使用 date 字段(UInt32)进行比较
        # 如果没有指定start_date,默认从20050101开始
        if start_date is None:
            start_date_int = 20050101
        else:
            # 转换为整数格式
            if isinstance(start_date, int):
                start_date_int = start_date
            else:
                # 字符串格式如 '2020-01-01' 转换为 20200101
                start_date_str = str(start_date).replace('-', '')
                start_date_int = int(start_date_str)

        conditions.append(f"date >= {start_date_int}")

        # 如果没有指定end_date,使用当前日期
        if end_date is None:
            end_date_int = int(datetime.now().strftime('%Y%m%d'))
        else:
            # 转换为整数格式
            if isinstance(end_date, int):
                end_date_int = end_date
            else:
                # 字符串格式如 '2025-12-31' 转换为 20251231
                end_date_str = str(end_date).replace('-', '')
                end_date_int = int(end_date_str)

        conditions.append(f"date <= {end_date_int}")

        # 构建完整的查询语句
        query = f"SELECT * FROM {self.table_name}"

        if conditions:
            query += " WHERE " + ' AND '.join(conditions)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 使用父类的 query 方法
        result = self.query(query)

        if result is not None:
            self.logger.info(f"Successfully read {len(result)} records from '{self.table_name}'")
        else:
            self.logger.warning(f"No data found or error occurred while reading from '{self.table_name}'")

        return result


if __name__ == '__main__':
    from lntools import Logger

    # --- 配置 ---
    # 使用测试表以避免影响生产数据
    TABLE_NAME = 'min_bar_test'

    main_logger = Logger(module_name="MinBarTableExample", output_method="console")

    try:
        # 1. 初始化 MinBarTable 实例(会自动连接到 ClickHouse)
        # 方式1: 使用默认配置(从 config.yml 读取)
        min_bar_manager = MinBarTable(table_name=TABLE_NAME)

        # 方式2: 显式指定配置
        # min_bar_manager = MinBarTable(
        #     table_name=TABLE_NAME,
        #     host='localhost',
        #     port=8123,
        #     user='default',
        #     password='getrich',
        #     database='default'
        # )
        main_logger.info("Successfully connected to ClickHouse")

        # 2. (可选) 先删除已存在的测试表,确保从干净的状态开始
        main_logger.info(f"--- Step 1: Drop old test table '{TABLE_NAME}' (if exists) ---")
        min_bar_manager.drop()

        # 3. 创建新表
        main_logger.info(f"--- Step 2: Create new table '{TABLE_NAME}' ---")
        if not min_bar_manager.create():
            raise RuntimeError("Failed to create table, aborting example")

        # 4. 准备示例数据
        main_logger.info("--- Step 3: Prepare sample data for insertion ---")
        sample_data = {
            'date': [20250101, 20250101, 20250102, 20250102],
            'time': [93100000, 93200000, 93100000, 93200000],
            'pre_close': [100000, 100000, 101500, 101500],
            'open': [101000, 101500, 102000, 102500],
            'high': [102000, 102500, 103000, 103500],
            'low': [100500, 101200, 101500, 102000],
            'close': [101500, 102200, 102500, 103000],
            'volume': [10000, 12000, 11000, 13000],
            'turnover': [1015000000, 1226400000, 1127500000, 1339000000],
            'open_interest': [0, 0, 0, 0],
            'pre_settle_price': [0, 0, 0, 0],
            'settle_price': [0, 0, 0, 0],
            'symbol': ['SH.600000.TEST', 'SH.600000.TEST', 'SH.600001.TEST', 'SH.600001.TEST'],
            'local_time': pd.to_datetime([
                '2025-01-01 09:31:00',
                '2025-01-01 09:32:00',
                '2025-01-02 09:31:00',
                '2025-01-02 09:32:00'
            ]),
        }
        sample_df = pd.DataFrame(sample_data)
        main_logger.info(f"Created DataFrame with {len(sample_df)} records")

        # 5. 批量插入数据
        main_logger.info(f"--- Step 4: Bulk insert data into '{TABLE_NAME}' ---")
        min_bar_manager.insert(sample_df)

        # 6. 测试不同的读取场景
        main_logger.info("--- Step 5: Test different read scenarios ---")

        # 场景1: 读取所有数据
        main_logger.info("Scenario 1: Read all data")
        result1 = min_bar_manager.read()
        if result1 is not None:
            print(f"Total records: {len(result1)}")
            print(result1.head())

        # 场景2: 只指定开始日期
        main_logger.info("\nScenario 2: Read data from specific start date")
        result2 = min_bar_manager.read(start_date='2025-01-02')
        if result2 is not None:
            print(f"Records from 2025-01-02: {len(result2)}")
            print(result2)

        # 场景3: 只指定结束日期
        main_logger.info("\nScenario 3: Read data until specific end date")
        result3 = min_bar_manager.read(end_date='2025-01-01 23:59:59')
        if result3 is not None:
            print(f"Records until 2025-01-01: {len(result3)}")
            print(result3)

        # 场景4: 指定单个标的
        main_logger.info("\nScenario 4: Read data for single symbol")
        result4 = min_bar_manager.read(symbols='SH.600000.TEST')
        if result4 is not None:
            print(f"Records for SH.600000.TEST: {len(result4)}")
            print(result4)

        # 场景5: 指定多个标的和日期范围
        main_logger.info("\nScenario 5: Read data for multiple symbols with date range")
        result5 = min_bar_manager.read(
            symbols=['SH.600000.TEST', 'SH.600001.TEST'],
            start_date='2025-01-01',
            end_date='2025-01-02',
            limit=10
        )
        if result5 is not None:
            print(f"Records for multiple symbols: {len(result5)}")
            print(result5)

        # 7. 清空表数据
        main_logger.info(f"\n--- Step 6: Truncate table '{TABLE_NAME}' ---")
        min_bar_manager.truncate()

        # 8. 删除表
        main_logger.info(f"--- Step 7: Drop test table '{TABLE_NAME}' ---")
        min_bar_manager.drop()

        main_logger.info("MinBarTable example completed successfully")

    except Exception as e:
        main_logger.error(f"Error running MinBarTable example: {e}")
        main_logger.error("Please ensure ClickHouse service is running and database 'default' exists")

    finally:
        # 9. 关闭连接
        if 'min_bar_manager' in locals():
            min_bar_manager.close()
            main_logger.info("MinBarTable connection closed")

    # ========== DayBarTable 示例 ==========
    main_logger.info("\n" + "="*50)
    main_logger.info("Starting DayBarTable Example")
    main_logger.info("="*50 + "\n")

    try:
        # 1. 初始化 DayBarTable 实例
        DAY_TABLE_NAME = 'day_bar_test'
        day_bar_manager = DayBarTable(table_name=DAY_TABLE_NAME)
        main_logger.info("Successfully connected to ClickHouse for DayBarTable")

        # 2. 先删除已存在的测试表
        main_logger.info(f"--- Step 1: Drop old test table '{DAY_TABLE_NAME}' (if exists) ---")
        day_bar_manager.drop()

        # 3. 创建新表
        main_logger.info(f"--- Step 2: Create new table '{DAY_TABLE_NAME}' ---")
        if not day_bar_manager.create():
            raise RuntimeError("Failed to create DayBarTable, aborting example")

        # 4. 准备日线示例数据
        main_logger.info("--- Step 3: Prepare sample day bar data for insertion ---")
        day_sample_data = {
            'date': [20250101, 20250102, 20250103, 20250101, 20250102, 20250103],
            'time': [150000000, 150000000, 150000000, 150000000, 150000000, 150000000],
            'pre_close': [100000, 101500, 102500, 200000, 201500, 203000],
            'open': [101000, 102000, 103000, 201000, 202000, 204000],
            'high': [102000, 103000, 104000, 202000, 204000, 206000],
            'low': [100500, 101500, 102500, 200500, 201500, 203500],
            'close': [101500, 102500, 103500, 201500, 203000, 205000],
            'volume': [100000, 120000, 110000, 150000, 160000, 140000],
            'turnover': [10150000000, 12300000000, 11385000000, 30225000000, 32480000000, 28700000000],
            'open_interest': [0, 0, 0, 0, 0, 0],
            'pre_settle_price': [0, 0, 0, 0, 0, 0],
            'settle_price': [0, 0, 0, 0, 0, 0],
            'symbol': ['SH.600000.TEST', 'SH.600000.TEST', 'SH.600000.TEST',
                       'SH.600001.TEST', 'SH.600001.TEST', 'SH.600001.TEST'],
            'local_time': pd.to_datetime([
                '2025-01-01 15:00:00',
                '2025-01-02 15:00:00',
                '2025-01-03 15:00:00',
                '2025-01-01 15:00:00',
                '2025-01-02 15:00:00',
                '2025-01-03 15:00:00'
            ]),
        }
        day_sample_df = pd.DataFrame(day_sample_data)
        main_logger.info(f"Created DataFrame with {len(day_sample_df)} day bar records")

        # 5. 批量插入数据
        main_logger.info(f"--- Step 4: Bulk insert data into '{DAY_TABLE_NAME}' ---")
        day_bar_manager.insert(day_sample_df)

        # 6. 测试不同的读取场景
        main_logger.info("--- Step 5: Test different read scenarios for day bar ---")

        # 场景1: 使用整数格式的日期查询
        main_logger.info("\nScenario 1: Read data with integer date format")
        result1 = day_bar_manager.read(start_date=20250101, end_date=20250102)
        if result1 is not None:
            print(f"Records from 20250101 to 20250102: {len(result1)}")
            print(result1)

        # 场景2: 使用字符串格式的日期查询
        main_logger.info("\nScenario 2: Read data with string date format")
        result2 = day_bar_manager.read(start_date='2025-01-02', end_date='2025-01-03')
        if result2 is not None:
            print(f"Records from 2025-01-02 to 2025-01-03: {len(result2)}")
            print(result2)

        # 场景3: 查询单个标的的所有数据
        main_logger.info("\nScenario 3: Read all data for single symbol")
        result3 = day_bar_manager.read(symbols='SH.600000.TEST')
        if result3 is not None:
            print(f"All records for SH.600000.TEST: {len(result3)}")
            print(result3)

        # 场景4: 查询多个标的在特定日期范围的数据
        main_logger.info("\nScenario 4: Read data for multiple symbols with date range")
        result4 = day_bar_manager.read(
            symbols=['SH.600000.TEST', 'SH.600001.TEST'],
            start_date=20250101,
            end_date=20250102
        )
        if result4 is not None:
            print(f"Records for multiple symbols (20250101-20250102): {len(result4)}")
            print(result4)

        # 7. 清空表数据
        main_logger.info(f"\n--- Step 6: Truncate table '{DAY_TABLE_NAME}' ---")
        day_bar_manager.truncate()

        # 8. 删除表
        main_logger.info(f"--- Step 7: Drop test table '{DAY_TABLE_NAME}' ---")
        day_bar_manager.drop()

        main_logger.info("DayBarTable example completed successfully")

    except Exception as e:
        main_logger.error(f"Error running DayBarTable example: {e}")
        main_logger.error("Please ensure ClickHouse service is running and database 'default' exists")

    finally:
        # 9. 关闭连接
        if 'day_bar_manager' in locals():
            day_bar_manager.close()
            main_logger.info("DayBarTable connection closed")
