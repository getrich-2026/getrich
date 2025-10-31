import pandas as pd
import clickhouse_connect
from lntools.utils.log import Logger

# 将建表语句直接嵌入到代码中，实现自动化建表
MIN_BAR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS getrich.min_bar
(
    `date` UInt32,
    `time` Int32,
    `pre_close` Int64,
    `open` Int64,
    `high` Int64,
    `low` Int64,
    `close` Int64,
    `volume` Int64,
    `turnover` Int64,
    `open_interest` Int64,
    `pre_settle_price` Int64,
    `settle_price` Int64,
    `symbol` String,
    `trading_day` Int32,
    `local_time` Int64,
    `insert_time` DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDate(toDateTime(local_time / 1000)))
ORDER BY (symbol, local_time)
"""

CODE_INFO_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS getrich.code_info
(
    `sec_type` Int32,
    `sec_name` String,
    `date` Int32,
    `high_limited` UInt32,
    `low_limited` UInt32,
    `multiplier` Int32,
    `margin_ratio` Int32,
    `price_tick` Int32,
    `capital` Int64,
    `cap_change_date` UInt32,
    `trade_date_in` UInt32,
    `trade_date_out` UInt32,
    `is_halt` Int8,
    `margin_unit` UInt32,
    `margin_ratio_param1` Int32,
    `margin_ratio_param2` Int32,
    `sec_name_ext` String,
    `symbol` String,
    `insert_time` DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(insert_time)
ORDER BY (symbol)
"""


class ClickHouseLoader:
    """
    用于将数据加载到 ClickHouse 的加载器。
    在初始化时会自动检查并创建不存在的表。
    """

    def __init__(self, host: str = 'localhost', port: int = 8123, database: str = 'getrich', **kwargs):
        """
        初始化 ClickHouseLoader。

        Args:
            host (str): ClickHouse 主机名。
            port (int): ClickHouse 端口。
            database (str): 数据库名称。
            **kwargs: 其他传递给 clickhouse-connect 客户端的参数。
        """
        self.logger = Logger(module_name=__name__)
        self.client = clickhouse_connect.get_client(
            host=host,
            port=port,
            database=database,
            **kwargs
        )
        self.logger.info(f"成功连接到 ClickHouse (host: {host}, port: {port}, database: {database})")

        # 初始化时检查并创建表
        self._initialize_schema()

    def _initialize_schema(self):
        """
        执行建表语句，如果表不存在则创建。
        """
        try:
            self.logger.info("正在检查并初始化数据库 schema...")
            self.client.command("CREATE DATABASE IF NOT EXISTS getrich")
            self.client.command(MIN_BAR_TABLE_SQL)
            self.logger.info("表 'min_bar' 已确认存在。")
            self.client.command(CODE_INFO_TABLE_SQL)
            self.logger.info("表 'code_info' 已确认存在。")
            self.logger.info("数据库 schema 初始化完成。")
        except Exception as e:
            self.logger.error(f"初始化数据库 schema 时出错: {e}")
            raise

    def bulk_insert(self, table_name: str, df: pd.DataFrame):
        """
        将 Pandas DataFrame 批量插入到指定的表中。

        Args:
            table_name (str): 目标表名。
            df (pd.DataFrame): 要插入的数据。
        """
        if df.empty:
            self.logger.info(f"DataFrame 为空，跳过插入操作 (表: {table_name})。")
            return

        try:
            # 使用 insert_df 方法进行高效插入
            self.client.insert_df(table=table_name, df=df)
            self.logger.info(f"成功将 {len(df)} 条数据批量插入到表 '{table_name}'。")
        except Exception as e:
            self.logger.error(f"向表 '{table_name}' 插入数据时出错: {e}")
            # 在实际生产环境中，您可能希望添加更复杂的错误处理和重试逻辑
            raise

    def close(self):
        """
        关闭 ClickHouse 客户端连接。
        """
        self.client.close()
        self.logger.info("ClickHouse 连接已关闭。")


if __name__ == '__main__':
    # ClickHouseLoader 使用示例
    main_logger = Logger(module_name='load_main')

    # 假设您有一个 ClickHouse 实例正在运行
    try:
        # 初始化时会自动创建数据库和表（如果不存在）
        loader = ClickHouseLoader(database='getrich')

        # 创建一个示例 DataFrame 来模拟 code_info 数据
        sample_code_info = pd.DataFrame({
            'sec_type': [1],
            'sec_name': ['示例股票'],
            'date': [20250101],
            'high_limited': [110000],
            'low_limited': [90000],
            'multiplier': [1],
            'margin_ratio': [100],
            'price_tick': [100],
            'capital': [100000000],
            'cap_change_date': [20250101],
            'trade_date_in': [20250101],
            'trade_date_out': [99991231],
            'is_halt': [0],
            'margin_unit': [1],
            'margin_ratio_param1': [0],
            'margin_ratio_param2': [0],
            'sec_name_ext': [''],
            'symbol': ['SH.600000.TEST'],
        })

        # 插入 code_info 数据
        loader.bulk_insert('code_info', sample_code_info)

        # 创建一个示例 DataFrame 来模拟 min_bar 数据
        sample_min_bar = pd.DataFrame({
            'date': [20250101],
            'time': [93100000],
            'pre_close': [100000],
            'open': [101000],
            'high': [102000],
            'low': [100500],
            'close': [101500],
            'volume': [10000],
            'turnover': [1015000000],
            'open_interest': [0],
            'pre_settle_price': [0],
            'settle_price': [0],
            'symbol': ['SH.600000.TEST'],
            'trading_day': [20250101],
            'local_time': [1735695060000],  # 对应 2025-01-01 09:31:00
        })

        # 插入 min_bar 数据
        loader.bulk_insert('min_bar', sample_min_bar)

        loader.close()

    except Exception as e:
        main_logger.error(f"运行示例时出错: {e}")
        main_logger.error("请确保 ClickHouse 服务正在运行。")
