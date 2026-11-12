# pyright: reportOptionalMemberAccess=false
# pyright: reportReturnType=false
"""ClickHouse 表操作封装。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd

from .database import ClickHouseClient


if TYPE_CHECKING:
    from .pool import ClickHouseConnectionPool


class ClickHouseTable(ABC):
    """封装表操作，支持外部客户端或连接池。"""

    def __init__(
        self,
        table_name: str,
        client: ClickHouseClient | None = None,
        pool: ClickHouseConnectionPool | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        logger_name: str | None = None,
    ) -> None:
        """优先使用 pool，其次 client，否则创建并持有客户端。"""
        self.table_name = table_name

        self.logger = logging.getLogger(logger_name or self.__class__.__name__)

        self._use_pool = False
        self._pool = None
        self.client = None
        self._owns_client = False

        if pool is not None:
            self._pool = pool
            self._use_pool = True
            self._owns_client = False
            self.logger.info("Using connection pool")

        elif client is not None:
            self.client = client
            self._use_pool = False
            self._owns_client = False
            self.logger.info("Using provided ClickHouse client")

        else:
            client_kwargs = {}
            if host is not None:
                client_kwargs["host"] = host
            if port is not None:
                client_kwargs["port"] = port
            if user is not None:
                client_kwargs["user"] = user
            if password is not None:
                client_kwargs["password"] = password
            if database is not None:
                client_kwargs["database"] = database

            self.client = ClickHouseClient(**client_kwargs)
            self._use_pool = False
            self._owns_client = True
            self.logger.info("Created new ClickHouse client")

    def _get_client(self) -> ClickHouseClient:
        """获取客户端实例。"""
        if self._use_pool:
            return self._pool.get_connection()
        return self.client

    def _release_client(self, client: ClickHouseClient) -> None:
        """释放客户端实例。"""
        if self._use_pool:
            self._pool.release_connection(client)

    @property
    def is_connected(self) -> bool:
        """检查客户端是否已连接"""
        if self._use_pool:
            stats = self._pool.get_stats()
            return stats["pool_size"] > 0
        return self.client is not None and self.client.is_connected()

    def close(self) -> None:
        """仅关闭本实例创建的客户端。"""
        if self._owns_client and self.client:
            self.client.close()
            self.logger.info("ClickHouse client closed")

    @abstractmethod
    def create(self, if_not_exists: bool = True) -> bool:
        """创建表（抽象方法,子类必须实现）。"""
        ...  # pylint: disable=unnecessary-ellipsis

    def insert(self, df: pd.DataFrame, batch_size: int | None = None) -> bool:
        """将 Pandas DataFrame 插入到表中。"""
        if df.empty:
            self.logger.info(f"DataFrame is empty, skipping insertion into '{self.table_name}'.")
            return True

        client = self._get_client()
        try:
            success = client.insert_data(table_name=self.table_name, data=df, batch_size=batch_size)
            return success

        except Exception as e:
            self.logger.error("Failed to insert into %s: %s", self.table_name, e)
            return False
        finally:
            self._release_client(client)

    def truncate(self) -> bool:
        """清空表中的所有数据。"""
        client = self._get_client()
        try:
            success = client.truncate_data(self.table_name)
            return success
        finally:
            self._release_client(client)

    def drop(self, if_exists: bool = True) -> bool:
        """删除表。"""
        client = self._get_client()
        try:
            success = client.drop_table(self.table_name, if_exists=if_exists)
            return success
        finally:
            self._release_client(client)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """返回查询结果；底层查询失败也返回空表。"""
        client = self._get_client()
        try:
            result = client.query(sql, params=params)
            return result
        finally:
            self._release_client(client)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> bool:
        """执行任意 SQL 语句（主要用于 DDL 或不返回数据的 DML）。"""
        client = self._get_client()
        try:
            return client.execute(sql, params=params)
        finally:
            self._release_client(client)

    def exists(self) -> bool:
        """检查表是否存在。"""
        client = self._get_client()
        try:
            config = client.get_config()
            database, separator, table = self.table_name.partition(".")
            if not separator:
                database, table = config["database"], self.table_name
            query = """
                SELECT count() as cnt FROM system.tables
                WHERE database = %(database)s AND name = %(table)s
            """
            result_df = client.query(query, params={"database": database, "table": table})
            if not result_df.empty:
                return int(result_df.iloc[0]["cnt"]) > 0
            return False
        except Exception as e:
            self.logger.error(f"Failed to check table existence: {e}")
            return False
        finally:
            self._release_client(client)

    def count(self, condition: str | None = None) -> int | None:
        """按可信 WHERE 子句计数；异常返回 None。"""
        client = self._get_client()
        try:
            if condition:
                query = f"SELECT count() as cnt FROM {self.table_name} WHERE {condition}"
            else:
                query = f"SELECT count() as cnt FROM {self.table_name}"

            result_df = client.query(query)
            if not result_df.empty:
                return int(result_df.iloc[0]["cnt"])
            return 0
        except Exception as e:
            self.logger.error(f"Failed to count records: {e}")
            return None
        finally:
            self._release_client(client)

    def optimize(self, final: bool = False) -> bool:
        """手动合并分片；FINAL 开销较大，不保证所有引擎去重。"""
        client = self._get_client()
        try:
            final_clause = "FINAL" if final else ""
            sql = f"OPTIMIZE TABLE {self.table_name} {final_clause}"
            success = client.execute(sql)
            if success:
                self.logger.info(f"Table '{self.table_name}' optimized successfully")
            else:
                self.logger.error(f"Failed to optimize table '{self.table_name}'")
            return success
        except Exception as e:
            self.logger.error(f"Failed to optimize table '{self.table_name}': {e}")
            return False
        finally:
            self._release_client(client)

    def __enter__(self) -> ClickHouseTable:
        """支持上下文管理器"""
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """退出上下文管理器时关闭连接"""
        self.close()

    def __repr__(self) -> str:
        """字符串表示"""
        config = self.client.get_config() if self.client is not None else {}
        return (
            f"{self.__class__.__name__}("
            f"table={self.table_name!r}, "
            f"host={config.get('host')!r}, "
            f"database={config.get('database')!r}, "
            f"connected={self.is_connected}, "
            f"pool_mode={self._use_pool}, "
            f"owns_client={self._owns_client})"
        )
