"""DuckDB-backed BarLoader implementation.

Uses an in-memory or file-backed DuckDB database for lightweight
bar data loading.  Data must be pre-registered via ``register_df()``
or ``register_parquet()`` before calling ``load_bars()``.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

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
    import duckdb


@dataclass
class DuckDBBarLoader:
    """DuckDB-backed ``BarLoader``.

    Queries data from a DuckDB database.  Data must be registered first
    via ``register_df()`` (Polars DataFrames) or ``register_parquet()``
    (Parquet files).  The table naming convention follows the PgSQL schema
    (``md_bars_{asset_class}_{freq}``) for consistency, but tables can be
    registered under any name.

    Parameters
    ----------
    database : str
        DuckDB database path.  Use ``":memory:"`` for an in-memory database
        (default).  File-backed databases persist across sessions.
    """

    database: str = ":memory:"

    _conn: duckdb.DuckDBPyConnection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        import duckdb

        object.__setattr__(self, "_conn", duckdb.connect(self.database))

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register_df(self, table_name: str, df: pl.DataFrame) -> None:
        """Register a Polars DataFrame as a virtual table in DuckDB."""
        self._conn.register(table_name, df)

    def register_parquet(self, table_name: str, path: str) -> None:
        """Register a Parquet file as a virtual table in DuckDB.

        Parameters
        ----------
        table_name : str
            Name to use for the virtual table.
        path : str
            Path to the Parquet file.
        """
        self._conn.execute(f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM '{path}'")

    # ------------------------------------------------------------------
    # Table name resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _table_name(
        asset_class: str | AssetClass | None,
        freq: str,
    ) -> str:
        """Resolve the DuckDB table name for the given filters."""
        cls_str: str | None = None
        if asset_class is not None:
            cls_str = asset_class.value if isinstance(asset_class, AssetClass) else asset_class
        if cls_str is None:
            return f"md_bars_{freq}"
        return f"md_bars_{cls_str}_{freq}"

    @staticmethod
    def _table_name_instruments(asset_class: str | AssetClass) -> str:
        """Resolve the DuckDB instruments table name."""
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
        """Load instrument metadata from DuckDB."""
        table = self._table_name_instruments(asset_class)
        cls_str = asset_class_value(asset_class)

        select_cols = ", ".join(columns) if columns is not None else "*"

        sql = f"SELECT {select_cols} FROM {table} ORDER BY symbol"

        try:
            rel = self._conn.execute(sql)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader instruments query failed: {exc}") from exc

        if result.is_empty():
            return result

        return validate_instruments_schema(result, cls_str)

    @staticmethod
    def _table_name_calendar(exchange: str) -> str:
        """Resolve the DuckDB calendar table name."""
        return f"md_calendar_{exchange}"

    @staticmethod
    def _table_name_corp_actions() -> str:
        """Resolve the DuckDB corporate-actions table name."""
        return "corp_actions"

    @staticmethod
    def _table_name_factors() -> str:
        """Resolve the DuckDB factors table name."""
        return "factors_long"

    @staticmethod
    def _table_name_adj_factors() -> str:
        """Resolve the DuckDB adj-factor table name."""
        return "md_adj_factor_equity"

    def load_calendar(
        self,
        exchange: str = "SSE",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load trading calendar from DuckDB."""
        table = self._table_name_calendar(exchange)

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if start is not None:
            where_clauses.append("date >= $start")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("date <= $end")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY date"

        try:
            rel = self._conn.execute(sql, params)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader calendar query failed: {exc}") from exc

        if result.is_empty():
            return result

        return validate_calendar_schema(result)

    def load_corp_actions(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load corporate actions from DuckDB."""
        table = self._table_name_corp_actions()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if symbols is not None:
            where_clauses.append("symbol = ANY($symbols)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("ex_date >= $start")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("ex_date <= $end")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY ex_date, symbol"

        try:
            rel = self._conn.execute(sql, params)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader corp_actions query failed: {exc}") from exc

        if result.is_empty():
            return result

        return validate_corp_actions_schema(result)

    def load_factors(
        self,
        factors: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load pre-computed factor values from DuckDB."""
        table = self._table_name_factors()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if factors is not None:
            where_clauses.append("factor = ANY($factors)")
            params["factors"] = list(factors)
        if symbols is not None:
            where_clauses.append("symbol = ANY($symbols)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("dt >= $start")
            params["start"] = start
        if end is not None:
            where_clauses.append("dt <= $end")
            params["end"] = end

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY factor, dt, symbol"

        try:
            rel = self._conn.execute(sql, params)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader factors query failed: {exc}") from exc

        if result.is_empty():
            return result

        if "dt" in result.columns:
            result = result.with_columns(pl.col("dt").cast(pl.Datetime("ms", "Asia/Shanghai")))

        return validate_factor_schema(result)

    def load_adj_factors(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load adj-factor records from DuckDB."""
        table = self._table_name_adj_factors()

        where_clauses: list[str] = []
        params: dict[str, object] = {}
        if symbols is not None:
            where_clauses.append("symbol = ANY($symbols)")
            params["symbols"] = list(symbols)
        if start is not None:
            where_clauses.append("dt >= $start")
            params["start"] = start.date()
        if end is not None:
            where_clauses.append("dt <= $end")
            params["end"] = end.date()

        where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""
        sql = f"SELECT * FROM {table} {where_sql}ORDER BY symbol, dt"

        try:
            rel = self._conn.execute(sql, params)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader adj_factor query failed: {exc}") from exc

        if result.is_empty():
            return result

        return validate_adj_schema(result)

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
        where_clauses: list[str] = ["dt >= $start", "dt < $end"]
        params: dict[str, object] = {
            "start": normalized_start,
            "end": normalized_end,
        }

        if symbols is not None:
            where_clauses.append("symbol = ANY($symbols)")
            params["symbols"] = list(symbols)

        sql = (
            f"SELECT {select_cols} FROM {table}\n"
            f"WHERE {' AND '.join(where_clauses)}\n"
            f"ORDER BY dt, symbol"
        )

        try:
            rel = self._conn.execute(sql, params)
            result: pl.DataFrame = pl.from_pandas(rel.df())
        except Exception as exc:
            raise DataLoadError(f"DuckDBBarLoader query failed: {exc}") from exc

        if result.is_empty():
            return result

        # Ensure datetime column has proper timezone metadata
        if "dt" in result.columns:
            result = result.with_columns(pl.col("dt").cast(pl.Datetime("ms", "Asia/Shanghai")))

        result = validate_bar_schema(result)

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
        """Load bars in monthly (or other) chunks from DuckDB."""
        for chunk_start, chunk_end in _iter_date_chunks(start, end, chunk=chunk):
            yield self.load_bars(
                symbols=symbols,
                start=chunk_start,
                end=chunk_end,
                freq=freq,
                asset_class=asset_class,
                columns=columns,
            )


__all__ = ["DuckDBBarLoader"]
