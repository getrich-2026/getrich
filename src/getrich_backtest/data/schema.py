"""Canonical Polars bar schema validation."""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl

from getrich_backtest.exceptions import BarSchemaError


BAR_DT_COLUMN = "dt"
BAR_SYMBOL_COLUMN = "symbol"
BAR_REQUIRED_COLUMNS = frozenset(
    {
        BAR_DT_COLUMN,
        BAR_SYMBOL_COLUMN,
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
)
BAR_OPTIONAL_COLUMNS = frozenset(
    {
        "vwap",
        "oi",
        "asset_class",
        "exchange",
        "freq",
        "amount",
        "settlement",
        "adj_factor",
        "limit_up",
        "limit_down",
        "is_suspended",
        "is_st",
    }
)
_PRICE_COLUMNS = ("open", "high", "low", "close")
_NUMERIC_DTYPES = {
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
    pl.Float32,
    pl.Float64,
    pl.Decimal,
}
_SYMBOL_DTYPES = {pl.String, pl.Utf8, pl.Categorical}


def _format_errors(errors: Iterable[str]) -> str:
    return "; ".join(errors)


def _is_numeric_dtype(dtype: pl.DataType) -> bool:
    return dtype in _NUMERIC_DTYPES or isinstance(dtype, pl.Decimal)


def _validate_datetime_dtype(dtype: pl.DataType, errors: list[str]) -> None:
    if not isinstance(dtype, pl.Datetime):
        errors.append("dt must be a Polars Datetime column")
        return
    if dtype.time_zone != "Asia/Shanghai":
        errors.append("dt timezone must be Asia/Shanghai")


def validate_bar_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and return bars sorted by ``dt`` and ``symbol``.

    The canonical bar table is a Polars long table. This function is strict at
    engine boundaries: it rejects missing columns, naive or non-Shanghai
    datetimes, nulls in required columns, duplicate ``(dt, symbol)`` pairs, and
    non-numeric OHLCV columns.
    """
    if not isinstance(df, pl.DataFrame):
        raise BarSchemaError("bar data must be a polars.DataFrame")

    errors: list[str] = []
    missing_columns = sorted(BAR_REQUIRED_COLUMNS.difference(df.columns))
    if missing_columns:
        errors.append(f"missing required columns: {', '.join(missing_columns)}")
        raise BarSchemaError(_format_errors(errors))

    schema = df.schema
    _validate_datetime_dtype(schema[BAR_DT_COLUMN], errors)

    symbol_dtype = schema[BAR_SYMBOL_COLUMN]
    if symbol_dtype not in _SYMBOL_DTYPES:
        errors.append("symbol must be a string or categorical column")

    for column in (*_PRICE_COLUMNS, "volume"):
        if not _is_numeric_dtype(schema[column]):
            errors.append(f"{column} must be numeric")

    null_counts = df.select(pl.col(sorted(BAR_REQUIRED_COLUMNS)).null_count()).row(0, named=True)
    columns_with_nulls = [column for column, count in null_counts.items() if count > 0]
    if columns_with_nulls:
        errors.append(f"required columns contain nulls: {', '.join(sorted(columns_with_nulls))}")

    duplicate_count = df.select(
        pl.struct([BAR_DT_COLUMN, BAR_SYMBOL_COLUMN]).is_duplicated().sum().alias("duplicates")
    ).item()
    if duplicate_count:
        errors.append("duplicate (dt, symbol) rows are not allowed")

    if errors:
        raise BarSchemaError(_format_errors(errors))

    return df.sort([BAR_DT_COLUMN, BAR_SYMBOL_COLUMN])
