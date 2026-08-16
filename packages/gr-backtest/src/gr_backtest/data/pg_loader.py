"""PostgreSQL-backed BarLoader implementation.

对接 gr-data 的 ``market`` / ``meta`` schema（DDL 真源在 gr-db），返回校验过的
Polars DataFrame。

**行情主存是 PostgreSQL/TimescaleDB**，不是 ClickHouse（AGENTS.md §2）。
表结构以 gr-data 为准，引擎在这一层做列名与类型适配：

===================================  ==========================================
``market.*_bar_*`` / ``meta.*``      引擎 canonical
===================================  ==========================================
``instrument_id`` (FK)               ``symbol``（JOIN ``meta.instruments``）
``dt`` (``DATE`` 日线 / ``TSTZ``)    ``dt``（统一 Asia/Shanghai aware）
``amount`` ÷ ``volume``              ``vwap``
``b_xdy`` / ``f_xdy``                ``pre_factor`` / ``post_factor``
``trading_day`` / ``is_open``        ``date`` / ``is_trading_day``
===================================  ==========================================

``oi``（持仓量）与公司行为表目前不在 gr-data schema 里，请求时显式报错而不是
用默认值填充。
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import polars as pl

from gr_backtest.data.adj_schema import validate_adj_schema
from gr_backtest.data.calendar_schema import validate_calendar_schema
from gr_backtest.data.corp_actions_schema import validate_corp_actions_schema
from gr_backtest.data.factor_schema import validate_factor_schema
from gr_backtest.data.instruments_schema import validate_instruments_schema
from gr_backtest.data.loader import (
    BAR_REQUIRED_COLUMNS,
    _apply_adj_factor,
    _iter_date_chunks,
    asset_class_value,
)
from gr_backtest.data.schema import validate_bar_schema
from gr_backtest.exceptions import DataLoadError
from gr_backtest.time import normalize_datetime_range
from gr_backtest.types import AssetClass, Frequency


if TYPE_CHECKING:
    pass


@dataclass
class PgBarLoader:
    """PostgreSQL-backed ``BarLoader``.

    从 ``market.{asset}_bar_{freq}`` 读行情，用 **同步** ``psycopg.Connection`` 构造。

    Parameters
    ----------
    conn : psycopg.Connection
        A synchronous PostgreSQL connection.  The caller is responsible for
        connection lifecycle.
    """

    conn: Any  # psycopg.Connection (sync)

    # Cache of table existence checks
    _table_cache: dict[str, bool] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Table name resolution
    # ------------------------------------------------------------------

    #: 行情表按品种分表，没有「所有品种」的合并表；不指定 asset_class 时用它。
    DEFAULT_ASSET_CLASS = "stock"

    #: ``market.*_bar_*`` 里可用的可选列 -> 引擎 canonical 列名。
    #: ``amount`` 不在其中：它要和 volume 一起算成 vwap，见 ``_bar_select_sql``。
    OPTIONAL_COLUMN_MAP = {
        "pre_close": "pre_close",
        "limit_up": "limit_up",
        "limit_down": "limit_down",
        "adj_factor": "adj_factor",
    }

    @classmethod
    def _table_name(
        cls,
        asset_class: str | AssetClass | None,
        freq: str,
    ) -> str:
        """解析行情表名：``market.{asset}_bar_{freq}``。

        表结构的真源在 gr-data（``gr_db/ddl/postgres/003_market.sql``），
        引擎这边只做适配，不另立一套命名。
        """
        if asset_class is None:
            cls_str = cls.DEFAULT_ASSET_CLASS
        elif isinstance(asset_class, AssetClass):
            cls_str = asset_class.value
        else:
            cls_str = asset_class
        return f"market.{cls_str}_bar_{freq}"

    @staticmethod
    def _table_name_instruments(asset_class: str | AssetClass) -> str:
        """合约元数据表。全品种共用 ``meta.instruments``，按 ``asset`` 列过滤。"""
        return "meta.instruments"

    @staticmethod
    def _dt_expr(*, is_daily: bool) -> str:
        """时间列表达式，统一成 Asia/Shanghai 的 timestamptz。

        日线表的 ``dt`` 是 ``DATE``，分钟线是 ``TIMESTAMPTZ``。``DATE`` 与
        ``timestamptz`` 比较时 PostgreSQL 按会话时区解释，不显式钉住时区就会
        随连接配置漂移，边界日期可能整体错一天（AGENTS.md §3.1）。
        """
        if is_daily:
            return "(b.dt::timestamp AT TIME ZONE 'Asia/Shanghai')"
        return "b.dt"

    @classmethod
    def _bar_select_sql(
        cls,
        table: str,
        columns: Sequence[str] | None,
        *,
        is_daily: bool,
    ) -> str:
        """把 ``market.*_bar_*`` 的列映射成引擎的 canonical bar 列。

        映射关系（gr-data 侧是真源，引擎这边适配）::

            instrument_id  -> symbol      （JOIN meta.instruments）
            dt (DATE/TSTZ) -> dt          （统一成 Asia/Shanghai aware）
            amount, volume -> vwap        （amount / volume，volume=0 时为 NULL）

        ``oi``（持仓量）当前不在 ``market`` 表结构里。请求它时直接报错，
        **不静默填 0** —— 期货策略拿到全 0 的持仓量会算出完全错误的信号。
        """
        wanted = set(columns) if columns is not None else None

        if wanted is not None and "oi" in wanted:
            raise DataLoadError(
                "market.*_bar_* 目前没有 oi（持仓量）列；需要它请先在 gr-data 侧补列，"
                "不要用默认值代替"
            )

        dt_expr = cls._dt_expr(is_daily=is_daily)
        parts = [
            f"{dt_expr} AS dt",
            "i.symbol AS symbol",
            "b.open::double precision AS open",
            "b.high::double precision AS high",
            "b.low::double precision AS low",
            "b.close::double precision AS close",
            "b.volume::double precision AS volume",
        ]

        # vwap 用成交额除以成交量。volume 为 0（停牌、无成交）时结果无意义，
        # 用 NULLIF 让它变成 NULL 而不是除零报错。
        if wanted is None or "vwap" in wanted:
            parts.append(
                "(b.amount / NULLIF(b.volume, 0))::double precision AS vwap",
            )

        for source, canonical in cls.OPTIONAL_COLUMN_MAP.items():
            # adj_factor 只有日线表有；分钟线表没这一列，选了会直接报 UndefinedColumn。
            if source == "adj_factor" and not is_daily:
                continue
            if wanted is None or canonical in wanted:
                parts.append(f"b.{source}::double precision AS {canonical}")

        return ",\n       ".join(parts)

    # ------------------------------------------------------------------
    # BarLoader interface
    # ------------------------------------------------------------------

    def load_instruments(
        self,
        asset_class: str | AssetClass,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """从 ``meta.instruments`` 读合约元数据。

        全品种共用一张表，用 ``asset`` 列按品种过滤（原实现假设的
        ``instruments_{asset}`` 分表在 gr-data schema 里不存在）。
        """
        table = self._table_name_instruments(asset_class)
        cls_str = asset_class_value(asset_class)

        select_cols = (
            ", ".join(columns)
            if columns is not None
            else "symbol, asset, exchange, name, list_date, delist_date, status"
        )

        sql = f"SELECT {select_cols} FROM {table} WHERE asset = %(asset)s ORDER BY symbol"

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"asset": cls_str})
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader instruments query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame({"symbol": []}, schema={"symbol": pl.Utf8})

        df = pl.from_dicts(rows)
        return validate_instruments_schema(df, cls_str)

    @staticmethod
    def _table_name_calendar(exchange: str) -> str:
        """交易日历表。全交易所共用一张 ``meta.trading_calendar``，按 exchange 过滤。"""
        return "meta.trading_calendar"

    @staticmethod
    def _table_name_corp_actions() -> str:
        """分红送转等公司行为表 —— gr-data 的 schema 里**还没有**这张表。"""
        raise DataLoadError(
            "gr-data 的 PostgreSQL schema 里没有公司行为（corp actions）表。"
            "需要它请先在 gr-data 侧建表并补 importer，再回来接；"
            "在此之前请用 DataFrameBarLoader 显式传入公司行为数据。"
        )

    @staticmethod
    def _table_name_factors() -> str:
        """因子时序表 —— 在 ClickHouse（``factors_long``），不在 PostgreSQL。"""
        raise DataLoadError(
            "因子时序存在 ClickHouse 的 factors_long 表，PgBarLoader 读不到。"
            "请用 ClickHouse 客户端加载因子，或用 DataFrameBarLoader 显式传入。"
        )

    @staticmethod
    def _table_name_adj_factors() -> str:
        """复权因子表：``market.stock_adj_factor``。"""
        return "market.stock_adj_factor"

    def load_calendar(
        self,
        exchange: str = "SSE",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """从 ``meta.trading_calendar`` 读交易日历。

        列名映射（gr-data 为真源）::

            trading_day -> date
            is_open     -> is_trading_day
        """
        table = self._table_name_calendar(exchange)

        where_clauses: list[str] = ["exchange = %(exchange)s"]
        params: dict[str, object] = {"exchange": exchange}
        if start is not None:
            where_clauses.append("trading_day >= %(start)s")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("trading_day <= %(end)s")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} "
        sql = (
            "SELECT trading_day AS date,\n"
            "       is_open AS is_trading_day,\n"
            "       has_night,\n"
            "       prev_trading_day,\n"
            "       next_trading_day\n"
            f"FROM {table} {where_sql}ORDER BY trading_day"
        )

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)  # type: ignore[arg-type]
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader calendar query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame(
                {"date": [], "is_trading_day": []},
                schema={"date": pl.Date, "is_trading_day": pl.Boolean},
            )

        df = pl.from_dicts(rows)
        return validate_calendar_schema(df)

    def load_corp_actions(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load corporate actions from PostgreSQL."""
        table = self._table_name_corp_actions()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if symbols is not None:
            where_clauses.append("symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("ex_date >= %(start)s")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("ex_date <= %(end)s")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY ex_date, symbol"

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)  # type: ignore[arg-type]
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader corp_actions query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame(
                {col: [] for col in ("symbol", "ex_date", "action_type")},
                schema={"symbol": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8},
            )

        df = pl.from_dicts(rows)
        return validate_corp_actions_schema(df)

    def load_factors(
        self,
        factors: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load pre-computed factor values from PostgreSQL."""
        table = self._table_name_factors()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if factors is not None:
            where_clauses.append("factor = ANY(%(factors)s)")
            params["factors"] = list(factors)
        if symbols is not None:
            where_clauses.append("symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("dt >= %(start)s")
            params["start"] = start
        if end is not None:
            where_clauses.append("dt <= %(end)s")
            params["end"] = end

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY factor, dt, symbol"

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)  # type: ignore[arg-type]
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader factors query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame(
                {col: [] for col in ("dt", "symbol", "factor", "value")},
                schema={
                    "dt": pl.Datetime("ms", "Asia/Shanghai"),
                    "symbol": pl.Utf8,
                    "factor": pl.Utf8,
                    "value": pl.Float64,
                },
            )

        df = pl.from_dicts(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})
        return validate_factor_schema(df)

    def load_adj_factors(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """从 ``market.stock_adj_factor`` 读复权因子。

        列名映射（gr-data 为真源）::

            instrument_id -> symbol        （JOIN meta.instruments）
            begin_date    -> dt
            b_xdy         -> pre_factor    逆推累积除权因子 = 前复权
            f_xdy         -> post_factor   顺推累积除权因子 = 后复权

        ``b_xdy``／``f_xdy`` 的复权方向来自厂商文档，不是推断：见 getrich-design 仓
        ``dataapi/legacy/insight/architecture-overview.md`` §3.2 ——
        「``b_xdy`` 逆推累积除权因子（前复权，最新价系数=1）」、
        「``f_xdy`` 顺推累计除权因子（后复权，最早价系数=1）」。
        搞反方向会让整段历史价格系统性偏移，且回测不会报错。
        """
        table = self._table_name_adj_factors()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if symbols is not None:
            where_clauses.append("i.symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("a.begin_date >= %(start)s")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("a.begin_date <= %(end)s")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = (
            "SELECT i.symbol AS symbol,\n"
            "       a.begin_date AS dt,\n"
            "       a.b_xdy::double precision AS pre_factor,\n"
            "       a.f_xdy::double precision AS post_factor\n"
            f"FROM {table} a\n"
            "JOIN meta.instruments i ON i.instrument_id = a.instrument_id\n"
            f"{where_sql}ORDER BY i.symbol, a.begin_date"
        )

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)  # type: ignore[arg-type]
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader adj_factor query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame(
                {col: [] for col in ("symbol", "dt", "pre_factor", "post_factor")},
                schema={
                    "symbol": pl.Utf8,
                    "dt": pl.Date,
                    "pre_factor": pl.Float64,
                    "post_factor": pl.Float64,
                },
            )

        df = pl.from_dicts(rows)
        return validate_adj_schema(df)

    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        adj_policy: str = "none",
    ) -> pl.DataFrame:
        """Load bars for the requested left-closed/right-open range."""
        normalized_start, normalized_end = normalize_datetime_range(start, end)

        table = self._table_name(asset_class, freq)
        is_daily = freq.endswith("d")

        if columns is not None:
            missing_required = BAR_REQUIRED_COLUMNS.difference(columns)
            if missing_required:
                missing = ", ".join(sorted(missing_required))
                raise DataLoadError(f"columns must include required bar columns: {missing}")

        select_cols = self._bar_select_sql(table, columns, is_daily=is_daily)

        # 日线表的 dt 是 DATE，分钟线是 TIMESTAMPTZ。DATE 没有时区信息，
        # 直接比较会按 UTC 解释，导致边界那天错位；统一在 SQL 里把日线的 dt
        # 提升成 Asia/Shanghai 的 timestamptz 后再比较。
        dt_expr = self._dt_expr(is_daily=is_daily)

        where_clauses: list[str] = [f"{dt_expr} >= %(start)s", f"{dt_expr} < %(end)s"]
        params: dict[str, object] = {
            "start": normalized_start,
            "end": normalized_end,
        }

        if symbols is not None:
            where_clauses.append("i.symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)

        # 行情表用 instrument_id 外键，引擎的 canonical 列是 symbol，
        # 因此必须 JOIN meta.instruments 做翻译。
        sql = (
            f"SELECT {select_cols}\n"
            f"FROM {table} b\n"
            f"JOIN meta.instruments i ON i.instrument_id = b.instrument_id\n"
            f"WHERE {' AND '.join(where_clauses)}\n"
            f"ORDER BY 1, 2"
        )

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)  # type: ignore[arg-type]
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader query failed: {exc}") from exc

        if not rows:
            # Return an empty DataFrame with the right schema
            empty_df = pl.DataFrame(
                {col: [] for col in BAR_REQUIRED_COLUMNS},
                schema={
                    "dt": pl.Datetime("ms", "Asia/Shanghai"),
                    "symbol": pl.Utf8,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                },
            )
            return empty_df

        df = pl.from_dicts(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})

        result = validate_bar_schema(df)

        if adj_policy != "none":
            adj_df = self.load_adj_factors(symbols=symbols, start=start, end=end)
            if not adj_df.is_empty():
                result = _apply_adj_factor(result, adj_df, adj_policy)

        return result

    def iter_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        chunk: str = "month",
    ) -> Generator[pl.DataFrame, None, None]:
        """Load bars in monthly (or other) chunks from PostgreSQL."""
        for chunk_start, chunk_end in _iter_date_chunks(start, end, chunk=chunk):
            yield self.load_bars(
                symbols=symbols,
                start=chunk_start,
                end=chunk_end,
                freq=freq,
                asset_class=asset_class,
                columns=columns,
            )


__all__ = ["PgBarLoader"]
