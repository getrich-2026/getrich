from __future__ import annotations

from datetime import date

import pandas as pd

from getrich_data_import.transform.bars import market_table, to_market_frame


def test_market_table_supports_stock_and_etf() -> None:
    assert market_table("stock", "1d") == "stock_bar_1d"
    assert market_table("etf", "1m") == "etf_bar_1m"


def test_to_market_frame_keeps_appendix_a_raw_fields() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument_id": 1,
                "dt": date(2026, 5, 19),
                "trading_day": date(2026, 5, 19),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "pre_close": 9.8,
                "volume": 100,
                "amount": 1000,
                "limit_up": 11.0,
                "limit_down": 8.8,
                "trading_status": "NORMAL",
                "adj_factor": 1.2,
                "source": "yinhe",
            }
        ]
    )

    out = to_market_frame(frame, freq="1d")

    assert out.loc[0, "pre_close"] == 9.8
    assert out.loc[0, "limit_up"] == 11.0
    assert out.loc[0, "limit_down"] == 8.8
    assert out.loc[0, "trading_status"] == "NORMAL"
    assert out.loc[0, "adj_factor"] == 1.2


def test_to_market_frame_coerces_empty_optional_numeric_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument_id": 1,
                "dt": date(2026, 5, 19),
                "trading_day": date(2026, 5, 19),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "pre_close": None,
                "limit_up": None,
                "limit_down": None,
                "source": "yinhe",
            }
        ]
    )

    out = to_market_frame(frame, freq="1d")

    assert out["pre_close"].dtype.kind == "f"
    assert out["limit_up"].dtype.kind == "f"
    assert out["limit_down"].dtype.kind == "f"
