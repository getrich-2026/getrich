# 数据访问层
from __future__ import annotations
import clickhouse_connect
import pandas as pd

from .utils import log


class ClickHouseDB:
    """
    用于与ClickHouse数据库交互的类。
    """
    def __init__(self, host='localhost', port=8123, user='default', password='getrich', database='default'):
        """
        初始化ClickHouse数据库连接。
        :param host: 主机名
        :param port: 端口号
        :param user: 用户名
        :param password: 密码
        :param database: 数据库名
        """
        try:
            self.client = clickhouse_connect.get_client(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database
            )
        except Exception as e:
            log.error(f"连接ClickHouse时出错: {e}")
            self.client = None

    def close_connection(self):
        """
        关闭数据库连接。
        """
        if self.client:
            self.client.close()

    def execute_sql(self, sql_query: str):
        """
        执行任意SQL语句 (主要用于DDL或不返回数据的DML)。
        :param sql_query: 要执行的SQL查询字符串。
        :return: 成功时返回True,失败时返回False。
        """
        if not self.client:
            log.error("没有到ClickHouse的活动连接。")
            return False
        try:
            self.client.command(sql_query)
            return True
        except Exception as e:
            log.error(f"执行SQL时出错: {e}")
            return False

    def read_data(self, table_name: str, columns: str = '*', condition: str | None = None) -> pd.DataFrame | None:
        """
        从表中读取数据并返回一个pandas DataFrame。
        :param table_name: 表名。
        :param columns: 要查询的列，默认为'*'。
        :param condition: WHERE子句的条件，例如 "symbol = 'BTC/USDT'"。
        :return: 包含查询结果的pandas DataFrame，如果出错则返回None。
        """
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return None

        query = f"SELECT {columns} FROM {table_name}"
        if condition:
            query += f" WHERE {condition}"

        try:
            df = self.client.query_df(query)
            return df
        except Exception as e:
            log.error(f"从表 {table_name} 读取数据时出错: {e}")
            return None

    def insert_data(self, table_name: str, data: pd.DataFrame | list, column_names: list[str] | None = None):
        """
        向表中插入数据。
        :param table_name: 表名。
        :param data: 要插入的数据,可以是pandas DataFrame或list of lists/tuples。
        :param column_names: 列名列表。如果data是DataFrame,则忽略此参数。
        :return: 成功时返回True,失败时返回False。
        """
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return False

        try:
            if isinstance(data, pd.DataFrame):
                self.client.insert_df(table_name, data)
            else:
                if column_names is None:
                    log.warning("当data是list时,必须提供column_names参数。")
                    return False
                self.client.insert(table_name, data, column_names=column_names)
            return True
        except Exception as e:
            log.error(f"向表 {table_name} 插入数据时出错: {e}")
            return False

    def upsert_data(self, table_name: str, data: pd.DataFrame, key_columns: list[str]):
        """
        向表中更新或插入数据 (Upsert)。
        此方法首先删除与 `key_columns` 匹配的现有行，然后插入新数据。
        注意：ClickHouse的DELETE (ALTER TABLE ... DELETE) 操作是异步执行的，
        数据不会立即被删除，而是在后台合并过程中被清理。

        :param table_name: 表名。
        :param data: 要插入的pandas DataFrame。
        :param key_columns: 用于标识唯一记录的列名列表。
        :return: 成功时返回True，失败时返回False。
        """
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return False

        if not isinstance(data, pd.DataFrame) or data.empty:
            log.warning("数据必须是非空的pandas DataFrame。")
            return False

        # 检查key_columns是否存在于DataFrame中
        missing_keys = [key for key in key_columns if key not in data.columns]
        if missing_keys:
            log.warning(f"关键列 {missing_keys} 在DataFrame中不存在。")
            return False

        try:
            # 1. 删除与新数据中的键匹配的现有记录
            # 从DataFrame中提取键值，并格式化为元组列表字符串
            keys_df = data[key_columns]
            # 将每一行转换为元组
            key_values = [tuple(row) for row in keys_df.itertuples(index=False)]

            # 构建 WHERE 子句
            # ClickHouse的IN子句支持元组
            keys_str = ', '.join(map(str, key_values))
            key_cols_str = ', '.join(key_columns)

            # 如果只有一个key，格式为 IN (v1, v2, ...)，否则为 IN ((k1,k2), (k1,k2), ...)
            if len(key_columns) == 1:
                where_clause = f"{key_cols_str} IN ({keys_str.rstrip(',')})"
            else:
                where_clause = f"({key_cols_str}) IN ({keys_str})"

            delete_query = f"ALTER TABLE {table_name} DELETE WHERE {where_clause}"

            self.execute_sql(delete_query)

            # 2. 插入新数据
            return self.insert_data(table_name, data)

        except Exception as e:
            log.error(f"向表 {table_name} upsert数据时出错: {e}")
            return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()
