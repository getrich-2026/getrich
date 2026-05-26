# 生成min_bar的类,包括创建表、读取文件、插入数据、查询数据等方法
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz

from import_data.db.clickhouse.table import ClickHouseTable

if TYPE_CHECKING:  # 避免循环导入问题
    from import_data.db.clickhouse.database import ClickHouseClient
    from import_data.db.clickhouse.pool import ClickHouseConnectionPool


class MinBarTable(ClickHouseTable):
    """
    用于操作 min_bar 表的类,负责分钟线数据的存储和查询。
    """

    def __init__(
        self,
        table_name: str = "market_data.bars_1m",
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
            table_name: 表名,默认为 'market_data.bars_1m'
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
            "symbol": "LowCardinality(String)",
            "type": "LowCardinality(String)",
            "dt": "Date",
            "bar_time": "DateTime",
            "pre_close": "Float64",
            "open": "Float64",
            "high": "Float64",
            "low": "Float64",
            "close": "Float64",
            "volume": "Float64",
            "amount": "Float64",
            "open_interest": "Float64",
            "settle": "Float64",
            "pre_settle": "Float64",
            "local_time": "DateTime64(3)",
            "provider": "LowCardinality(String)",
            "updated_at": "DateTime64(3, 'Asia/Shanghai')",
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
            symbol LowCardinality(String) COMMENT '统一代码, e.g. 000300.XSHG',
            type LowCardinality(String) CODEC(ZSTD(1)) DEFAULT '' COMMENT '标的类型',
            dt Date CODEC(Delta, ZSTD(1)) COMMENT '业务日期',
            bar_time DateTime CODEC(Delta, ZSTD(1)) COMMENT 'K 线对齐时间 (2025-12-31 10:00:00)',
            pre_close Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '前收盘价',
            open Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '开盘价',
            high Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '最高价',
            low Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '最低价',
            close Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '收盘价',
            volume Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '成交量',
            amount Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '成交额',
            open_interest Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '持仓量(期货)',
            settle Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '结算价',
            pre_settle Float64 CODEC(Delta, ZSTD(1)) DEFAULT 0 COMMENT '前结算价',
            local_time DateTime64(3) CODEC(Delta, ZSTD(1)) COMMENT '本地时间',
            provider LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',
            updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3) COMMENT '数据更新时间'
        )
        ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(dt)
        ORDER BY (symbol, dt, bar_time)
        SETTINGS index_granularity = 8192,
                min_bytes_for_wide_part = 0,
                min_rows_for_wide_part = 0,
                enable_mixed_granularity_parts = 1;
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
        columns: list[str] | None = None,
        order_by: str = "symbol, bar_time",
        limit: int | None = None,
        final: bool = False,
        is_prefix: bool = False,
    ) -> pd.DataFrame:
        """
        读取 min_bar 表中的数据,支持灵活的日期 and 标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表 or None(读取所有标的)
            start_date: 开始日期,支持 datetime 或字符串格式(如 '2020-01-01'),None 表示从 2005-01-01 开始
            end_date: 结束日期,支持 datetime 或字符串格式(如 '2025-12-31'),None 表示到当前日期
            columns: 需要查询的列名列表，None 表示查询所有列
            order_by: 排序字段,默认按 symbol 和 bar_time 排序
            limit: 限制返回的记录数,None 表示不限制
            final: 是否使用 FINAL 关键字读取最终数据版本
            is_prefix: symbols 参数是否为前缀匹配模式

        Returns:
            包含查询结果 of DataFrame (无数据时返回空 DataFrame)
        """
        # 构建条件列表
        # 设定本地时区
        local_tz = pytz.timezone("Asia/Shanghai")
        params: dict[str, Any] = {}
        where_clauses = []

        # 1. 处理 symbols 参数
        if symbols:
            if isinstance(symbols, str):
                symbols = [symbols]
            params["syms"] = symbols

            if is_prefix:
                # 前缀匹配：multiMatchAny(column, ['^prefix1', '^prefix2', ...])
                where_clauses.append("multiMatchAny(symbol, {syms:Array(String)})")
            else:
                # 精确匹配：symbol IN ('sym1', 'sym2', ...)
                where_clauses.append("symbol IN {syms:Array(String)}")

        # 2. 处理日期逻辑 (关键修复点)
        # 统一转换为带时区的 pd.Timestamp，然后再转为原生 datetime
        def to_aware_datetime(
            dt_input: datetime | str | None,
            default_val: pd.Timestamp,
            is_end: bool = False,
        ) -> datetime:
            ts = pd.to_datetime(dt_input or default_val)
            # 如果没有时区信息，加上本地时区
            ts = ts.tz_localize(local_tz) if ts.tz is None else ts.tz_convert(local_tz)

            # 如果是结束日期且只精确到天，自动补全到当天的最后一秒
            if is_end and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
                ts = ts.replace(hour=23, minute=59, second=59)

            return ts.to_pydatetime()

        start_dt_aware = to_aware_datetime(start_date, pd.Timestamp("2005-01-01"))
        end_dt_aware = to_aware_datetime(end_date, pd.Timestamp.now(), is_end=True)

        # 传给 ClickHouse 的参数使用带时区的原生 datetime
        params["start"] = start_dt_aware
        params["end"] = end_dt_aware
        where_clauses.append("bar_time >= {start:DateTime}")
        where_clauses.append("bar_time <= {end:DateTime}")

        # dt 分区裁剪 (Date 类型直接用 date 对象，不涉及秒级时区偏移)
        params["start_d"] = start_dt_aware.date()
        params["end_d"] = end_dt_aware.date()
        where_clauses.append("dt >= {start_d:Date}")
        where_clauses.append("dt <= {end_d:Date}")

        # 3. 构建查询列
        select_cols = "*"
        if columns:
            # 简单的防注入：确保列名只包含字母数字下划线
            safe_columns = [c for c in columns if c.isidentifier()]
            if safe_columns:
                select_cols = ", ".join(safe_columns)

        # 4. 构建完整的查询语句
        final_str = "FINAL" if final else ""
        query = f"SELECT {select_cols} FROM {self.table_name} {final_str}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 5. 执行查询
        try:
            result = self.query(query, params=params)
            if result.empty:
                return pd.DataFrame()
            self.logger.info(f"Read {len(result)} records from '{self.table_name}'")
            return result
        except Exception as e:
            self.logger.error(f"Error reading from '{self.table_name}': {e}")
            return pd.DataFrame()


class DayBarTable(ClickHouseTable):
    """
    用于操作 day_bar 表的类,负责日线数据的存储和查询。

    继承自 ClickHouseTable 基类,复用通用的表操作方法。
    """

    def __init__(
        self,
        table_name: str = "market_data.bars_1d",
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
            table_name: 表名,默认为 'market_data.bars_1d'
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

        # 表结构定义（与 MinBarTable 对齐类型）
        self.table_schema = {
            "symbol": "LowCardinality(String)",
            "type": "LowCardinality(String)",
            "dt": "Date",
            "pre_close": "Float64",
            "open": "Float64",
            "high": "Float64",
            "low": "Float64",
            "close": "Float64",
            "volume": "Float64",
            "amount": "Float64",
            "pct_chg": "Float64",
            "pct_chg_log": "Float64",
            "adj_factor": "Float64",
            "amplitude": "Float64",
            "limit_up": "Float64",
            "limit_down": "Float64",
            "open_interest": "Float64",
            "settle": "Float64",
            "pre_settle": "Float64",
            "trading_status": "Enum8('NORMAL'=0, 'HALTED'=1, 'UNKNOWN'=2)",
            "provider": "LowCardinality(String)",
            "updated_at": "DateTime64(3, 'Asia/Shanghai')",
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

        create_sql = f"""
        CREATE TABLE {exists_clause} {self.table_name} (
            symbol LowCardinality(String) COMMENT '统一代码',
            type LowCardinality(String) CODEC(ZSTD(1)) DEFAULT '' COMMENT '标的类型',
            dt Date CODEC(Delta, ZSTD(1)) COMMENT '业务日期',

            pre_close Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '前收盘价',
            open Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '开盘价',
            high Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '最高价',
            low Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '最低价',
            close Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '收盘价',
            volume Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '成交量',
            amount Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '成交额',
            
            pct_chg Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '涨跌幅',
            pct_chg_log Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '对数涨跌幅',
            adj_factor Float64 CODEC(ZSTD(1)) DEFAULT 1 COMMENT '复权因子',
            amplitude Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '振幅',

            limit_up Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '涨停价',
            limit_down Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '跌停价',

            open_interest Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '持仓量',
            settle Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '结算价',
            pre_settle Float64 CODEC(ZSTD(1)) DEFAULT 0 COMMENT '前结算价',

            trading_status Enum8('NORMAL'=0, 'HALTED'=1, 'UNKNOWN'=2) DEFAULT 'UNKNOWN' COMMENT '交易状态',
            provider LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',

            updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3) COMMENT '数据更新时间'
        ) ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(dt)
        ORDER BY (symbol, dt)
        SETTINGS index_granularity = 8192, 
                min_bytes_for_wide_part = 0, 
                min_rows_for_wide_part = 0, 
                enable_mixed_granularity_parts = 1;
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
        columns: list[str] | None = None,
        order_by: str = "symbol, dt",
        limit: int | None = None,
        final: bool = False,
        is_prefix: bool = False,
    ) -> pd.DataFrame:
        """
        读取 day_bar 表中的数据,支持灵活的日期 and 标的筛选。

        Args:
            symbols: 标的代码,可以是单个字符串、字符串列表 or None(读取所有标的)
            start_date: 开始日期,支持 datetime 或字符串格式(如 '2020-01-01'),None 表示从 2005-01-01 开始
            end_date: 结束日期,支持 datetime 或字符串格式(如 '2025-12-31'),None 表示到当前日期
            columns: 需要查询的列名列表，None 表示查询所有列
            order_by: 排序字段,默认按 symbol 和 dt 排序
            limit: 限制返回的记录数,None 表示不限制
            final: 是否使用 FINAL 关键字读取最终数据版本
            is_prefix: symbols 参数是否为前缀匹配模式

        Returns:
            包含查询结果 of DataFrame (无数据时返回空 DataFrame)
        """
        # 构建条件列表
        # 设定本地时区
        local_tz = pytz.timezone("Asia/Shanghai")
        params: dict[str, Any] = {}
        where_clauses = []

        # 1. 处理 symbols 参数
        if symbols:
            if isinstance(symbols, str):
                symbols = [symbols]
            params["syms"] = symbols

            if is_prefix:
                # 前缀匹配
                where_clauses.append("multiMatchAny(symbol, {syms:Array(String)})")
            else:
                # 精确匹配
                where_clauses.append("symbol IN {syms:Array(String)}")

        # 2. 处理日期逻辑
        def to_aware_datetime(
            dt_input: datetime | str | None, default_val: pd.Timestamp
        ) -> datetime:
            ts = pd.to_datetime(dt_input or default_val)
            ts = ts.tz_localize(local_tz) if ts.tz is None else ts.tz_convert(local_tz)
            return ts.to_pydatetime()

        start_dt_aware = to_aware_datetime(start_date, pd.Timestamp("2005-01-01"))
        end_dt_aware = to_aware_datetime(end_date, pd.Timestamp.now())

        # 日线表使用 dt (Date 类型) 进行筛选
        params["start"] = start_dt_aware.date()
        params["end"] = end_dt_aware.date()
        where_clauses.append("dt >= {start:Date}")
        where_clauses.append("dt <= {end:Date}")

        # 3. 构建查询列
        select_cols = "*"
        if columns:
            safe_columns = [c for c in columns if c.isidentifier()]
            if safe_columns:
                select_cols = ", ".join(safe_columns)

        # 4. 构建完整的查询语句
        final_str = "FINAL" if final else ""
        query = f"SELECT {select_cols} FROM {self.table_name} {final_str}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit:
            query += f" LIMIT {limit}"

        # 5. 执行查询
        try:
            result = self.query(query, params=params)
            if result.empty:
                return pd.DataFrame()
            self.logger.info(f"Read {len(result)} records from '{self.table_name}'")
            return result
        except Exception as e:
            self.logger.error(f"Error reading from '{self.table_name}': {e}")
            return pd.DataFrame()
