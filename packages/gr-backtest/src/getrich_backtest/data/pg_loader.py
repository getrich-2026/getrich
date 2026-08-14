"""PostgreSQL-backed BarLoader implementation.

Queries ``md_bars_{asset_class}_{freq}`` tables and returns validated
Polars DataFrames.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import polars as pl

from getrich_backtest.data.adj_schema import validate_adj_schema
from getrich_backtest.data.calendar_schema import validate_calendar_schema
from getrich_backtest.data.corp_actions_schema import validate_corp_actions_schema
from getrich_backtest.data.factor_schema import validate_factor_schema
from getrich_backtest.data.instruments_schema import validate_instruments_schema
from getrich_backtest.data.loader import (
    BAR_REQUIRED_COLUMNS,
    _apply_adj_factor,
    _iter_date_chunks,
    asset_class_value,
)
from getrich_backtest.data.schema import validate_bar_schema
from getrich_backtest.exceptions import DataLoadError
from getrich_backtest.time import normalize_datetime_range
from getrich_backtest.types import AssetClass, Frequency


if TYPE_CHECKING:
    pass


@dataclass
class PgBarLoader:
    """PostgreSQL-backed ``BarLoader``.

    Reads bar data from PgSQL tables named ``md_bars_{asset_class}_{freq}``.
    Construct with a **synchronous** ``psycopg.Connection``.

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

    @staticmethod
    def _table_name(
        asset_class: str | AssetClass | None,
        freq: str,
    ) -> str:
        """Resolve the PostgreSQL table name for the given filters."""
        cls_str: str | None = None
        if asset_class is not None:
            cls_str = asset_class.value if isinstance(asset_class, AssetClass) else asset_class
        if cls_str is None:
            return f"md_bars_{freq}"
        return f"md_bars_{cls_str}_{freq}"

    @staticmethod
    def _table_name_instruments(asset_class: str | AssetClass) -> str:
        """Resolve the PostgreSQL instruments table name."""
        cls_str = asset_class_value(asset_class)
        return f"instruments_{cls_str}"

    # ------------------------------------------------------------------
    # BarLoader interface
    # ------------------------------------------------------------------

    def load_instruments(
        self,
        asset_class: str | AssetClass,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Load instrument metadata from PostgreSQL."""
        table = self._table_name_instruments(asset_class)
        cls_str = asset_class_value(asset_class)

        select_cols = ", ".join(columns) if columns is not None else "*"

        sql = f"SELECT {select_cols} FROM {table} ORDER BY symbol"

        try:
            from psycopg.rows import dict_row

            with self.conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
        except Exception as exc:
            raise DataLoadError(f"PgBarLoader instruments query failed: {exc}") from exc

        if not rows:
            return pl.DataFrame({"symbol": []}, schema={"symbol": pl.Utf8})

        df = pl.from_dicts(rows)
        return validate_instruments_schema(df, cls_str)

    @staticmethod
    def _table_name_calendar(exchange: str) -> str:
        """Resolve the PostgreSQL calendar table name."""
        return f"md_calendar_{exchange}"

    @staticmethod
    def _table_name_corp_actions() -> str:
        """Resolve the PostgreSQL corporate-actions table name."""
        return "corp_actions"

    @staticmethod
    def _table_name_factors() -> str:
        """Resolve the PostgreSQL factors table name."""
        return "factors_long"

    @staticmethod
    def _table_name_adj_factors() -> str:
        """Resolve the PostgreSQL adj-factor table name."""
        return "md_adj_factor_equity"

    def load_calendar(
        self,
        exchange: str = "SSE",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load trading calendar from PostgreSQL."""
        table = self._table_name_calendar(exchange)

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if start is not None:
            where_clauses.append("date >= %(start)s")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("date <= %(end)s")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY date"

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
        """Load adj-factor records from PostgreSQL."""
        table = self._table_name_adj_factors()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if symbols is not None:
            where_clauses.append("symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("dt >= %(start)s")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("dt <= %(end)s")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY symbol, dt"

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

        # Build SELECT clause
        if columns is not None:
            missing_required = BAR_REQUIRED_COLUMNS.difference(columns)
            if missing_required:
                missing = ", ".join(sorted(missing_required))
                raise DataLoadError(f"columns must include required bar columns: {missing}")
            select_cols = ", ".join(columns)
        else:
            select_cols = "*"

        # Build WHERE clauses
        where_clauses: list[str] = ["dt >= %(start)s", "dt < %(end)s"]
        params: dict[str, object] = {
            "start": normalized_start,
            "end": normalized_end,
        }

        if symbols is not None:
            where_clauses.append("symbol = ANY(%(symbols)s)")
            params["symbols"] = list(symbols)

        sql = (
            f"SELECT {select_cols} FROM {table}\n"
            f"WHERE {' AND '.join(where_clauses)}\n"
            f"ORDER BY dt, symbol"
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
