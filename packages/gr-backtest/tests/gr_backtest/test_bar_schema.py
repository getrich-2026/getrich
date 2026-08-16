from datetime import datetime, timezone

import polars as pl
import pytest
from gr_backtest.data.schema import validate_bar_schema
from gr_backtest.exceptions import BarSchemaError
from gr_backtest.time import get_shanghai_tz


def valid_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 9.0],
            "high": [10.5, 9.5],
            "low": [9.8, 8.8],
            "close": [10.2, 9.2],
            "volume": [1000.0, 900.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_validate_bar_schema_accepts_and_sorts_valid_bars() -> None:
    result = validate_bar_schema(valid_bars())
    assert result["dt"].to_list() == sorted(result["dt"].to_list())


def test_validate_bar_schema_rejects_missing_required_column() -> None:
    with pytest.raises(BarSchemaError, match="missing required columns"):
        validate_bar_schema(valid_bars().drop("close"))


def test_validate_bar_schema_rejects_naive_datetime() -> None:
    df = valid_bars().with_columns(pl.col("dt").dt.replace_time_zone(None))
    with pytest.raises(BarSchemaError, match="Asia/Shanghai"):
        validate_bar_schema(df)


def test_validate_bar_schema_rejects_utc_datetime() -> None:
    df = valid_bars().with_columns(pl.col("dt").dt.convert_time_zone("UTC"))
    with pytest.raises(BarSchemaError, match="Asia/Shanghai"):
        validate_bar_schema(df)


def test_validate_bar_schema_rejects_null_required_value() -> None:
    df = valid_bars().with_columns(
        pl.when(pl.arange(0, pl.len()) == 0).then(None).otherwise("close").alias("close")
    )
    with pytest.raises(BarSchemaError, match="nulls"):
        validate_bar_schema(df)


def test_validate_bar_schema_rejects_duplicate_dt_symbol() -> None:
    df = pl.concat([valid_bars(), valid_bars().head(1)])
    with pytest.raises(BarSchemaError, match="duplicate"):
        validate_bar_schema(df)


def test_validate_bar_schema_rejects_non_numeric_ohlcv() -> None:
    df = valid_bars().with_columns(pl.lit("bad").alias("open"))
    with pytest.raises(BarSchemaError, match="open must be numeric"):
        validate_bar_schema(df)


def test_validate_bar_schema_rejects_non_polars_input() -> None:
    with pytest.raises(BarSchemaError, match="polars.DataFrame"):
        validate_bar_schema({})  # type: ignore[arg-type]


def test_validate_bar_schema_rejects_utc_python_datetimes() -> None:
    df = pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)],
            "symbol": ["000001.SZ"],
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000.0],
        }
    )
    with pytest.raises(BarSchemaError, match="Asia/Shanghai"):
        validate_bar_schema(df)
