# 数据访问层
from __future__ import annotations

from typing import Any

import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client
from lntools import Logger, read_pkg_yaml

log = Logger(module_name="ClickhouseClient")

# pyright: reportOptionalMemberAccess=false


def load_db_config():
    """
    从 config.yml 文件加载数据库配置。
    """
    # 方法 1: 使用 pkg_resources（打包后）
    try:
        config = read_pkg_yaml("config/config.yml", package="getrich")
        if config:
            return config
    except Exception as e:
        log.warning(f"Failed to load config from package resources: {e}")
        return {}


# 在模块加载时读取配置
DEFAULT_DB_CONFIG = load_db_config().get("default_database", {})

# 从配置中获取默认值,如果配置不存在则使用硬编码的备用值
DEFAULT_HOST = DEFAULT_DB_CONFIG.get("host", "192.168.1.60")
DEFAULT_PORT = DEFAULT_DB_CONFIG.get("port", 8123)
DEFAULT_USER = DEFAULT_DB_CONFIG.get("user", "default")
DEFAULT_PASSWORD = DEFAULT_DB_CONFIG.get("password", "getrich")
DEFAULT_DATABASE = DEFAULT_DB_CONFIG.get("database", "default")


class ClickHouseClient:
    """
    ClickHouse 客户端类,负责数据库连接管理和基础操作。

    职责：
    - 管理数据库连接的生命周期
    - 提供底层的 SQL 执行接口
    - 提供通用的数据读写方法

    使用方式：
        # 方式1: 使用默认配置
        client = ClickHouseClient()

        # 方式2: 指定配置
        client = ClickHouseClient(host='localhost', database='mydb')

        # 方式3: 运行时修改配置
        client.configure(database='new_db', reconnect=True)
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        user: str = DEFAULT_USER,
        password: str = DEFAULT_PASSWORD,
        database: str = DEFAULT_DATABASE,
    ):
        """
        初始化 ClickHouse 客户端。

        Args:
            host: ClickHouse 主机地址
            port: ClickHouse 端口
            user: 用户名
            password: 密码
            database: 数据库名
        """
        # 存储配置
        self._config: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
        }

        # 底层连接对象
        self._connection: Client | None = None

        # 自动连接
        self.connect()

    @property
    def client(self):
        """获取底层连接对象（向后兼容）"""
        return self._connection

    def connect(self) -> bool:
        """
        连接到 ClickHouse 数据库。

        Returns:
            连接成功返回 True,否则返回 False
        """
        try:
            self._connection = clickhouse_connect.get_client(**self._config)
            log.info(
                f"Successfully connected to ClickHouse: "
                f"{self._config['host']}:{self._config['port']}/{self._config['database']}"
            )
            return True
        except Exception as e:
            log.error(f"Failed to connect to ClickHouse: {e}")
            self._connection = None
            return False

    def close(self):
        """关闭数据库连接。"""
        if self._connection:
            try:
                self._connection.close()
                self._connection = None
                log.info("ClickHouse connection closed")
            except Exception as e:
                log.error(f"Error closing ClickHouse connection: {e}")

    def configure(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        reconnect: bool = True,
    ) -> None:
        """
        更新数据库连接配置。

        Args:
            host: 新的主机地址
            port: 新的端口
            user: 新的用户名
            password: 新的密码
            database: 新的数据库名
            reconnect: 是否立即重新连接,默认 True
        """
        # 更新配置
        if host is not None:
            self._config["host"] = host
        if port is not None:
            self._config["port"] = port
        if user is not None:
            self._config["user"] = user
        if password is not None:
            self._config["password"] = password
        if database is not None:
            self._config["database"] = database

        log.info(
            f"Configuration updated: "
            f"{self._config['host']}:{self._config['port']}/{self._config['database']}"
        )

        # 如果需要重新连接
        if reconnect:
            self.close()
            self.connect()

    def get_config(self) -> dict[str, Any]:
        """
        获取当前的数据库配置。

        Returns:
            配置字典
        """
        return self._config.copy()

    def is_connected(self) -> bool:
        """
        检查是否已连接。

        Returns:
            已连接返回 True,否则返回 False
        """
        return self._connection is not None

    def ensure_connection(self) -> bool:
        """
        确保数据库连接可用,断开时自动重连。

        Returns:
            连接可用返回 True,否则返回 False
        """
        if not self.is_connected():
            log.warning("No active connection, attempting to reconnect...")
            return self.connect()
        return True

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> bool:
        """
        执行任意 SQL 语句(主要用于 DDL 或不返回数据的 DML)。

        Args:
            sql: 要执行的 SQL 语句
            params: SQL 参数化查询的参数字典

        Returns:
            成功时返回 True,失败时返回 False
        """
        if not self.ensure_connection():
            return False

        try:
            if params:
                self._connection.command(sql, parameters=params)
            else:
                self._connection.command(sql)
            return True
        except Exception as e:
            log.error(f"Error executing SQL: {e}\nSQL: {sql}")
            return False

    def execute_sql_file(self, file_path: str) -> bool:
        """
        从 SQL 文件中读取并执行多个 SQL 语句。
        主要用于执行包含多个 DDL 语句的 SQL 脚本文件。

        Args:
            file_path: SQL 文件路径

        Returns:
            全部执行成功返回 True, 遇到错误停止并返回 False
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                sql_content = f.read()

            # 简单的按分号分割, 过滤空语句
            # 注意: 这种简单的分割不支持 SQL 字符串中包含分号的情况
            # 但对于通常的 schema 定义文件来说已经足够
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]

            log.info(f"Found {len(statements)} SQL statements in {file_path}")

            for i, sql in enumerate(statements):
                log.info(f"Executing statement {i + 1}/{len(statements)}...")
                if not self.execute(sql):
                    log.error(f"Failed to execute statement {i + 1} in {file_path}")
                    return False

            log.info(f"Successfully executed all statements in {file_path}")
            return True

        except Exception as e:
            log.error(f"Error reading or executing SQL file {file_path}: {e}")
            return False

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame | None:
        """
        执行查询并以 Pandas DataFrame 形式返回结果。

        Args:
            sql: 要执行的 SQL 查询语句
            params: 查询参数

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        if not self.ensure_connection():
            return None

        try:
            result_df = self._connection.query_df(sql, parameters=params)
            log.info(f"Query executed successfully, returned {len(result_df)} rows")
            return result_df
        except Exception as e:
            log.error(f"Error executing query: {e}\nSQL: {sql}")
            return None

    def query_sql(
        self, sql_query: str, params: dict[str, Any] | None = None, use_df: bool = True
    ) -> pd.DataFrame | list[list[Any]] | None:
        """
        执行 SELECT SQL 查询并返回结果（向后兼容）。

        Args:
            sql_query: 要执行的SQL查询字符串
            params: SQL参数化查询的参数字典
            use_df: 是否将结果作为 DataFrame 返回

        Returns:
            包含查询结果的 DataFrame 或列表,如果出错则返回 None
        """
        if not self.ensure_connection():
            return None

        try:
            if use_df:
                result = self._connection.query_df(sql_query, parameters=params)
                log.info(f"SQL query executed successfully, returned {len(result)} records")
            else:
                result = self._connection.query(sql_query, parameters=params).result_rows
                log.info(f"SQL query executed successfully, returned {len(result)} records")
            return result  # type: ignore
        except Exception as e:
            log.error(f"Error executing SQL query: {e}\nSQL: {sql_query}")
            return None

    def read_data(
        self,
        table_name: str,
        columns: str = "*",
        condition: str | None = None,
        params: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order_by: str | None = None,
    ) -> pd.DataFrame | None:
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
        if not self.ensure_connection():
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
                df = self._connection.query_df(query, parameters=params)
            else:
                df = self._connection.query_df(query)
            log.info(f"Successfully read {len(df)} records from table {table_name}")
            return df
        except Exception as e:
            log.error(f"Error reading data from table {table_name}: {e}\nSQL: {query}")
            return None

    def insert_data(
        self,
        table_name: str,
        data: pd.DataFrame | list[list[Any]],
        column_names: list[str] | None = None,
        batch_size: int | None = None,
    ) -> bool:
        """
        向表中插入数据, 支持批量插入
        :param table_name: 表名
        :param data: 要插入的数据,可以是pandas DataFrame或list of lists/tuples
        :param column_names: 列名列表。如果data是DataFrame,则忽略此参数
        :param batch_size: 批量插入的批次大小, None表示一次性插入
        :return: 成功时返回True,失败时返回False
        """
        if not self.ensure_connection():
            return False

        try:
            if isinstance(data, pd.DataFrame):
                if data.empty:
                    log.warning("DataFrame is empty, no insertion needed")
                    return True
                try:
                    if batch_size and len(data) > batch_size:
                        # 分批次插入
                        for i in range(0, len(data), batch_size):
                            self._connection.insert_df(table_name, data.iloc[i : i + batch_size])
                    else:
                        self._connection.insert_df(table_name, data)
                except Exception as e:
                    log.error(f"Error inserting data into table {table_name}: {e}")
                    return False

                log.info(f"Successfully inserted {len(data)} records into table {table_name}")
                return True

            elif isinstance(data, list):  # type: ignore
                if not data:
                    log.warning("Data list is empty")
                    return False

                if column_names is None:
                    log.warning("column_names parameter is required when data is a list")
                    return False

                # 分批处理列表数据
                if batch_size and len(data) > batch_size:
                    for i in range(0, len(data), batch_size):
                        batch = data[i : i + batch_size]
                        self._connection.insert(table_name, batch, column_names=column_names)
                else:
                    self._connection.insert(table_name, data, column_names=column_names)

                log.info(f"Successfully inserted {len(data)} records into table {table_name}")
                return True
            else:
                log.warning("Unsupported data type, must be DataFrame or list")
                return False
        except Exception as e:
            log.error(f"Error inserting data into table {table_name}: {e}")
            return False

    def upsert_data(
        self,
        table_name: str,
        data: pd.DataFrame,
        key_columns: list[str],
        batch_size: int | None = None,
    ) -> bool:
        """
        向表中更新或插入数据 (Upsert)。
        如果表的ENGINE是ReplacingMergeTree, 使用insert以后自动去重的机制来update。
        如果表的ENGINE是MergeTree, 此方法首先删除与 `key_columns` 匹配的现有行, 然后插入新数据。
        注意: ClickHouse的DELETE (ALTER TABLE ... DELETE) 操作是异步执行的,
        数据不会立即被删除, 而是在后台合并过程中被清理。

        :param table_name: 表名
        :param data: 要插入的pandas DataFrame
        :param key_columns: 用于标识唯一记录的列名列表
        :param batch_size: 批量处理的批次大小, None表示一次性处理
        :return: 成功时返回True, 失败时返回False
        """
        if not self.ensure_connection():
            return False

        if not isinstance(data, pd.DataFrame) or data.empty:  # type: ignore
            log.warning("Data must be a non-empty pandas DataFrame")
            return False

        # 检查key_columns是否存在于DataFrame中
        missing_keys = [key for key in key_columns if key not in data.columns]
        if missing_keys:
            log.warning(f"Key columns {missing_keys} not found in DataFrame")
            return False

        try:
            total_rows = len(data)

            # 如果未指定批次大小或数据量较小, 一次性处理
            if batch_size is None or total_rows <= batch_size:
                return self._process_upsert_batch(table_name, data, key_columns)

            # 批量处理
            log.info(f"Starting batch upsert, total {total_rows} records, batch size {batch_size}")
            success_count = 0
            for i in range(0, total_rows, batch_size):
                batch_data = data.iloc[i : i + batch_size].copy()
                batch_num = i // batch_size + 1
                total_batches = (total_rows + batch_size - 1) // batch_size

                log.debug(
                    f"Processing batch {batch_num}/{total_batches}, record count: {len(batch_data)}"
                )

                if self._process_upsert_batch(table_name, batch_data, key_columns):
                    success_count += len(batch_data)
                else:
                    log.error(f"Batch {batch_num} processing failed")
                    return False

            log.info(f"Batch upsert completed, successfully processed {success_count} records")
            return True
        except Exception as e:
            log.error(f"Error upserting data into table {table_name}: {e}")
            return False

    def truncate_data(self, table_name: str) -> bool:
        """
        清空表中的所有数据。

        :param table_name: 要清空的表名。
        :return: 成功时返回True, 失败时返回False。
        """
        if not self.ensure_connection():
            return False

        truncate_sql = f"TRUNCATE TABLE {table_name}"

        if self.execute(truncate_sql):
            log.info(f"Table '{table_name}' has been successfully truncated")
            return True
        else:
            log.error(f"Failed to truncate table '{table_name}'")
            return False

    def drop_table(self, table_name: str, if_exists: bool = True) -> bool:
        """
        删除指定的表。

        :param table_name: 要删除的表名
        :param if_exists: 如果为True, 在表不存在时不会报错; 如果为False, 表不存在时会报错
        :return: 成功时返回True, 失败时返回False
        """
        if not self.ensure_connection():
            return False

        exists_clause = "IF EXISTS" if if_exists else ""
        drop_sql = f"DROP TABLE {exists_clause} {table_name}"

        if self.execute(drop_sql):
            log.info(f"Table '{table_name}' dropped successfully")
            return True
        else:
            log.error(f"Failed to drop table '{table_name}'")
            return False

    def _process_upsert_batch(
        self, table_name: str, batch_data: pd.DataFrame, key_columns: list[str]
    ) -> bool:
        """处理单个批次的upsert操作"""
        try:
            # 方案1: 使用 REPLACE INTO (推荐)
            if self._support_replace_into(table_name):
                return self._upsert_with_replace(table_name, batch_data)

            # 方案2: 传统的 DELETE + INSERT
            return self._upsert_with_delete_insert(table_name, batch_data, key_columns)

        except Exception as e:
            log.error(f"Error processing batch: {e}")
            return False

    def _upsert_with_replace(self, table_name: str, data: pd.DataFrame) -> bool:
        """
        使用 ReplacingMergeTree 的自动去重机制进行 upsert

        ReplacingMergeTree 会在后台合并时自动去重,根据 ORDER BY 子句中的列判断重复。
        相同排序键的行中,保留版本号（如果指定）最大的行,或最后插入的行。

        注意：去重不是立即发生的,而是在后台合并过程中异步执行。
        查询时使用 FINAL 修饰符可以强制进行去重,但会影响性能。
        """
        try:
            # ReplacingMergeTree 引擎直接插入即可,后台会自动去重
            return self.insert_data(table_name, data)

        except Exception as e:
            log.error(f"ReplacingMergeTree upsert operation failed: {e}")
            return False

    def _upsert_with_delete_insert(
        self, table_name: str, data: pd.DataFrame, key_columns: list[str]
    ) -> bool:
        """使用 DELETE + INSERT 进行upsert"""
        try:
            # 1. 构建安全的DELETE查询
            if not self._delete_existing_records(table_name, data, key_columns):
                return False

            # 2. 插入新数据
            return self.insert_data(table_name, data)

        except Exception as e:
            log.error(f"DELETE+INSERT operation failed: {e}")
            return False

    def _delete_existing_records(
        self, table_name: str, data: pd.DataFrame, key_columns: list[str]
    ) -> bool:
        """安全地删除现有记录"""
        try:
            keys_df = data[key_columns].drop_duplicates()

            # 分批构建DELETE语句以避免SQL过长
            batch_size = 500  # DELETE批次大小

            for i in range(0, len(keys_df), batch_size):
                batch_keys = keys_df.iloc[i : i + batch_size]

                if len(key_columns) == 1:
                    # 单列键
                    key_col = key_columns[0]
                    values = batch_keys[key_col].tolist()

                    # 安全处理值类型
                    if pd.api.types.is_string_dtype(batch_keys[key_col]):
                        values_str = ", ".join(
                            [f"'{str(v).replace(chr(39), chr(39) + chr(39))}'" for v in values]
                        )
                    else:
                        values_str = ", ".join(map(str, values))

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

                    where_clause = " OR ".join(conditions)

                delete_query = f"ALTER TABLE {table_name} DELETE WHERE {where_clause}"
                self.execute(delete_query)

            return True

        except Exception as e:
            log.error(f"Error deleting existing records: {e}")
            return False

    def _support_replace_into(self, table_name: str) -> bool:
        """检查表是否支持REPLACE INTO操作"""
        if not self.ensure_connection():
            return False

        try:
            # 检查表引擎和主键设置
            sql = f"""
                SELECT engine, primary_key
                FROM system.tables
                WHERE database = currentDatabase() AND name = '{table_name}'
            """
            result = self._connection.query(sql).result_rows

            if not result:
                return False

            engine, primary_key = result[0]

            # ReplacingMergeTree 或有主键的表支持 REPLACE
            return "ReplacingMergeTree" in engine or bool(primary_key)

        except Exception as e:
            log.debug(f"Error checking REPLACE support, using traditional method: {e}")
            return False

    def __enter__(self):
        """支持上下文管理器"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ):
        """退出上下文管理器时关闭连接"""
        self.close()

    def __repr__(self):
        """字符串表示"""
        return (
            f"ClickHouseClient("
            f"host='{self._config['host']}', "
            f"database='{self._config['database']}', "
            f"connected={self.is_connected()}"
            ")"
        )
