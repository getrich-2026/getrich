# 生成min_bar的类,包括创建表、读取文件、插入数据、查询数据等方法
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from getrich.libs.clickhouse.table import ClickHouseTable

if TYPE_CHECKING:  # 避免循环导入问题
    from getrich.libs.clickhouse.database import ClickHouseClient
    from getrich.libs.clickhouse.pool import ClickHouseConnectionPool


class MinBarTable(ClickHouseTable):
    """
    用于操作 min_bar 表的类,负责分钟线数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。

    注意：虽然主键使用 local_time, 但添加了 date 字段的跳数索引以优化日期范围查询。
    """

    def __init__(
        self,
        table_name: str = "min_bar",
        client: ClickHouseClient | None = None,
        pool: ClickHouseConnectionPool | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        """
        初始化 MinBarTable。

        Args:
            table_name: 表名,默认为 'min_bar'
            client: ClickHouse 客户端实例,如果为 None 则自动创建
            pool: ClickHouse 连接池实例(优先级高于 client)
            host: ClickHouse 主机地址(仅在 client=None 且 pool=None 时使用)
            port: ClickHouse 端口(仅在 client=None 且 pool=None 时使用)
            user: 用户名(仅在 client=None 且 pool=None 时使用)
            password: 密码(仅在 client=None 且 pool=None 时使用)
            database: 数据库名(仅在 client=None 且 pool=None 时使用)
        """
        # 调用父类构造函数
        super().__init__(
            table_name=table_name,
            client=client,
            pool=pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            logger_name="MinBarTable",
        )

        # 表结构定义
        self.table_schema = {
            "date": "UInt32",
            "time": "Int32",
            "pre_close": "Int64",
            "open": "Int64",
            "high": "Int64",
            "low": "Int64",
            "close": "Int64",
            "volume": "Int64",
            "turnover": "Int64",
            "open_interest": "Int64",
            "pre_settle_price": "Int64",
            "settle_price": "Int64",
            "symbol": "String",
            "local_time": "DateTime64(3)",
            "insert_time": "DateTime",
        }

    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建 min_bar 表。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        # 使用 local_time 做分区依据,按 symbol+date+local_time 排序
        # 这样既支持按时间顺序查询,也优化了按日期范围查询的性能
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
            local_time DateTime64(3) CODEC(Delta, ZSTD),
            insert_time DateTime('Asia/Shanghai') DEFAULT now() CODEC(Delta, ZSTD)
        )
        ENGINE = MergeTree()
        PARTITION BY toYYYYMM(local_time)
        ORDER BY (symbol, date, local_time)
        SETTINGS index_granularity = 8192,
                 min_bytes_for_wide_part = 0,
                 min_rows_for_wide_part = 0,
                 enable_mixed_granularity_parts = 1
        """

        # 使用父类的 execute 方法
        if self.execute(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def read(
        self,
        symbols: str | list[str] | None = None,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
        order_by: str = "symbol, local_time",
        limit: int | None = None,
    ) -> pd.DataFrame | None:
        """
        读取 min_bar 表中的数据,支持灵活的日期和标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表或 None(读取所有标的)
            start_date: 开始日期,支持 datetime 或字符串格式(如 '2020-01-01'),None 表示从 2005-01-01 开始
            end_date: 结束日期,支持 datetime 或字符串格式(如 '2025-12-31'),None 表示到当前日期
            order_by: 排序字段,默认按 symbol 和 local_time 排序
            limit: 限制返回的记录数,None 表示不限制

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        # 构建条件列表
        conditions = []

        # 处理symbols参数
        if symbols is not None:
            if isinstance(symbols, str):
                # 单个标的
                conditions.append(f"symbol = '{symbols}'")
            elif isinstance(symbols, list) and len(symbols) > 0:
                # 多个标的
                symbols_str = "', '".join(symbols)
                conditions.append(f"symbol IN ('{symbols_str}')")

        # 处理日期范围
        # 如果没有指定start_date,默认从2005-01-01开始
        if start_date is None:
            start_date = "2005-01-01"

        # 转换start_date为字符串格式
        if isinstance(start_date, datetime):
            start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            start_date_str = str(start_date)

        conditions.append(f"local_time >= '{start_date_str}'")

        # 如果没有指定end_date,使用当前日期
        if end_date is None:
            end_date = datetime.now()

        # 转换end_date为字符串格式
        if isinstance(end_date, datetime):
            end_date_str = end_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            end_date_str = str(end_date)

        conditions.append(f"local_time <= '{end_date_str}'")

        # 构建完整的查询语句
        query = f"SELECT * FROM {self.table_name}"

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 使用父类的 query 方法
        result = self.query(query)

        if result is not None:
            self.logger.info(f"Successfully read {len(result)} records from '{self.table_name}'")
        else:
            self.logger.warning(
                f"No data found or error occurred while reading from '{self.table_name}'"
            )

        return result


class DayBarTable(ClickHouseTable):
    """
    用于操作 day_bar 表的类,负责日线数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。

    注意：日线数据按 (symbol, date) 排序,因为日线查询主要按日期范围进行。
    """

    def __init__(
        self,
        table_name: str = "day_bar",
        client: ClickHouseClient | None = None,
        pool: ClickHouseConnectionPool | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        """
        初始化 DayBarTable。

        Args:
            table_name: 表名,默认为 'day_bar'
            client: ClickHouse 客户端实例,如果为 None 则自动创建
            pool: ClickHouse 连接池实例(优先级高于 client)
            host: ClickHouse 主机地址(仅在 client=None 且 pool=None 时使用)
            port: ClickHouse 端口(仅在 client=None 且 pool=None 时使用)
            user: 用户名(仅在 client=None 且 pool=None 时使用)
            password: 密码(仅在 client=None 且 pool=None 时使用)
            database: 数据库名(仅在 client=None 且 pool=None 时使用)
        """
        # 调用父类构造函数
        super().__init__(
            table_name=table_name,
            client=client,
            pool=pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            logger_name="DayBarTable",
        )

        # 表结构定义（与 MinBarTable 相同）
        self.table_schema = {
            "date": "UInt32",
            "time": "Int32",
            "pre_close": "Int64",
            "open": "Int64",
            "high": "Int64",
            "low": "Int64",
            "close": "Int64",
            "volume": "Int64",
            "turnover": "Int64",
            "open_interest": "Int64",
            "pre_settle_price": "Int64",
            "settle_price": "Int64",
            "symbol": "String",
            "local_time": "DateTime64(3)",
            "insert_time": "DateTime",
        }

    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建 day_bar 表。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        # Day bar data partitioned by year, sorted by symbol+date for optimized date range queries
        # Using local_time for partitioning (DateTime64 type supports toYear function)
        # date field as part of primary key for efficient index utilization
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
            local_time DateTime64(3) CODEC(Delta, ZSTD),
            insert_time DateTime('Asia/Shanghai') DEFAULT now() CODEC(Delta, ZSTD)
        )
        ENGINE = MergeTree()
        PARTITION BY toYear(local_time)
        ORDER BY (symbol, date)
        SETTINGS index_granularity = 8192,
             min_bytes_for_wide_part = 0,
             min_rows_for_wide_part = 0,
             enable_mixed_granularity_parts = 1
        """

        # Use parent class execute method
        if self.execute(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def read(
        self,
        symbols: str | list[str] | None = None,
        start_date: int | str | None = None,
        end_date: int | str | None = None,
        order_by: str = "symbol, date",
        limit: int | None = None,
    ) -> pd.DataFrame | None:
        """
        读取 day_bar 表中的数据,支持灵活的日期和标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表或 None(读取所有标的)
            start_date: 开始日期,支持整数格式(如 20200101)或字符串格式(如 '2020-01-01'),
                       None 表示从 20050101 开始
            end_date: 结束日期,支持整数格式(如 20251231)或字符串格式(如 '2025-12-31'),
                     None 表示到当前日期
            order_by: 排序字段,默认按 symbol 和 date 排序
            limit: 限制返回的记录数,None 表示不限制

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        # 构建条件列表
        conditions = []

        # 处理symbols参数
        if symbols is not None:
            if isinstance(symbols, str):
                # 单个标的
                conditions.append(f"symbol = '{symbols}'")
            elif isinstance(symbols, list) and len(symbols) > 0:
                # 多个标的
                symbols_str = "', '".join(symbols)
                conditions.append(f"symbol IN ('{symbols_str}')")

        # 处理日期范围 - 使用 date 字段(UInt32)进行比较
        # 如果没有指定start_date,默认从20050101开始
        if start_date is None:
            start_date_int = 20050101
        else:
            # 转换为整数格式
            if isinstance(start_date, int):
                start_date_int = start_date
            else:
                # 字符串格式如 '2020-01-01' 转换为 20200101
                start_date_str = str(start_date).replace("-", "")
                start_date_int = int(start_date_str)

        conditions.append(f"date >= {start_date_int}")

        # 如果没有指定end_date,使用当前日期
        if end_date is None:
            end_date_int = int(datetime.now().strftime("%Y%m%d"))
        else:
            # 转换为整数格式
            if isinstance(end_date, int):
                end_date_int = end_date
            else:
                # 字符串格式如 '2025-12-31' 转换为 20251231
                end_date_str = str(end_date).replace("-", "")
                end_date_int = int(end_date_str)

        conditions.append(f"date <= {end_date_int}")

        # 构建完整的查询语句
        query = f"SELECT * FROM {self.table_name}"

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 使用父类的 query 方法
        result = self.query(query)

        if result is not None:
            self.logger.info(f"Successfully read {len(result)} records from '{self.table_name}'")
        else:
            self.logger.warning(
                f"No data found or error occurred while reading from '{self.table_name}'"
            )

        return result


class CodeInfoTable(ClickHouseTable):
    """
    用于操作 code_info 表的类,负责合约/标的信息数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。

    注意: code_info 表存储合约的基本信息，按 symbol 排序以优化查询。
    """

    def __init__(
        self,
        table_name: str = "code_info",
        client: ClickHouseClient | None = None,
        pool: ClickHouseConnectionPool | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        """
        初始化 CodeInfoTable。

        Args:
            table_name: 表名,默认为 'code_info'
            client: ClickHouse 客户端实例,如果为 None 则自动创建
            pool: ClickHouse 连接池实例(优先级高于 client)
            host: ClickHouse 主机地址(仅在 client=None 且 pool=None 时使用)
            port: ClickHouse 端口(仅在 client=None 且 pool=None 时使用)
            user: 用户名(仅在 client=None 且 pool=None 时使用)
            password: 密码(仅在 client=None 且 pool=None 时使用)
            database: 数据库名(仅在 client=None 且 pool=None 时使用)
        """
        # 调用父类构造函数
        super().__init__(
            table_name=table_name,
            client=client,
            pool=pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            logger_name="CodeInfoTable",
        )

        # 表结构定义
        self.table_schema = {
            "sec_type": "Int32",
            "sec_name": "String",
            "date": "UInt32",
            "high_limited": "Int64",
            "low_limited": "Int64",
            "multiplier": "Int32",
            "margin_ratio": "Int32",
            "price_tick": "Int64",
            "capital": "Int64",
            "cap_change_date": "UInt32",
            "trade_date_in": "UInt32",
            "trade_date_out": "UInt32",
            "is_halt": "Int8",
            "margin_unit": "Int32",
            "margin_ratio_param1": "Int32",
            "margin_ratio_param2": "Int32",
            "sec_name_ext": "String",
            "symbol": "String",
            "insert_time": "DateTime",
        }

    def create(self, if_not_exists: bool = True) -> bool:
        """
        创建 code_info 表。

        Args:
            if_not_exists: 如果表已存在,是否跳过创建

        Returns:
            创建成功返回 True,否则返回 False
        """
        exists_clause = "IF NOT EXISTS" if if_not_exists else ""

        # code_info table sorted by symbol for efficient contract queries
        # Using ReplacingMergeTree to support data updates (latest record for same symbol is kept)
        create_sql = f"""
        CREATE TABLE {exists_clause} {self.table_name}
        (
            sec_type Int32,
            sec_name String,
            date UInt32,
            high_limited Int64,
            low_limited Int64,
            multiplier Int32,
            margin_ratio Int32,
            price_tick Int64,
            capital Int64,
            cap_change_date UInt32,
            trade_date_in UInt32,
            trade_date_out UInt32,
            is_halt Int8,
            margin_unit Int32,
            margin_ratio_param1 Int32,
            margin_ratio_param2 Int32,
            sec_name_ext String,
            symbol String,
            insert_time DateTime('Asia/Shanghai') DEFAULT now()
        )
        ENGINE = ReplacingMergeTree()
        ORDER BY symbol
        SETTINGS index_granularity = 8192
        """

        # Use parent class execute method
        if self.execute(create_sql):
            self.logger.info(f"Table '{self.table_name}' created successfully.")
            return True
        else:
            self.logger.error(f"Failed to create table '{self.table_name}'.")
            return False

    def read(
        self,
        symbols: str | list[str] | None = None,
        sec_type: int | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame | None:
        """
        读取 code_info 表中的数据,支持按标的代码和证券类型筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表或 None(读取所有标的)
            sec_type: 证券类型筛选,None 表示不限制
            limit: 限制返回的记录数,None 表示不限制

        Returns:
            包含查询结果的 DataFrame,如果出错则返回 None
        """
        # 构建条件列表
        conditions = []

        # 处理 symbols 参数
        if symbols is not None:
            if isinstance(symbols, str):
                # 单个标的
                conditions.append(f"symbol = '{symbols}'")
            elif isinstance(symbols, list) and len(symbols) > 0:
                # 多个标的
                symbols_str = "', '".join(symbols)
                conditions.append(f"symbol IN ('{symbols_str}')")

        # 处理 sec_type 参数
        if sec_type is not None:
            conditions.append(f"sec_type = {sec_type}")

        # 构建完整的查询语句
        query = f"SELECT * FROM {self.table_name}"

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY symbol"

        if limit:
            query += f" LIMIT {limit}"

        # 使用父类的 query 方法
        result = self.query(query)

        if result is not None:
            self.logger.info(f"Successfully read {len(result)} records from '{self.table_name}'")
        else:
            self.logger.warning(
                f"No data found or error occurred while reading from '{self.table_name}'"
            )

        return result

    def get_by_symbol(self, symbol: str) -> pd.Series | None:
        """
        获取指定标的的合约信息。

        Args:
            symbol: 标的代码

        Returns:
            包含合约信息的 Series,如果不存在则返回 None
        """
        result = self.read(symbols=symbol, limit=1)
        if result is not None and len(result) > 0:
            return result.iloc[0]
        return None
