# 生成min_bar的类，包括创建表、读取文件、插入数据、查询数据等方法
from __future__ import annotations

import pandas as pd

from lntools import Logger
from Data.clickhouse.database import ClickHouseDB


class MinBarTable(ClickHouseDB):
    """
    用于操作min_bar表的类, 负责创建 market_data 表、数据导入、表管理等操作
    继承自 ClickHouseDB 以复用数据库操作方法
    """

    def __init__(self,
                 host: str = 'localhost',
                 port: int = 8123,
                 user: str = 'default',
                 password: str = 'getrich',
                 database: str = 'default',
                 table_name: str = 'min_bar') -> None:
        # 调用父类构造函数初始化数据库连接
        super().__init__(host=host, port=port, user=user, password=password, database=database)
        self.table_name = table_name
        self.logger = Logger(module_name="MinBarTable", output_method="console")

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
            'trading_day': 'Int32',
            'local_time': 'DateTime64(3)'
        }

    def create_table(self, if_not_exists: bool = True) -> bool:
        """
        创建min_bar表
        :param if_not_exists: 如果表已存在，是否跳过创建
        :return: 创建成功返回True, 否则返回False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""
        # 使用 local_time (ms since epoch) 做分区依据，按 symbol+local_time 排序以优化按合约和时间范围的查询
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
            trading_day Int32 CODEC(Delta, ZSTD),
            local_time DateTime64(3) CODEC(Delta, ZSTD),
            insert_time DateTime DEFAULT now() CODEC(Delta, ZSTD)
        )
        ENGINE = MergeTree()
        PARTITION BY toYYYYMM(local_time)
        ORDER BY (symbol, local_time)
        SETTINGS index_granularity = 8192,
                 min_bytes_for_wide_part = 0,
                 min_rows_for_wide_part = 0,
                 enable_mixed_granularity_parts = 1
        """

        # 使用父类的 execute_sql 方法
        if self.execute_sql(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def bulk_insert(self, df: pd.DataFrame) -> bool:
        """
        将 Pandas DataFrame 批量插入到表中。

        :param df: 包含要插入数据的数据帧。
        :return: 成功返回True, 否则返回False。
        """
        if df.empty:
            self.logger.info(f"DataFrame is empty, skipping insertion into '{self.table_name}'.")
            return True

        # 使用父类的 insert_data 方法
        if self.insert_data(self.table_name, df):
            self.logger.info(f"Successfully bulk inserted {len(df)} rows into '{self.table_name}'.")
            return True
        else:
            self.logger.error(f"Failed to bulk insert data into '{self.table_name}'.")
            return False

    def drop_table(self, if_exists: bool = True) -> bool:
        """
        删除表。

        :param if_exists: 如果表不存在，是否跳过删除。
        :return: 成功返回True, 否则返回False。
        """
        exists_clause = "IF EXISTS" if if_exists else ""
        drop_sql = f"DROP TABLE {exists_clause} {self.table_name}"
        
        # 使用父类的 execute_sql 方法
        if self.execute_sql(drop_sql):
            self.logger.info(f"Table '{self.table_name}' dropped successfully.")
            return True
        else:
            self.logger.error(f"Failed to drop table '{self.table_name}'.")
            return False

    def truncate_table(self) -> bool:
        """
        清空表中的所有数据。

        :return: 成功返回True, 否则返回False。
        """
        truncate_sql = f"TRUNCATE TABLE {self.table_name}"
        
        # 使用父类的 execute_sql 方法
        if self.execute_sql(truncate_sql):
            self.logger.info(f"Table '{self.table_name}' truncated successfully.")
            return True
        else:
            self.logger.error(f"Failed to truncate table '{self.table_name}'.")
            return False

    def query_data(self, query: str) -> pd.DataFrame | None:
        """
        执行查询并以 Pandas DataFrame 形式返回结果。

        :param query: 要执行的 SQL 查询语句。
        :return: 包含查询结果的 DataFrame, 如果出错则返回 None。
        """
        # 使用父类的 client 直接查询
        if not self.client:
            self.logger.error("没有到ClickHouse的活动连接。")
            return None
            
        try:
            result_df = self.client.query_df(query)
            self.logger.info(f"Query executed successfully, returned {len(result_df)} rows.")
            return result_df
        except Exception as e:
            self.logger.error(f"Failed to execute query: {e}")
            return None


if __name__ == '__main__':

    # --- 配置 ---
    CLICKHOUSE_HOST = 'localhost'
    CLICKHOUSE_PORT = 8123
    USER = 'default'
    PASSWORD = 'getrich'
    DATABASE = 'default'
    # 使用测试表以避免影响生产数据
    TABLE_NAME = 'min_bar_test'

    main_logger = Logger(module_name="MinBarTableExample", output_method="console")

    try:
        # 1. 初始化 MinBarTable 实例（会自动连接到 ClickHouse）
        min_bar_manager = MinBarTable(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            user=USER,
            password=PASSWORD,
            database=DATABASE,
            table_name=TABLE_NAME
        )
        main_logger.info(f"成功连接到 ClickHouse (host: {CLICKHOUSE_HOST}, port: {CLICKHOUSE_PORT})")

        # 2. (可选) 先删除已存在的测试表，确保从干净的状态开始
        main_logger.info(f"--- 步骤 1: 删除旧的测试表 '{TABLE_NAME}' (如果存在) ---")
        min_bar_manager.drop_table()

        # 3. 创建新表
        main_logger.info(f"--- 步骤 2: 创建新表 '{TABLE_NAME}' ---")
        if not min_bar_manager.create_table():
            raise RuntimeError("创建表失败，中止示例。")

        # 4. 准备示例数据
        main_logger.info("--- 步骤 3: 准备要插入的示例数据 ---")
        sample_data = {
            'date': [20250101, 20250101],
            'time': [93100000, 93200000],
            'pre_close': [100000, 100000],
            'open': [101000, 101500],
            'high': [102000, 102500],
            'low': [100500, 101200],
            'close': [101500, 102200],
            'volume': [10000, 12000],
            'turnover': [1015000000, 1226400000],
            'open_interest': [0, 0],
            'pre_settle_price': [0, 0],
            'settle_price': [0, 0],
            'symbol': ['SH.600000.TEST', 'SH.600000.TEST'],
            'trading_day': [20250101, 20250101],
            # 使用 pandas 的 to_datetime 来创建带时区的 datetime 对象
            'local_time': pd.to_datetime(['2025-01-01 09:31:00', '2025-01-01 09:32:00']),
        }
        sample_df = pd.DataFrame(sample_data)
        main_logger.info(f"创建了包含 {len(sample_df)} 条记录的 DataFrame。")

        # 5. 批量插入数据
        main_logger.info(f"--- 步骤 4: 批量插入数据到 '{TABLE_NAME}' ---")
        min_bar_manager.bulk_insert(sample_df)

        # 6. 查询数据进行验证
        main_logger.info("--- 步骤 5: 查询插入的数据进行验证 ---")
        query_sql = f"SELECT * FROM {TABLE_NAME} WHERE symbol = 'SH.600000.TEST' ORDER BY local_time"
        result = min_bar_manager.query_data(query_sql)
        if result is not None:
            main_logger.info("查询结果:")
            print(result)

        # 7. 清空表数据
        main_logger.info(f"--- 步骤 6: 清空表 '{TABLE_NAME}' ---")
        min_bar_manager.truncate_table()
        result_after_truncate = min_bar_manager.query_data(f"SELECT count() FROM {TABLE_NAME}")
        if result_after_truncate is not None:
            main_logger.info(f"清空后表中的行数: {result_after_truncate.iloc[0, 0]}")

        # 8. 删除表
        main_logger.info(f"--- 步骤 7: 删除测试表 '{TABLE_NAME}' ---")
        min_bar_manager.drop_table()

        main_logger.info("示例运行成功完成。")

    except Exception as e:
        main_logger.error(f"运行示例时出错: {e}")
        main_logger.error("请确保 ClickHouse 服务正在运行，并且数据库 'default' 已存在。")

    finally:
        # 9. 关闭连接（使用继承的方法）
        if 'min_bar_manager' in locals():
            min_bar_manager.close_connection()
            main_logger.info("ClickHouse 连接已关闭。")
