from __future__ import annotations

import logging
import re
from typing import Any, cast

import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client

from gr_data.config import ClickHouseConfig


log = logging.getLogger("ClickhouseClient")


class ClickHouseClient:
    """同步 ClickHouse 客户端；失败通过 False、None 或空表返回。"""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        *,
        config: ClickHouseConfig | None = None,
    ) -> None:
        """显式参数覆盖注入配置；初始化时建立连接。"""
        cfg = config if config is not None else ClickHouseConfig.from_env(strict=False)
        self._config: dict[str, Any] = {
            "host": cfg.host if host is None else host,
            "port": cfg.port if port is None else port,
            "user": cfg.user if user is None else user,
            "password": cfg.password if password is None else password,
            "database": cfg.database if database is None else database,
        }

        self._connection: Client | None = None

        self.connect()

    @property
    def client(self) -> Client | None:
        """获取底层连接对象（向后兼容）"""
        return self._connection

    def connect(self) -> bool:
        """连接到 ClickHouse 数据库。"""
        if self._connection is not None:
            try:
                if self._connection.ping():
                    return True
            except Exception:
                log.warning("Connection check failed, reconnecting...")
            self.close()
        try:
            self._connection = clickhouse_connect.get_client(**self._config)
            log.info(
                f"Successfully connected to ClickHouse: "
                f"{self._config['host']}:{self._config['port']}/{self._config['database']}"
            )
            return True
        except Exception as e:
            log.error(f"Failed to connect to ClickHouse: {e}")
            self.close()
            return False

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._connection:
            conn = self._connection
            # 先清空引用，确保关闭失败后重连也不会复用旧连接。
            self._connection = None
            try:
                conn.close()
                log.info("ClickHouse connection closed")
            except Exception as e:
                # 关闭失败仅记录日志，不向外抛出。
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
        """更新数据库连接配置。"""
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
            self.close()
            return False

    def execute_sql_file(self, file_path: str) -> bool:
        """顺序执行分号分隔的 SQL；不支持字符串内分号，失败即停止。"""
        try:
            with open(file_path, encoding="utf-8") as f:
                sql_content = f.read()

            statements = [s.strip() for s in sql_content.split(";") if s.strip()]

            log.info(f"Found {len(statements)} SQL statements in {file_path}")

            for i, sql in enumerate(statements):
                # 跳过纯行注释。
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
        """返回查询结果；失败返回空表，与零行结果不作区分。"""
        if not self.ensure_connection():
            return pd.DataFrame()

        try:
            assert self._connection is not None
            result_df = self._connection.query_df(sql, parameters=params)
            log.info(f"Query executed successfully, returned {len(result_df)} rows")
            return result_df
        except Exception as e:
            self.close()
            log.error(f"Error executing query: {e}\nSQL: {sql}")
            return pd.DataFrame()

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
        """按 SQL 子句读取；失败返回 None，子句须来自可信调用方。"""
        if not self.ensure_connection():
            return None

        query = f"SELECT {columns} FROM {table_name}"
        if condition:
            query += f" WHERE {condition}"
        if order_by:
            query += f" ORDER BY {order_by}"
        if limit is not None:
            query += f" LIMIT {limit}"
        if offset is not None:
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
            self.close()
            return None

    def insert_data(
        self,
        table_name: str,
        data: pd.DataFrame | list[list[Any]],
        column_names: list[str] | None = None,
        batch_size: int | None = None,
    ) -> bool:
        """分批插入；失败返回 False，已成功批次不会回滚。"""
        if batch_size is not None and (type(batch_size) is not int or batch_size <= 0):
            log.error("batch_size must be a positive integer or None")
            return False

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
                            self._connection.insert_df(table_name, data.iloc[i : i + batch_size])
                    else:
                        self._connection.insert_df(table_name, data)
                except Exception as e:
                    log.error(f"Error inserting data into table {table_name}: {e}")
                    self.close()
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
            self.close()
            log.error(f"Error inserting data into table {table_name}: {e}")
            return False

    def upsert_data(
        self,
        table_name: str,
        data: pd.DataFrame,
        key_columns: list[str],
        batch_size: int | None = None,
    ) -> bool:
        """校验替换引擎与排序键后插入；成功仅表示接受写入，不保证即时唯一。"""
        if batch_size is not None and (type(batch_size) is not int or batch_size <= 0):
            log.error("batch_size must be a positive integer or None")
            return False
        if not isinstance(data, pd.DataFrame) or data.empty:
            log.warning("Data must be a non-empty pandas DataFrame")
            return False
        if not key_columns or len(set(key_columns)) != len(key_columns):
            log.error("Upsert requires non-empty, distinct key_columns")
            return False
        if any(key not in data.columns for key in key_columns):
            log.error("Upsert key_columns must exist in the DataFrame")
            return False
        if not self.ensure_connection():
            return False
        if not self._validate_upsert_target(table_name, key_columns):
            return False
        return self.insert_data(table_name, data, batch_size=batch_size)

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

    def _validate_upsert_target(self, table_name: str, key_columns: list[str]) -> bool:
        """仅接受已知替换引擎和简单列排序键；无法确认时拒绝写入。"""
        identifier = r"[A-Za-z_][A-Za-z0-9_]*"
        if not re.fullmatch(rf"{identifier}(?:\.{identifier})?", table_name):
            log.error("Cannot verify upsert target name: %s", table_name)
            return False
        database, separator, table = table_name.partition(".")
        params = {"table": table if separator else table_name}
        database_clause = "currentDatabase()"
        if separator:
            database_clause = "%(database)s"
            params["database"] = database
        try:
            assert self._connection is not None
            rows = self._connection.query(
                "SELECT engine, sorting_key FROM system.tables "
                f"WHERE database = {database_clause} AND name = %(table)s",
                parameters=params,
            ).result_rows
            if len(rows) != 1:
                log.error("Cannot find unique upsert metadata for %s", table_name)
                return False
            engine, sorting_key = rows[0]
            if engine not in {"ReplacingMergeTree", "ReplicatedReplacingMergeTree"}:
                log.error("Unsupported upsert engine for %s: %s", table_name, engine)
                return False
            key = sorting_key.strip()
            if key.startswith("tuple(") and key.endswith(")"):
                key = key[6:-1]
            elif key.startswith("(") and key.endswith(")"):
                key = key[1:-1]
            columns = [part.strip() for part in key.split(",")]
            # 不推断表达式、别名或带转义的标识符，避免把不同键误认为相同。
            columns = [
                col[1:-1] if len(col) >= 2 and col[0] == col[-1] and col[0] in '`"' else col
                for col in columns
            ]
            if any(re.fullmatch(identifier, col) is None for col in columns):
                log.error("Cannot verify ORDER BY columns for %s: %s", table_name, sorting_key)
                return False
            if columns != key_columns:
                log.error("Upsert key_columns do not match ORDER BY for %s", table_name)
                return False
            return True
        except Exception as e:
            log.error("Failed to verify upsert metadata for %s: %s", table_name, e)
            return False

    def __enter__(self) -> ClickHouseClient:
        """支持上下文管理器"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """退出上下文管理器时关闭连接"""
        self.close()

    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"ClickHouseClient("
            f"host='{self._config['host']}', "
            f"database='{self._config['database']}', "
            f"connected={self.is_connected()}"
            ")"
        )
