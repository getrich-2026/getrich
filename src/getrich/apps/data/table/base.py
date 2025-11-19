"""
ClickHouse 表操作基类

提供通用的表操作方法,包括创建、插入、查询、删除等。
所有具体的表类都应该继承此基类。

职责分离：
- ClickHouseClient: 单个连接管理
- ClickHouseConnectionPool: 连接池管理
- ClickHouseTable: 表操作逻辑
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd
from lntools import Logger

from getrich.libs.db.database import ClickHouseClient

if TYPE_CHECKING:
    from getrich.libs.db.pool import ClickHouseConnectionPool


# pyright: reportOptionalMemberAccess=false
# pyright: reportReturnType=false


class ClickHouseTable(ABC):
    """
    ClickHouse 表操作基类。

    职责：
    - 管理表的结构（创建、删除）
    - 提供表级别的数据操作（插入、查询、统计）
    - 提供业务相关的查询接口（由子类实现）

    使用方式：
        1. 使用默认配置的客户端：
           table = MinBarTable(table_name='min_bar')

        2. 传入已有的客户端实例（推荐,可共享连接）：
           client = ClickHouseClient()
           table1 = MinBarTable(table_name='min_bar', client=client)
           table2 = TickTable(table_name='tick_data', client=client)

        3. 使用连接池（高性能场景）：
           pool = ClickHouseConnectionPool(min_size=2, max_size=10)
           table = MinBarTable(table_name='min_bar', pool=pool)
           # 每次操作自动从池中获取/释放连接

        4. 显式传入配置创建新客户端：
           table = MinBarTable(
               table_name='min_bar',
               host='192.168.1.100',
               database='mydb'
           )
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

        Args:
            table_name: 表名
            client: ClickHouse 客户端实例
            pool: ClickHouse 连接池实例（与 client 互斥，优先使用 pool）
            host: ClickHouse 主机地址（仅在 client 和 pool 都为 None 时使用）
            port: ClickHouse 端口（仅在 client 和 pool 都为 None 时使用）
            user: 用户名（仅在 client 和 pool 都为 None 时使用）
            password: 密码（仅在 client 和 pool 都为 None 时使用）
            database: 数据库名（仅在 client 和 pool 都为 None 时使用）
            logger_name: 日志记录器名称,None 时使用类名
        """
        self.table_name = table_name

        # 初始化日志记录器
        self.logger = Logger(
            module_name=logger_name or self.__class__.__name__,
        )

        # 连接管理模式
        self._use_pool = False
        self._pool = None
        self.client = None
        self._owns_client = False

        # 模式 1: 使用连接池（优先级最高）
        if pool is not None:
            self._pool = pool
            self._use_pool = True
            self._owns_client = False
            self.logger.info("Using connection pool")

        # 模式 2: 使用传入的客户端
        elif client is not None:
            self.client = client
            self._use_pool = False
            self._owns_client = False
            self.logger.info("Using provided ClickHouse client")

        # 模式 3: 创建新的客户端
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
        """
        获取客户端实例。

        如果使用连接池，从池中获取连接；
        否则返回固定客户端。

        Returns:
            ClickHouse 客户端实例
        """
        if self._use_pool:
            return self._pool.get_connection()
        return self.client

    def _release_client(self, client: ClickHouseClient):
        """
        释放客户端实例。

        如果使用连接池，将连接释放回池中；
        否则不执行任何操作。

        Args:
            client: 要释放的客户端实例
        """
        if self._use_pool:
            self._pool.release_connection(client)

    @property
    def is_connected(self) -> bool:
        """检查客户端是否已连接"""
        if self._use_pool:
            # 连接池模式：检查池是否有可用连接
            stats = self._pool.get_stats()
            return stats["pool_size"] > 0
        return self.client is not None and self.client.is_connected()

    def close(self) -> None:
        """
        关闭数据库连接。

        注意：只有当表实例拥有客户端时才会关闭连接。
        如果客户端是从外部传入的,则不会关闭。
        """
        if self._owns_client and self.client:
            self.client.close()
            self.logger.info("ClickHouse client closed")

    @abstractmethod
    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建表（抽象方法,子类必须实现）。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def insert(self, df: pd.DataFrame, batch_size: int | None = None) -> bool:
        """
        将 Pandas DataFrame 插入到表中。

        Args:
            df: 包含要插入数据的 DataFrame
            batch_size: 批量插入的批次大小,None 表示一次性插入

        Returns:
            成功返回 True,否则返回 False
        """
        if df.empty:
            self.logger.info(f"DataFrame is empty, skipping insertion into '{self.table_name}'.")
            return True

        client = self._get_client()
        try:
            # 委托给客户端处理
            success = client.insert_data(table_name=self.table_name, data=df, batch_size=batch_size)

            if success:
                self.logger.info(f"Successfully inserted {len(df)} rows into '{self.table_name}'.")
            else:
                self.logger.error(f"Failed to insert data into '{self.table_name}'.")

            return success

        except Exception as e:
            self.logger.error(f"Failed to insert data into '{self.table_name}': {e}")
            return False
        finally:
            self._release_client(client)

    def truncate(self) -> bool:
        """
        清空表中的所有数据。

        Returns:
            成功返回 True,否则返回 False
        """
        client = self._get_client()
        try:
            success = client.truncate_data(self.table_name)
            if success:
                self.logger.info(f"Table '{self.table_name}' has been successfully truncated")
            else:
                self.logger.error(f"Failed to truncate table '{self.table_name}'")
            return success
        finally:
            self._release_client(client)

    def drop(self, if_exists: bool = True) -> bool:
        """
        删除表。

        Args:
            if_exists: 如果为 True,在表不存在时不会报错

        Returns:
            成功返回 True,否则返回 False
        """
        client = self._get_client()
        try:
            success = client.drop_table(self.table_name, if_exists=if_exists)
            if success:
                self.logger.info(f"Table '{self.table_name}' dropped successfully")
            else:
                self.logger.error(f"Failed to drop table '{self.table_name}'")
            return success
        finally:
            self._release_client(client)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame | None:
        """
        执行查询并以 Pandas DataFrame 形式返回结果。

        Args:
            sql: 要执行的 SQL 查询语句
            params: 查询参数

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        client = self._get_client()
        try:
            result = client.query(sql, params=params)
            if result is not None:
                self.logger.info(f"Query executed successfully, returned {len(result)} rows.")
            else:
                self.logger.error("Failed to execute query")
            return result
        finally:
            self._release_client(client)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> bool:
        """
        执行任意 SQL 语句（主要用于 DDL 或不返回数据的 DML）。

        Args:
            sql: 要执行的 SQL 语句
            params: SQL 参数

        Returns:
            成功返回 True,否则返回 False
        """
        client = self._get_client()
        try:
            return client.execute(sql, params=params)
        finally:
            self._release_client(client)

    def exists(self) -> bool:
        """
        检查表是否存在。

        Returns:
            表存在返回 True,否则返回 False
        """
        client = self._get_client()
        try:
            config = client.get_config()
            query = f"""
                SELECT count() as cnt
                FROM system.tables
                WHERE database = '{config["database"]}' AND name = '{self.table_name}'
            """
            result_df = client.query(query)
            if result_df is not None and len(result_df) > 0:
                return int(result_df.iloc[0]["cnt"]) > 0
            return False
        except Exception as e:
            self.logger.error(f"Failed to check table existence: {e}")
            return False
        finally:
            self._release_client(client)

    def count(self, condition: str | None = None) -> int | None:
        """
        获取表中的记录数。

        Args:
            condition: WHERE 条件子句（不包含 WHERE 关键字）

        Returns:
            记录数,如果出错则返回 None
        """
        client = self._get_client()
        try:
            if condition:
                query = f"SELECT count() as cnt FROM {self.table_name} WHERE {condition}"
            else:
                query = f"SELECT count() as cnt FROM {self.table_name}"

            result_df = client.query(query)
            if result_df is not None and len(result_df) > 0:
                return int(result_df.iloc[0]["cnt"])
            return 0
        except Exception as e:
            self.logger.error(f"Failed to count records: {e}")
            return None
        finally:
            self._release_client(client)

    def optimize(self, final: bool = False) -> bool:
        """
        优化表（合并数据分片）。

        Args:
            final: 是否执行 FINAL 合并（完全去重）

        Returns:
            成功返回 True,否则返回 False
        """
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
        """支持上下文管理器"""
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """退出上下文管理器时关闭连接"""
        self.close()

    def __repr__(self):
        """字符串表示"""
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
