from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from gr_data.ingest.tushare.total_return import index_simple_returns


def test_total_return_uses_exchange_previous_day_and_rejects_price_index() -> None:
    calendar = pl.DataFrame(
        {
            "exchange": ["SSE"] * 4,
            "is_open": [1] * 4,
            "cal_date": ["20260105", "20260106", "20260107", "20260108"],
            "pretrade_date": ["20251231", "20260105", "20260106", "20260107"],
        }
    )
    prices = pl.DataFrame(
        {
            "ts_code": ["H00300.CSI"] * 3,
            "trade_date": ["20260108", "20260106", "20260105"],
            "close": [110.0, 102.0, 100.0],
        }
    )
    symbol, values = index_simple_returns(prices, calendar)
    assert symbol == "H00300.CSI"
    assert values == {date(2026, 1, 6): pytest.approx(0.02)}
    with pytest.raises(ValueError, match="total-return index"):
        index_simple_returns(prices.with_columns(pl.lit("000300.SH").alias("ts_code")), calendar)
    with pytest.raises(ValueError, match="Duplicate"):
        index_simple_returns(pl.concat([prices, prices]), calendar)
    # 即便跳过日也存在报价，前交易日指针错误时不能跨日计成单日收益。
    jumped = calendar.with_columns(
        pl.when(pl.col("cal_date") == "20260108")
        .then(pl.lit("20260106"))
        .otherwise(pl.col("pretrade_date"))
        .alias("pretrade_date")
    )
    with pytest.raises(ValueError, match="previous trading day"):
        index_simple_returns(prices, jumped.reverse())
    with pytest.raises(ValueError, match="Incomplete daily SSE calendar"):
        index_simple_returns(prices, jumped.filter(pl.col("cal_date") != "20260107"))
