from __future__ import annotations

from datetime import date

import pandas as pd

from getrich_data_import.adapters.insight import _normalize_bars, _request_end, _request_start


def test_insight_request_window_is_shanghai_timezone_aware() -> None:
    start = _request_start(date(2026, 5, 19), "1m")
    end = _request_end(date(2026, 5, 19), "1m")

    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert start.utcoffset().total_seconds() == 8 * 3600
    assert end.utcoffset().total_seconds() == 8 * 3600
    assert (start.hour, end.hour) == (9, 16)


def test_insight_adj_factor_only_emitted_for_stock_like_daily_bars() -> None:
    raw = pd.DataFrame(
        {
            "htsc_code": ["IF2406.CCFX"],
            "time": [pd.Timestamp("2026-05-19")],
            "open": [1],
            "high": [2],
            "low": [1],
            "close": [2],
        }
    )

    future = _normalize_bars(raw, asset="future", freq="1d", provider="insight")
    stock = _normalize_bars(raw, asset="stock", freq="1d", provider="insight")

    assert future["adj_factor"].isna().all()
    assert stock["adj_factor"].tolist() == [1.0]
