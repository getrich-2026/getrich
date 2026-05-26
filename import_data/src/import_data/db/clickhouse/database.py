from __future__ import annotations

from typing import Any, cast

import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client
from import_data.core.logger import Logger
from import_data.core.config import settings


log = Logger("ClickhouseClient")


# 在模块加载时读取配置
DEFAULT_DB_CONFIG = settings.clickhouse

# 从配置中获取默认值,如果配置不存在则使用硬编码的备用值
DEFAULT_HOST = DEFAULT_DB_CONFIG.host
DEFAULT_PORT = DEFAULT_DB_CONFIG.port
DEFAULT_USER = DEFAULT_DB_CONFIG.user
DEFAULT_PASSWORD = DEFAULT_DB_CONFIG.password
DEFAULT_DATABASE = DEFAULT_DB_CONFIG.database


class ClickHouseClient:
    """
    ClickHouse 客户端类,负责数据库连接管理和基础操作。

    职责：
    - 管理数据库连接的生命周期
    - 提供底层的 SQL 执行接口
    - 提供通用的数据读写方法
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
    def client(self) -> Client | None:
        """获取底层连接对象（向后兼容）"""
        return self._connection

    def connect(self) -> bool:
        """
        连接到 ClickHouse 数据库。
        """
        if self._connection is not None:
            try:
                self._connection.ping()
                return True
            except Exception:
                log.warning("Connection check failed, reconnecting...")
                self._connection = None
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

    def close(self) -> None:
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
        """获取当前的数据库配置。"""
        return self._config.copy()

    def is_connected(self) -> bool:
        """检查是否已连接。"""
        return self._connection is not None

    def ensure_connection(self) -> bool:
        """确保数据库连接可用,断开时自动重连。"""
        if not self.is_connected():
            log.warning("No active connection, attempting to reconnect...")
            return self.connect()
        return True

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> bool:
        """执行任意 SQL 语句(主要用于 DDL 或不返回数据的 DML)。"""
        if not self.ensure_connection():
            return False

        try:
            assert self._connection is not None
            if params:
                self._connection.command(sql, parameters=params)
            else:
                self._connection.command(sql)
            return True
        except Exception as e:
            log.error(f"Error executing SQL: {e}\nSQL: {sql}")
            self._connection = None
            return False

    def execute_sql_file(self, file_path: str) -> bool:
        """从 SQL 文件中读取并执行多个 SQL 语句。"""
        try:
            with open(file_path, encoding="utf-8") as f:
                sql_content = f.read()

            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            log.info(f"Found {len(statements)} SQL statements in {file_path}")

            for i, sql in enumerate(statements):
                lines = sql.split("\n")
                has_content = False
                for line in lines:
                    line_content = line.strip()
                    if line_content and not line_content.startswith("--"):
                        has_content = True
                        break

                if not has_content:
                    log.debug(f"Skipping empty or comment-only statement {i + 1}")
                    continue

                log.info(f"Executing statement {i + 1}/{len(statements)}...")
                if not self.execute(sql):
                    log.error(f"Failed to execute statement {i + 1} in {file_path}")
                    return False

            log.info(f"Successfully executed all statements in {file_path}")
            return True

        except Exception as e:
            log.error(f"Error reading or executing SQL file {file_path}: {e}")
            return False

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """执行查询并以 Pandas DataFrame 形式返回结果。"""
        if not self.ensure_connection():
            return pd.DataFrame()

        try:
            assert self._connection is not None
            result_df = cast(
                pd.DataFrame, self._connection.query_df(sql, parameters=params)
            )
            log.info(f"Query executed successfully, returned {len(result_df)} rows")
            return result_df
        except Exception as e:
            self._connection = None
            log.error(f"Error executing query: {e}\nSQL: {sql}")
            return pd.DataFrame()

    def query_sql(
        self, sql_query: str, params: dict[str, Any] | None = None, use_df: bool = True
    ) -> pd.DataFrame | list[list[Any]] | None:
        """执行 SELECT SQL 查询并返回结果（向后兼容）。"""
        if not self.ensure_connection():
            return None

        try:
            assert self._connection is not None
            if use_df:
                res_df = cast(
                    pd.DataFrame,
                    self._connection.query_df(sql_query, parameters=params),
                )
                log.info(
                    f"SQL query executed successfully, returned {len(res_df)} records"
                )
                return res_df
            else:
                res_list = cast(
                    list[list[Any]],
                    self._connection.query(sql_query, parameters=params).result_rows,
                )
                log.info(
                    f"SQL query executed successfully, returned {len(res_list)} records"
                )
                return res_list
        except Exception as e:
            log.error(f"Error executing SQL query: {e}\nSQL: {sql_query}")
            self._connection = None
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
        """从表中读取数据并返回一个pandas DataFrame"""
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
            assert self._connection is not None
            if params:
                df = self._connection.query_df(query, parameters=params)
            else:
                df = self._connection.query_df(query)
            log.info(f"Successfully read {len(df)} records from table {table_name}")
            return cast(pd.DataFrame, df)
        except Exception as e:
            log.error(f"Error reading data from table {table_name}: {e}\nSQL: {query}")
            self._connection = None
            return None

    def insert_data(
        self,
        table_name: str,
        data: pd.DataFrame | list[list[Any]],
        column_names: list[str] | None = None,
        batch_size: int | None = None,
    ) -> bool:
        """向表中插入数据"""
        if not self.ensure_connection():
            return False

        try:
            assert self._connection is not None
            if isinstance(data, pd.DataFrame):
                if data.empty:
                    log.warning("DataFrame is empty, no insertion needed")
                    return True
                try:
                    if batch_size and len(data) > batch_size:
                        for i in range(0, len(data), batch_size):
                            self._connection.insert_df(
                                table_name, data.iloc[i : i + batch_size]
                            )
                    else:
                        self._connection.insert_df(table_name, data)
                except Exception as e:
                    log.error(f"Error inserting data into table {table_name}: {e}")
                    return False

                log.info(
                    f"Successfully inserted {len(data)} records into table {table_name}"
                )
                return True

            elif isinstance(data, list):
                if not data:
                    log.warning("Data list is empty")
                    return False

                if column_names is None:
                    log.warning(
                        "column_names parameter is required when data is a list"
                    )
                    return False

                if batch_size and len(data) > batch_size:
                    for i in range(0, len(data), batch_size):
                        batch = data[i : i + batch_size]
                        self._connection.insert(
                            table_name, batch, column_names=column_names
                        )
                else:
                    self._connection.insert(table_name, data, column_names=column_names)

                log.info(
                    f"Successfully inserted {len(data)} records into table {table_name}"
                )
                return True
            else:
                log.warning("Unsupported data type, must be DataFrame or list")
                return False
        except Exception as e:
            self._connection = None
            log.error(f"Error inserting data into table {table_name}: {e}")
            return False

    def upsert_data(
        self,
        table_name: str,
        data: pd.DataFrame,
        key_columns: list[str],
        batch_size: int | None = None,
    ) -> bool:
        """向表中更新或插入数据 (Upsert)"""
        if not self.ensure_connection():
            return False

        if not isinstance(data, pd.DataFrame) or data.empty:
            log.warning("Data must be a non-empty pandas DataFrame")
            return False

        missing_keys = [key for key in key_columns if key not in data.columns]
        if missing_keys:
            log.warning(f"Key columns {missing_keys} not found in DataFrame")
            return False

        try:
            total_rows = len(data)

            if batch_size is None or total_rows <= batch_size:
                return self._process_upsert_batch(table_name, data, key_columns)

            log.info(
                f"Starting batch upsert, total {total_rows} records, batch size {batch_size}"
            )
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

            log.info(
                f"Batch upsert completed, successfully processed {success_count} records"
            )
            return True
        except Exception as e:
            self._connection = None
            log.error(f"Error upserting data into table {table_name}: {e}")
            return False

    def truncate_data(self, table_name: str) -> bool:
        """清空表中的所有数据。"""
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
        """删除指定的表。"""
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
            if self._support_replace_into(table_name):
                return self._upsert_with_replace(table_name, batch_data)
            return self._upsert_with_delete_insert(table_name, batch_data, key_columns)
        except Exception as e:
            log.error(f"Error processing batch: {e}")
            return False

    def _upsert_with_replace(self, table_name: str, data: pd.DataFrame) -> bool:
        """使用 ReplacingMergeTree 的自动去重机制进行 upsert"""
        try:
            return self.insert_data(table_name, data)
        except Exception as e:
            log.error(f"ReplacingMergeTree upsert operation failed: {e}")
            return False

    def _upsert_with_delete_insert(
        self, table_name: str, data: pd.DataFrame, key_columns: list[str]
    ) -> bool:
        """使用 DELETE + INSERT 进行upsert"""
        try:
            if not self._delete_existing_records(table_name, data, key_columns):
                return False
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
            batch_size = 500

            for i in range(0, len(keys_df), batch_size):
                batch_keys = keys_df.iloc[i : i + batch_size]

                if len(key_columns) == 1:
                    key_col = key_columns[0]
                    values = batch_keys[key_col].tolist()

                    if pd.api.types.is_string_dtype(batch_keys[key_col]):
                        values_str = ", ".join(
                            [
                                f"'{str(v).replace(chr(39), chr(39) + chr(39))}'"
                                for v in values
                            ]
                        )
                    else:
                        values_str = ", ".join(map(str, values))

                    where_clause = f"{key_col} IN ({values_str})"
                else:
                    conditions = []
                    for row in batch_keys.itertuples(index=False, name=None):
                        condition_parts = []
                        for col, value in zip(key_columns, row, strict=True):
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
            assert self._connection is not None
            sql = f"""
                SELECT engine, primary_key
                FROM system.tables
                WHERE database = currentDatabase() AND name = '{table_name}'
            """
            result = self._connection.query(sql).result_rows

            if not result:
                return False

            engine, primary_key = result[0]
            return "ReplacingMergeTree" in engine or bool(primary_key)

        except Exception as e:
            log.debug(f"Error checking REPLACE support, using traditional method: {e}")
            return False

    def __enter__(self) -> ClickHouseClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"ClickHouseClient("
            f"host='{self._config['host']}', "
            f"database='{self._config['database']}', "
            f"connected={self.is_connected()}"
            ")"
        )
