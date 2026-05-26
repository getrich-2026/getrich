from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd
from import_data.core.logger import Logger

from .database import ClickHouseClient

if TYPE_CHECKING:
    from .pool import ClickHouseConnectionPool


class ClickHouseTable(ABC):
    """
    ClickHouse 表操作基类。

    职责：
    - 管理表的结构（创建、删除）
    - 提供表级别的数据操作（插入、查询、统计）
    - 提供业务相关的查询接口（由子类实现）
    """

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
    ):
        """
        初始化 ClickHouse 表操作类。
        """
        self.table_name = table_name
        self.logger = Logger(logger_name or self.__class__.__name__)

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
            assert self._pool is not None
            return self._pool.get_connection()
        assert self.client is not None
        return self.client

    def _release_client(self, client: ClickHouseClient):
        """释放客户端实例。"""
        if self._use_pool:
            assert self._pool is not None
            self._pool.release_connection(client)

    @property
    def is_connected(self) -> bool:
        """检查客户端是否已连接"""
        if self._use_pool:
            assert self._pool is not None
            stats = self._pool.get_stats()
            return stats["pool_size"] > 0
        return self.client is not None and self.client.is_connected()

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._owns_client and self.client:
            self.client.close()
            self.logger.info("ClickHouse client closed")

    @abstractmethod
    def create(self, if_not_exists: bool = True) -> bool:
        """创建表（抽象方法,子类必须实现）。"""
        ...

    def insert(self, df: pd.DataFrame, batch_size: int | None = None) -> bool:
        """将 Pandas DataFrame 插入到表中。"""
        if df.empty:
            self.logger.info(
                f"DataFrame is empty, skipping insertion into '{self.table_name}'."
            )
            return True

        client = self._get_client()
        try:
            success = client.insert_data(
                table_name=self.table_name, data=df, batch_size=batch_size
            )
            return success
        except Exception:
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
        """执行查询并以 Pandas DataFrame 形式返回结果。"""
        client = self._get_client()
        try:
            result = client.query(sql, params=params)
            return result
        finally:
            self._release_client(client)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> bool:
        """执行任意 SQL 语句。"""
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
            query = f"""
                SELECT count() as cnt
                FROM system.tables
                WHERE database = '{config["database"]}' AND name = '{self.table_name}'
            """
            result_df = client.query(query)
            if not result_df.empty:
                return int(result_df.iloc[0]["cnt"]) > 0
            return False
        except Exception as e:
            self.logger.error(f"Failed to check table existence: {e}")
            return False
        finally:
            self._release_client(client)

    def count(self, condition: str | None = None) -> int | None:
        """获取表中的记录数。"""
        client = self._get_client()
        try:
            if condition:
                query = (
                    f"SELECT count() as cnt FROM {self.table_name} WHERE {condition}"
                )
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
        """优化表（合并数据分片）。"""
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

    def __enter__(self):
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:
        self.close()

    def __repr__(self):
        client = self._get_client()
        try:
            config = client.get_config()
            return (
                f"{self.__class__.__name__}("
                f"table='{self.table_name}', "
                f"host='{config['host']}', "
                f"database='{config['database']}', "
                f"connected={self.is_connected}, "
                f"pool_mode={self._use_pool}, "
                f"owns_client={self._owns_client}"
                ")"
            )
        finally:
            self._release_client(client)
