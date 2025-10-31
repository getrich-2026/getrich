# 数据访问层
from __future__ import annotations
from typing import Optional, Dict, Any, Union, List

import clickhouse_connect
import pandas as pd

from lntools import Logger

log = Logger(module_name="ClickhouseDB")


class ClickHouseDB:
    """
    用于与ClickHouse数据库交互的类。
    """
    def __init__(self,
                 host: str = 'localhost',
                 port: int = 8123,
                 user: str = 'default',
                 password: str = 'getrich',
                 database: str = 'default'):
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
            log.info(f"成功连接到ClickHouse数据库: {host}:{port}/{database}")
        except Exception as e:
            log.error(f"连接ClickHouse时出错: {e}")
            self.client = None

    def close_connection(self):
        """
        关闭数据库连接。
        """
        if hasattr(self, 'client') and self.client:
            try:
                self.client.close()
                self.client = None
                log.info("ClickHouse连接已关闭")
            except Exception as e:
                log.error(f"关闭ClickHouse连接时出错: {e}")

    def execute_sql(self, sql_query: str, params: Optional[Dict[str, Any]] = None):
        """
        执行任意SQL语句 (主要用于DDL或不返回数据的DML)。
        :param sql_query: 要执行的SQL查询字符串。
        :param params: SQL参数化查询的参数字典。
        :return: 成功时返回True,失败时返回False。
        """
        if not self.client:
            log.error("没有到ClickHouse的活动连接。")
            return False
        try:
            if params:
                self.client.command(sql_query, parameters=params)
            else:
                self.client.command(sql_query)
            return True
        except Exception as e:
            log.error(f"执行SQL时出错: {e}\nSQL: {sql_query}")
            return False

    def query_sql(self,
                  sql_query: str,
                  params: Optional[Dict[str, Any]] = None,
                  use_df: bool = True) -> Optional[Union[pd.DataFrame, List[List[Any]]]]:
        """
        执行任意SELECT SQL查询并返回结果。

        :param sql_query: 要执行的SQL查询字符串。
        :param params: SQL参数化查询的参数字典。
        :param use_df: 是否将结果作为pandas DataFrame返回。默认为True。
                       如果为False, 则返回一个列表的列表。
        :return: 包含查询结果的pandas DataFrame或列表, 如果出错则返回None。
        """
        if not self.client:
            log.error("没有到ClickHouse的活动连接。")
            return None
        try:
            if use_df:
                result = self.client.query_df(sql_query, parameters=params)
                log.info(f"SQL查询成功执行, 返回 {len(result)} 条记录。")
            else:
                result = self.client.query(sql_query, parameters=params).result_rows
                log.info(f"SQL查询成功执行, 返回 {len(result)} 条记录。")
            return result  # type: ignore
        except Exception as e:
            log.error(f"执行SQL查询时出错: {e}\nSQL: {sql_query}")
            return None

    def read_data(self,
                  table_name: str,
                  columns: str = '*',
                  condition: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None,
                  limit: Optional[int] = None,
                  offset: Optional[int] = None,
                  order_by: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        从表中读取数据并返回一个pandas DataFrame, 支持参数化查询和分页
        :param table_name: 表名
        :param columns: 要查询的列, 默认为'*'
        :param condition: WHERE子句的条件, 例如 "symbol = 'BTC/USDT'"
        :return: 包含查询结果的pandas DataFrame, 如果出错则返回None
        :param params: SQL参数化查询的参数字典
        :param limit: 限制返回的记录数
        :param offset: 偏移量
        :param order_by: 排序字段, 例如 "date DESC"
        :return: 包含查询结果的pandas DataFrame, 如果出错则返回None
        """
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return None

        query = f"SELECT {columns} FROM {table_name}"
        if condition:
            query += f" WHERE {condition}"
        if order_by:
            query += f" ORDER BY {order_by}"
        if limit:
            query += f" LIMIT {limit}"
        if offset:
            query += f" OFFSET {offset}"

        try:
            if params:
                df = self.client.query_df(query, parameters=params)
            else:
                df = self.client.query_df(query)
            log.info(f"从表 {table_name} 成功读取 {len(df)} 条记录")
            return df
        except Exception as e:
            log.error(f"从表 {table_name} 读取数据时出错: {e}\nSQL: {query}")
            return None

    def insert_data(self,
                    table_name: str,
                    data: Union[pd.DataFrame, List[List[Any]]],
                    column_names: Optional[List[str]] = None,
                    batch_size: Optional[int] = None) -> bool:
        """
        向表中插入数据, 支持批量插入
        :param table_name: 表名
        :param data: 要插入的数据,可以是pandas DataFrame或list of lists/tuples
        :param column_names: 列名列表。如果data是DataFrame,则忽略此参数
        :param batch_size: 批量插入的批次大小, None表示一次性插入
        :return: 成功时返回True,失败时返回False
        """
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return False

        try:
            if isinstance(data, pd.DataFrame):
                if data.empty:
                    log.warning("DataFrame为空, 无需插入")
                    return True
                try:
                    if batch_size and len(data) > batch_size:
                        # 分批次插入
                        for i in range(0, len(data), batch_size):
                            self.client.insert_df(table_name, data.iloc[i:i+batch_size])
                    else:
                        self.client.insert_df(table_name, data)
                except Exception as e:
                    log.error(f"向表 {table_name} 插入数据时出错: {e}")
                    return False

                log.info(f"向表 {table_name} 成功插入 {len(data)} 条记录")
                return True

            elif isinstance(data, list):
                if not data:
                    log.warning("数据列表为空")
                    return False

                if column_names is None:
                    log.warning("当data是list时,必须提供column_names参数。")
                    return False

                # 分批处理列表数据
                if batch_size and len(data) > batch_size:
                    for i in range(0, len(data), batch_size):
                        batch = data[i:i+batch_size]
                        self.client.insert(table_name, batch, column_names=column_names)
                else:
                    self.client.insert(table_name, data, column_names=column_names)

                log.info(f"向表 {table_name} 成功插入 {len(data)} 条记录")
                return True
            else:
                log.warning("不支持的数据类型, 必须是DataFrame或列表类型")
                return False
        except Exception as e:
            log.error(f"向表 {table_name} 插入数据时出错: {e}")
            return False

    def upsert_data(self,
                    table_name: str,
                    data: pd.DataFrame,
                    key_columns: list[str],
                    batch_size: Optional[int] = None) -> bool:
        """
        向表中更新或插入数据 (Upsert)。
        此方法首先删除与 `key_columns` 匹配的现有行, 然后插入新数据。
        注意: ClickHouse的DELETE (ALTER TABLE ... DELETE) 操作是异步执行的,
        数据不会立即被删除, 而是在后台合并过程中被清理。

        :param table_name: 表名
        :param data: 要插入的pandas DataFrame
        :param key_columns: 用于标识唯一记录的列名列表
        :param batch_size: 批量处理的批次大小, None表示一次性处理
        :return: 成功时返回True, 失败时返回False
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
            total_rows = len(data)

            # 如果未指定批次大小或数据量较小, 一次性处理
            if batch_size is None or total_rows <= batch_size:
                return self._process_upsert_batch(table_name, data, key_columns)

            # 批量处理
            log.info(f"开始批量upsert, 总计 {total_rows} 条记录, 批次大小 {batch_size}")
            success_count = 0
            for i in range(0, total_rows, batch_size):
                batch_data = data.iloc[i:i + batch_size].copy()
                batch_num = i // batch_size + 1
                total_batches = (total_rows + batch_size - 1) // batch_size

                log.debug(f"处理批次 {batch_num}/{total_batches}, 记录数: {len(batch_data)}")

                if self._process_upsert_batch(table_name, batch_data, key_columns):
                    success_count += len(batch_data)
                else:
                    log.error(f"批次 {batch_num} 处理失败")
                    return False

            log.info(f"批量upsert完成, 成功处理 {success_count} 条记录")
            return True
        except Exception as e:
            log.error(f"向表 {table_name} upsert数据时出错: {e}")
            return False

    def _process_upsert_batch(self, table_name: str, batch_data: pd.DataFrame, key_columns: list[str]) -> bool:
        """处理单个批次的upsert操作"""
        try:
            # 方案1: 使用 REPLACE INTO (推荐)
            if self._support_replace_into(table_name):
                return self._upsert_with_replace(table_name, batch_data)

            # 方案2: 传统的 DELETE + INSERT
            return self._upsert_with_delete_insert(table_name, batch_data, key_columns)

        except Exception as e:
            log.error(f"处理批次时出错: {e}")
            return False

    def _upsert_with_replace(self, table_name: str, data: pd.DataFrame) -> bool:
        """
        使用 ReplacingMergeTree 的自动去重机制进行 upsert

        ReplacingMergeTree 会在后台合并时自动去重，根据 ORDER BY 子句中的列判断重复。
        相同排序键的行中，保留版本号（如果指定）最大的行，或最后插入的行。

        注意：去重不是立即发生的，而是在后台合并过程中异步执行。
        查询时使用 FINAL 修饰符可以强制进行去重，但会影响性能。
        """
        try:
            # ReplacingMergeTree 引擎直接插入即可，后台会自动去重
            return self.insert_data(table_name, data)

        except Exception as e:
            log.error(f"ReplacingMergeTree upsert 操作失败: {e}")
            return False

    def _upsert_with_delete_insert(self, table_name: str, data: pd.DataFrame, key_columns: list[str]) -> bool:
        """使用 DELETE + INSERT 进行upsert"""
        try:
            # 1. 构建安全的DELETE查询
            if not self._delete_existing_records(table_name, data, key_columns):
                return False

            # 2. 插入新数据
            return self.insert_data(table_name, data)

        except Exception as e:
            log.error(f"DELETE+INSERT操作失败: {e}")
            return False

    def _delete_existing_records(self, table_name: str, data: pd.DataFrame, key_columns: list[str]) -> bool:
        """安全地删除现有记录"""
        try:
            keys_df = data[key_columns].drop_duplicates()

            # 分批构建DELETE语句以避免SQL过长
            batch_size = 500  # DELETE批次大小

            for i in range(0, len(keys_df), batch_size):
                batch_keys = keys_df.iloc[i:i + batch_size]

                if len(key_columns) == 1:
                    # 单列键
                    key_col = key_columns[0]
                    values = batch_keys[key_col].tolist()

                    # 安全处理值类型
                    if pd.api.types.is_string_dtype(batch_keys[key_col]):
                        values_str = ', '.join([f"'{str(v).replace(chr(39), chr(39)+chr(39))}'" for v in values])
                    else:
                        values_str = ', '.join(map(str, values))

                    where_clause = f"{key_col} IN ({values_str})"
                else:
                    # 多列键
                    conditions = []
                    for _, row in batch_keys.iterrows():
                        condition_parts = []
                        for col in key_columns:
                            value = row[col]
                            if pd.isna(value):
                                condition_parts.append(f"{col} IS NULL")
                            elif isinstance(value, str):
                                escaped_value = str(value).replace("'", "''")
                                condition_parts.append(f"{col} = '{escaped_value}'")
                            else:
                                condition_parts.append(f"{col} = {value}")

                        conditions.append(f"({' AND '.join(condition_parts)})")

                    where_clause = ' OR '.join(conditions)

                delete_query = f"ALTER TABLE {table_name} DELETE WHERE {where_clause}"
                self.execute_sql(delete_query)

            return True

        except Exception as e:
            log.error(f"删除现有记录时出错: {e}")
            return False

    def _support_replace_into(self, table_name: str) -> bool:
        """检查表是否支持REPLACE INTO操作"""
        if not self.client:
            log.warning("没有到ClickHouse的活动连接。")
            return False

        try:
            # 检查表引擎和主键设置
            sql = f"""
                SELECT engine, primary_key
                FROM system.tables
                WHERE database = currentDatabase() AND name = '{table_name}'
            """
            result = self.client.query(sql).result_rows

            if not result:
                return False

            engine, primary_key = result[0]

            # ReplacingMergeTree 或有主键的表支持 REPLACE
            return 'ReplacingMergeTree' in engine or bool(primary_key)

        except Exception as e:
            log.debug(f"检查REPLACE支持时出错, 使用传统方式: {e}")
            return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_connection()
