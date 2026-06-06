from datetime import datetime

import polars as pl
import pytest

from getrich_backtest import (
    AssetClass,
    BarSchemaError,
    DataFrameBarLoader,
    DataLoadError,
    TimezoneError,
    get_shanghai_tz,
)


def valid_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ", "600000.SH"],
            "open": [9.0, 10.0, 11.0, 20.0],
            "high": [9.5, 10.5, 11.5, 20.5],
            "low": [8.8, 9.8, 10.8, 19.8],
            "close": [9.2, 10.2, 11.2, 20.2],
            "volume": [900.0, 1000.0, 1100.0, 2000.0],
            "freq": ["1d", "1d", "1d", "1d"],
            "asset_class": ["equity_a", "equity_a", "equity_a", "equity_a"],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_dataframe_bar_loader_constructor_validates_input() -> None:
    df = valid_bars().drop("close")
    with pytest.raises(BarSchemaError):
        DataFrameBarLoader(df)


def test_load_bars_filters_left_closed_right_open_range() -> None:
    loader = DataFrameBarLoader(valid_bars())
    start = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz())
    result = loader.load_bars(None, start, end)
    assert result["dt"].max() < end
    assert result.height == 3


def test_load_bars_filters_symbols() -> None:
    loader = DataFrameBarLoader(valid_bars())
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 4, tzinfo=get_shanghai_tz())
    result = loader.load_bars(["600000.SH"], start, end)
    assert result["symbol"].to_list() == ["600000.SH"]


def test_load_bars_filters_freq_and_asset_class() -> None:
    loader = DataFrameBarLoader(valid_bars())
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 4, tzinfo=get_shanghai_tz())
    result = loader.load_bars(None, start, end, freq="1d", asset_class=AssetClass.EQUITY_A)
    assert result.height == 4


def test_load_bars_works_when_freq_column_missing_for_any_freq() -> None:
    """Without freq column, loader trusts the caller — any freq passes through."""
    loader = DataFrameBarLoader(valid_bars().drop("freq"))
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 4, tzinfo=get_shanghai_tz())
    # Should NOT raise — loader trusts provided data
    for freq in ("1m", "5m", "15m", "30m", "60m", "1h", "1d"):
        result = loader.load_bars(None, start, end, freq=freq)
        assert result.height == 4


def test_load_bars_filters_by_freq_column_when_present() -> None:
    """When freq column exists, it's used as filter — including new frequencies."""
    # Create bars with mixed frequencies including new ones
    tz = get_shanghai_tz()
    df = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 1, 9, 35, tzinfo=tz),
                datetime(2026, 1, 1, 9, 40, tzinfo=tz),
            ],
            "symbol": ["A", "A", "A"],
            "open": [10.0, 10.1, 10.2],
            "high": [11.0, 11.1, 11.2],
            "low": [9.0, 9.1, 9.2],
            "close": [10.5, 10.6, 10.7],
            "volume": [1000.0, 1100.0, 1200.0],
            "freq": ["5m", "5m", "1d"],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    loader = DataFrameBarLoader(df)
    start = datetime(2026, 1, 1, tzinfo=tz)
    end = datetime(2026, 1, 2, tzinfo=tz)

    # Filter for 5m → should return 2 rows
    result_5m = loader.load_bars(None, start, end, freq="5m")
    assert result_5m.height == 2
    assert result_5m["freq"].unique().to_list() == ["5m"]

    # Filter for 1d → should return 1 row
    result_1d = loader.load_bars(None, start, end, freq="1d")
    assert result_1d.height == 1
    assert result_1d["freq"].unique().to_list() == ["1d"]


def test_load_bars_raises_when_asset_class_column_missing() -> None:
    loader = DataFrameBarLoader(valid_bars().drop("asset_class"))
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 4, tzinfo=get_shanghai_tz())
    with pytest.raises(DataLoadError, match="asset_class"):
        loader.load_bars(None, start, end, asset_class="equity_a")


def test_load_bars_raises_when_projection_omits_required_columns() -> None:
    loader = DataFrameBarLoader(valid_bars())
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    end = datetime(2026, 1, 4, tzinfo=get_shanghai_tz())
    with pytest.raises(DataLoadError, match="required"):
        loader.load_bars(None, start, end, columns=["dt", "symbol", "close"])


def test_load_bars_rejects_invalid_range() -> None:
    loader = DataFrameBarLoader(valid_bars())
    start = datetime(2026, 1, 1, tzinfo=get_shanghai_tz())
    with pytest.raises(TimezoneError):
        loader.load_bars(None, start, start)
