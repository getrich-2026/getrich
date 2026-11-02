"""涨跌停状态（045）：哨兵值写 NULL 并标 NO_LIMIT，与「涨跌停价未知」分开。

哨兵取值来自 2026-09 真实样本：北交所 99999.99/0.0，沪市 99999.999/0.01，深市 999999.999/0.01。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext


MONTH = "2024-01"
DAY = "20240102"


def _write(paths, dataset, df):
    write_parquet(df, paths.dataset_file("tushare", dataset, MONTH), append=False)


def _daily(rows):
    """rows: [(ts_code, pre_close)]"""
    return pd.DataFrame(
        [
            {
                "ts_code": c,
                "trade_date": DAY,
                "open": 10.0,
                "high": 10.7,
                "low": 9.0,
                "close": 10.5,
                "pre_close": pc,
                "vol": 1000.0,
                "amount": 10500.0,
            }
            for c, pc in rows
        ]
    )


def _build(paths, daily_rows, limit_rows, *, listing_dates=None, prices=None):
    """limit_rows: [(ts_code, pre_close, up_limit, down_limit)]"""
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    codes = [c for c, _ in daily_rows]
    daily = _daily(daily_rows)
    for field, value in (prices or {}).items():
        daily[field] = value
    _write(paths, "daily", daily)
    _write(
        paths,
        "adj_factor",
        pd.DataFrame([{"ts_code": c, "trade_date": DAY, "adj_factor": 1.0} for c in codes]),
    )
    _write(
        paths,
        "stk_limit",
        pd.DataFrame(
            [
                {"ts_code": c, "trade_date": DAY, "pre_close": pc, "up_limit": up, "down_limit": dn}
                for c, pc, up, dn in limit_rows
            ],
            columns=["ts_code", "trade_date", "pre_close", "up_limit", "down_limit"],
        ),
    )
    imp = StockBars1dImporter(conn=None, ctx=IngestContext(paths=paths))
    imp._id_map = lambda: {c: i + 1 for i, c in enumerate(codes)}
    imp._stock_listing_dates = lambda codes: listing_dates or {}
    df = imp.build().set_index("instrument_id")
    return df, imp.collect_soft_warnings()


@pytest.mark.parametrize(
    "code,up,down",
    [
        ("920025.BJ", 99999.99, 0.0),
        ("601091.SH", 99999.999, 0.01),
        ("301716.SZ", 999999.999, 0.01),
    ],
)
def test_sentinel_limits_are_no_limit_and_null(tmp_raw_root, code, up, down):
    df, warnings = _build(tmp_raw_root, [(code, 9.8)], [(code, 9.8, up, down)])
    row = df.loc[1]
    assert row["price_limit_status"] == "NO_LIMIT"
    assert pd.isna(row["limit_up"]) and pd.isna(row["limit_down"])
    assert warnings == []


def test_normal_limits_are_limited(tmp_raw_root):
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [("600000.SH", 9.8, 10.78, 8.82)])
    assert df.loc[1, "price_limit_status"] == "LIMITED"
    assert df.loc[1, "limit_up"] == 10.78
    assert warnings == []


@pytest.mark.parametrize(
    "field,value",
    [("open", 11.0), ("open", 8.0), ("high", 11.0), ("low", 8.0), ("close", 11.0), ("close", 8.0)],
)
def test_any_ohlc_outside_limits_preserves_price_but_marks_limits_unknown(
    tmp_raw_root, field, value
):
    """open／close 不一定被 high／low 包含，也必须逐价核验限价矛盾。"""
    frame, warnings = _build(
        tmp_raw_root,
        [("600000.SH", 9.8)],
        [("600000.SH", 9.8, 10.78, 8.82)],
        prices={field: value},
    )
    assert frame.loc[1, field] == value
    assert frame.loc[1, "price_limit_status"] == "UNKNOWN"
    assert pd.isna(frame.loc[1, "limit_up"]) and pd.isna(frame.loc[1, "limit_down"])
    assert any("OHLC outside price limits" in warning for warning in warnings)


@pytest.mark.parametrize("prices", [{"open": 10.78, "high": 10.78}, {"close": 8.82, "low": 8.82}])
def test_prices_exactly_at_limit_are_kept(tmp_raw_root, prices):
    frame, warnings = _build(
        tmp_raw_root,
        [("600000.SH", 9.8)],
        [("600000.SH", 9.8, 10.78, 8.82)],
        prices=prices,
    )
    assert frame.loc[1, "price_limit_status"] == "LIMITED"
    assert warnings == []


def test_half_sentinel_is_unknown_and_soft(tmp_raw_root):
    """只有一边像哨兵值，无法确认当日不设涨跌幅：按非法值处理。"""
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [("600000.SH", 9.8, 99999.99, 8.82)])
    assert df.loc[1, "price_limit_status"] == "UNKNOWN"
    assert pd.isna(df.loc[1, "limit_up"])
    assert warnings


def test_missing_limit_row_is_unknown_and_soft(tmp_raw_root):
    daily = [("600000.SH", 9.8), ("000001.SZ", 9.8)]
    df, warnings = _build(tmp_raw_root, daily, [("600000.SH", 9.8, 10.78, 8.82)])
    assert df.loc[2, "price_limit_status"] == "UNKNOWN"
    assert any("no usable price limit" in w for w in warnings)


def test_first_day_without_limit_row_is_unknown_not_soft(tmp_raw_root):
    """主数据确认首日且无 stk_limit 行：保留 UNKNOWN，不计软告警。"""
    daily = [("600000.SH", 9.8), ("920001.BJ", float("nan"))]
    df, warnings = _build(
        tmp_raw_root,
        daily,
        [("600000.SH", 9.8, 10.78, 8.82)],
        listing_dates={"920001.BJ": date(2024, 1, 2)},
    )
    assert df.loc[2, "price_limit_status"] == "UNKNOWN"
    assert warnings == []


@pytest.mark.parametrize(
    "listing_day,blocks", [(date(2024, 1, 2), False), (date(2024, 1, 1), True), (None, True)]
)
def test_missing_whole_limit_row_requires_exact_master_listing_day(
    tmp_raw_root, listing_day, blocks
):
    """即使有有限前收盘，首日不阻塞；上市次日／缺主数据仍待复核。"""
    frame, warnings = _build(
        tmp_raw_root,
        [("688033.SH", 9.8)],
        [],
        listing_dates={"688033.SH": listing_day} if listing_day else {},
    )
    assert frame.loc[1, "price_limit_status"] == "UNKNOWN"
    assert pd.isna(frame.loc[1, "limit_up"]) and pd.isna(frame.loc[1, "limit_down"])
    assert bool(warnings) is blocks


@pytest.mark.parametrize("up,down", [(99999.99, 8.82), (None, None), (10.6, 8.82)])
def test_listing_day_does_not_exempt_present_invalid_or_contradictory_limit_row(
    tmp_raw_root, up, down
):
    frame, warnings = _build(
        tmp_raw_root,
        [("688033.SH", 9.8)],
        [("688033.SH", 9.8, up, down)],
        listing_dates={"688033.SH": date(2024, 1, 2)},
    )
    assert warnings
    assert frame.loc[1, "price_limit_status"] == "UNKNOWN"


def test_missing_pre_close_does_not_prove_listing_day(tmp_raw_root):
    frame, warnings = _build(tmp_raw_root, [("688033.SH", float("nan"))], [])
    assert warnings and frame.loc[1, "price_limit_status"] == "UNKNOWN"


def test_pre_close_mismatch_is_unknown_and_soft(tmp_raw_root):
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [("600000.SH", 9.5, 10.45, 8.55)])
    assert df.loc[1, "price_limit_status"] == "UNKNOWN"
    assert pd.isna(df.loc[1, "limit_up"])
    assert any("differ" in w for w in warnings)


def test_one_sided_missing_keeps_valid_side_as_unknown(tmp_raw_root):
    nan = float("nan")
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [("600000.SH", 9.8, nan, 8.82)])
    assert df.loc[1, "price_limit_status"] == "UNKNOWN"
    assert df.loc[1, "limit_down"] == 8.82
    assert warnings


def test_sentinel_is_not_compared_with_pre_close(tmp_raw_root):
    """哨兵值不由前收盘推算，stk_limit 的 pre_close 与日线不同也仍是 NO_LIMIT。"""
    df, warnings = _build(
        tmp_raw_root, [("688801.SH", 30.0)], [("688801.SH", 25.0, 99999.999, 0.01)]
    )
    assert df.loc[1, "price_limit_status"] == "NO_LIMIT"
    assert warnings == []


@pytest.mark.parametrize("up,down", [(float("inf"), 0.0), (10.78, 0.01)])
def test_inf_or_lower_half_sentinel_is_unknown_and_soft(tmp_raw_root, up, down):
    """+Inf 不是哨兵；只有下限出现哨兵量级也不能认定不设涨跌幅。"""
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [("600000.SH", 9.8, up, down)])
    assert df.loc[1, "price_limit_status"] == "UNKNOWN"
    assert pd.isna(df.loc[1, "limit_up"]) and pd.isna(df.loc[1, "limit_down"])
    assert any("invalid price limits" in w for w in warnings)


def test_empty_stk_limit_partition_is_unknown(tmp_raw_root):
    df, warnings = _build(tmp_raw_root, [("600000.SH", 9.8)], [])
    assert df.loc[1, "price_limit_status"] == "UNKNOWN"
    assert any("partitions are empty" in w for w in warnings)


def test_limits_without_pre_close_column_are_limited(tmp_raw_root):
    """stk_limit 没有 pre_close 时不做比较，涨跌停价有效即 LIMITED。"""
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    _write(tmp_raw_root, "daily", _daily([("600000.SH", 9.8)]))
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": DAY, "adj_factor": 1.0}]),
    )
    _write(
        tmp_raw_root,
        "stk_limit",
        pd.DataFrame(
            [{"ts_code": "600000.SH", "trade_date": DAY, "up_limit": 10.78, "down_limit": 8.82}]
        ),
    )
    imp = StockBars1dImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    imp._id_map = lambda: {"600000.SH": 1}
    assert imp.build().iloc[0]["price_limit_status"] == "LIMITED"


def test_stock_contract_has_price_limit_status_only_for_stock():
    from gr_data.common import contracts

    assert "price_limit_status" in contracts.bar_1d("stock").columns
    for asset in ("etf", "index", "future"):
        assert "price_limit_status" not in contracts.bar_1d(asset).columns


# --------------------------------------------------------------------------- #
# PG：045 约束与入库
# --------------------------------------------------------------------------- #
def _seed(pg_conn):
    pg_conn.execute(
        "INSERT INTO meta.instruments (symbol,asset,exchange,list_date) "
        "VALUES ('600000.SH','stock','XSHG','2000-01-01')"
    )
    iid = pg_conn.execute("SELECT instrument_id FROM meta.instruments").fetchone()[0]
    pg_conn.commit()
    return iid


@pytest.mark.integration
@pytest.mark.parametrize(
    "status,up,down,ok",
    [
        ("LIMITED", 10.78, 8.82, True),
        ("LIMITED", None, 8.82, False),
        ("NO_LIMIT", None, None, True),
        ("NO_LIMIT", 99999.99, 0, False),
        ("UNKNOWN", None, 8.82, True),
        (None, 99999.999, 0.01, True),  # 045 之前写入、未评估
        ("BOGUS", None, None, False),
    ],
)
def test_045_constraints(pg_conn, status, up, down, ok):
    import psycopg

    iid = _seed(pg_conn)
    sql = (
        "INSERT INTO market.stock_bar_1d "
        "(instrument_id,dt,trading_day,source,limit_up,limit_down,price_limit_status) "
        "VALUES (%s,'2024-01-02','2024-01-02','tushare',%s,%s,%s)"
    )
    if ok:
        pg_conn.execute(sql, (iid, up, down, status))
        pg_conn.commit()
    else:
        with pytest.raises(psycopg.errors.CheckViolation):
            pg_conn.execute(sql, (iid, up, down, status))
        pg_conn.rollback()


@pytest.mark.integration
def test_stock_bar_create_is_idempotent(pg_conn):
    from gr_db import POSTGRES_DDL_DIR

    sql = (POSTGRES_DDL_DIR / "003_market.sql").read_text()
    pg_conn.execute(sql)
    pg_conn.execute(sql)
    pg_conn.commit()


@pytest.mark.integration
def test_import_writes_price_limit_status(pg_conn, tmp_raw_root):
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    iid = _seed(pg_conn)
    pg_conn.execute(
        "INSERT INTO meta.symbol_map (instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','600000.SH')",
        (iid,),
    )
    pg_conn.commit()
    _write(tmp_raw_root, "daily", _daily([("600000.SH", 9.8)]))
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": DAY, "adj_factor": 1.0}]),
    )
    _write(
        tmp_raw_root,
        "stk_limit",
        pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": DAY,
                    "pre_close": 9.8,
                    "up_limit": 99999.999,
                    "down_limit": 0.01,
                }
            ]
        ),
    )
    StockBars1dImporter(pg_conn, IngestContext(paths=tmp_raw_root, months=(MONTH,))).run()
    row = pg_conn.execute(
        "SELECT price_limit_status, limit_up, limit_down FROM market.stock_bar_1d WHERE dt=%s",
        (date(2024, 1, 2),),
    ).fetchone()
    assert row == ("NO_LIMIT", None, None)


@pytest.mark.integration
def test_listing_day_missing_row_audit_is_transactional_and_preserves_unknown(
    pg_conn, tmp_raw_root, monkeypatch
):
    from pathlib import Path

    from gr_data.config.pipeline import Config
    from gr_data.ingest import IngestRunError, run_provider
    from gr_data.raw.tushare.suspension_store import publish_coverage
    from gr_tools.config import Environment

    iid = _seed(pg_conn)
    pg_conn.execute(
        "UPDATE meta.instruments SET list_date=%s WHERE instrument_id=%s", (date(2024, 1, 2), iid)
    )
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','600000.SH')",
        (iid,),
    )
    pg_conn.commit()
    _write(tmp_raw_root, "daily", _daily([("600000.SH", 9.8)]))
    _write(
        tmp_raw_root,
        "adj_factor",
        pd.DataFrame([{"ts_code": "600000.SH", "trade_date": DAY, "adj_factor": 1.0}]),
    )
    _write(
        tmp_raw_root,
        "stk_limit",
        pd.DataFrame(columns=["ts_code", "trade_date", "pre_close", "up_limit", "down_limit"]),
    )
    _write(
        tmp_raw_root,
        "suspend_d",
        pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"]),
    )
    publish_coverage(tmp_raw_root.dataset_file("tushare", "suspend_d", MONTH), [date(2024, 1, 2)])
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    run_provider("tushare", pg_conn, cfg, only=["suspend_d"], months=(MONTH,))
    for _ in range(2):
        result = run_provider(
            "tushare",
            pg_conn,
            cfg,
            only=["stock_bar_1d"],
            months=(MONTH,),
            batch_id="listing-day-test:2024-01",
        )
        assert not result[0].warnings
        assert pg_conn.execute(
            "SELECT price_limit_status,limit_up,limit_down FROM market.stock_bar_1d"
        ).fetchall() == [("UNKNOWN", None, None)]
        pg_conn.commit()
    audits = pg_conn.execute(
        "SELECT detail FROM ops.data_quality_check "
        "WHERE rule='tushare_stk_limit_listing_day_missing'"
    ).fetchall()
    assert len(audits) == 2
    assert all(
        a[0]["source_code"] == "600000.SH"
        and a[0]["list_date"] == "2024-01-02"
        and a[0]["trading_day"] == "2024-01-02"
        for a in audits
    )
    pg_conn.commit()

    def fail_copy(*args, **kwargs):
        raise ValueError("forced listing-day COPY failure")

    monkeypatch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
    with pytest.raises(IngestRunError, match="forced listing-day COPY failure"):
        run_provider("tushare", pg_conn, cfg, only=["stock_bar_1d"], months=(MONTH,))
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check "
            "WHERE rule='tushare_stk_limit_listing_day_missing'"
        ).fetchone()[0]
        == 2
    )
    assert pg_conn.execute(
        "SELECT price_limit_status,limit_up,limit_down FROM market.stock_bar_1d"
    ).fetchall() == [("UNKNOWN", None, None)]
