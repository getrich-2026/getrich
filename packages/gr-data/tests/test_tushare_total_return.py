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


def test_import_total_return_attaches_chunk_truncate_trigger_across_new_year(
    pg_conn, tmp_path
) -> None:
    """B2: 独立调用 import_total_return 跨年新建 chunk 时必须自动挂载 diag_chunk_truncate。"""
    from gr_data.ingest.tushare.total_return import import_total_return

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meta.instruments(symbol,asset,exchange,name)
            VALUES ('H00300.CSI','index','CSI','沪深300全收益')
            RETURNING instrument_id
            """
        )
        iid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
            "VALUES (%s,'tushare','H00300.CSI')",
            (iid,),
        )

    calendar = pl.DataFrame(
        {
            "exchange": ["SSE"] * 5,
            "is_open": [1, 0, 0, 1, 1],
            "cal_date": ["20271231", "20280101", "20280102", "20280103", "20280104"],
            "pretrade_date": ["20271230", "20271231", "20271231", "20271231", "20280103"],
        }
    )
    prices = pl.DataFrame(
        {
            "ts_code": ["H00300.CSI"] * 3,
            "trade_date": ["20271231", "20280103", "20280104"],
            "close": [100.0, 101.0, 102.01],
        }
    )
    cal_path = tmp_path / "cal.parquet"
    px_path = tmp_path / "px.parquet"
    calendar.write_parquet(cal_path)
    prices.write_parquet(px_path)

    symbol, version, count = import_total_return(pg_conn, px_path, cal_path)
    assert symbol == "H00300.CSI"
    assert count == 2
    assert version.startswith("tushare-tr-")

    # 确认新建的 TimescaleDB chunk 均挂载并启用了 diag_chunk_truncate（054/057 全局约束）
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = '_timescaledb_internal'
              AND c.relkind = 'r'
              AND NOT EXISTS (
                  SELECT 1 FROM pg_trigger t
                  WHERE t.tgrelid = c.oid
                    AND t.tgname = 'diag_chunk_truncate'
                    AND t.tgenabled = 'O'
              )
            """
        )
        missing_trigger_chunks = cur.fetchall()
    assert missing_trigger_chunks == []
