"""旧上市前隔离策略已由 BJ 行级待处理取代；沪深仍严格失败。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest
from gr_data.config.pipeline import Config
from gr_data.ingest import IngestRunError, run_provider
from gr_data.raw.tushare.suspension_store import publish_coverage
from gr_tools.config import Environment


DAY = "20100422"
BATCH = "tushare-stock-20100101-20231231:2010-04"


def _daily(code, **values):
    return {
        "ts_code": code,
        "trade_date": DAY,
        "open": 30.0,
        "high": 31.0,
        "low": 29.0,
        "close": 30.0,
        "pre_close": 30.0,
        "pct_chg": 0.0,
        "vol": 400.0,
        "amount": 1200.0,
        **values,
    }


def _valuation(code, **values):
    fields = (
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    )
    return {
        "ts_code": code,
        "trade_date": DAY,
        "close": 30.0,
        "limit_status": 0,
        **{f: 1.0 for f in fields},
        **values,
    }


@pytest.fixture
def bj_case(pg_conn, tmp_raw_root):
    for code, exchange in (
        ("600000.SH", "XSHG"),
        ("000001.SZ", "XSHE"),
        ("920047.BJ", "XBSE"),
        ("920001.BJ", "XBSE"),
    ):
        instrument = pg_conn.execute(
            "INSERT INTO meta.instruments(symbol,asset,exchange,list_date) "
            "VALUES (%s,'stock',%s,'2020-11-24') RETURNING instrument_id",
            (code, exchange),
        ).fetchone()[0]
        pg_conn.execute(
            "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
            "VALUES (%s,'tushare',%s)",
            (instrument, code),
        )
        if code == "920047.BJ":
            pg_conn.execute(
                "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
                "VALUES (%s,'tushare','430047.BJ')",
                (instrument,),
            )
    pg_conn.commit()

    def write(dataset, rows):
        path = tmp_raw_root.dataset_file("tushare", dataset, "2010-04")
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(path, compression="zstd")
        return path

    codes = ("600000.SH", "920047.BJ", "920001.BJ")
    write("daily", [_daily(c) for c in codes])
    write(
        "adj_factor",
        [{"ts_code": c, "trade_date": DAY, "adj_factor": 1.2} for c in (*codes, "000001.SZ")],
    )
    write(
        "stk_limit",
        [
            {"ts_code": c, "trade_date": DAY, "pre_close": 30, "up_limit": 33, "down_limit": 27}
            for c in (*codes, "000001.SZ")
        ],
    )
    write("daily_basic", [_valuation(c) for c in codes])
    suspension = tmp_raw_root.dataset_file("tushare", "suspend_d", "2010-04")
    suspension.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"]).to_parquet(
        suspension, compression="zstd"
    )
    publish_coverage(suspension, [pd.Timestamp("2010-04-22").date()])
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    run_provider("tushare", pg_conn, cfg, only=["suspend_d"], months=("2010-04",), batch_id=BATCH)
    return pg_conn, cfg, write


def _run(case, only):
    conn, cfg, _ = case
    return run_provider("tushare", conn, cfg, only=only, months=("2010-04",), batch_id=BATCH)


def _pending(conn):
    return conn.execute(
        "SELECT dataset,source_code,source_date,failure_rules,raw_values,batch_id "
        "FROM ops.tushare_bj_pending ORDER BY pending_id"
    ).fetchall()


def test_missing_factor_is_pending_but_normal_bj_and_same_day_valuation_are_imported(bj_case):
    conn, _, write = bj_case
    path = write(
        "adj_factor",
        [{"ts_code": c, "trade_date": DAY, "adj_factor": 1.2} for c in ("600000.SH", "920001.BJ")],
    )
    before = sha256(path.read_bytes()).hexdigest()
    for _ in range(2):
        result = _run(bj_case, ["stock_bar_1d", "adj_factor_ts", "valuation_1d"])
        assert [r.rows_written for r in result] == [2, 2, 3]
        assert all(not r.warnings for r in result)
    pending = _pending(conn)
    assert len(pending) == 1 and pending[0][:3] == ("stock_bar_1d", "920047.BJ", DAY)
    assert "missing_or_invalid_adj_factor" in pending[0][3]
    assert pending[0][4]["primary"]["vol"] == 400
    assert pending[0][4]["auxiliary"]["adj_factor"] == []
    assert pending[0][5] == BATCH
    assert sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("bad_last", [False, True])
def test_bad_duplicate_does_not_hide_good_record_same_code_and_date(bj_case, bad_last):
    conn, _, write = bj_case
    good, bad = _daily("920047.BJ"), _daily("920047.BJ", open=-1)
    write("daily", [good, bad] if bad_last else [bad, good])
    result = _run(bj_case, ["stock_bar_1d"])
    assert result[0].rows_written == 1
    assert conn.execute("SELECT open FROM market.stock_bar_1d").fetchone()[0] == 30
    assert len(_pending(conn)) == 1


@pytest.mark.parametrize("code", ["600000.SH", "000001.SZ"])
def test_shanghai_shenzhen_invalid_rows_still_stop_and_rollback_pending(bj_case, code):
    conn, _, write = bj_case
    write("daily", [_daily("920047.BJ", open=-1), _daily(code, open=-1)])
    with pytest.raises(IngestRunError, match="非正价格"):
        _run(bj_case, ["stock_bar_1d"])
    assert _pending(conn) == []
    assert conn.execute("SELECT count(*) FROM market.stock_bar_1d").fetchone()[0] == 0


@pytest.mark.parametrize(
    "dataset,rows,only,rule",
    [
        (
            "adj_factor",
            [
                {"ts_code": "920047.BJ", "trade_date": DAY, "adj_factor": -1},
                {"ts_code": "920047.BJ", "trade_date": DAY, "adj_factor": 1.2},
            ],
            "adj_factor_ts",
            "invalid_range_adj_factor",
        ),
        (
            "daily_basic",
            [_valuation("920047.BJ", limit_status=9), _valuation("920047.BJ")],
            "valuation_1d",
            "invalid_limit_status",
        ),
    ],
)
def test_other_writers_preserve_good_duplicate_and_route_failed_record(
    bj_case, dataset, rows, only, rule
):
    conn, _, write = bj_case
    write(dataset, rows)
    result = _run(bj_case, [only])
    assert result[0].rows_written == 1
    pending = _pending(conn)
    assert len(pending) == 1 and pending[0][0] == only and rule in pending[0][3]


def test_all_bj_failed_rows_commit_pending_without_empty_dataset_failure(bj_case):
    conn, _, write = bj_case
    write("adj_factor", [{"ts_code": "920047.BJ", "trade_date": DAY, "adj_factor": float("inf")}])
    result = _run(bj_case, ["adj_factor_ts"])
    assert result[0].rows_written == 0 and not result[0].warnings
    assert _pending(conn)[0][4]["primary"]["adj_factor"] == "inf"


def test_missing_primary_partition_is_not_downgraded_to_pending(bj_case):
    conn, cfg, _ = bj_case
    cfg.raw_root.joinpath("tushare/adj_factor/2010-04.parquet").unlink()
    with pytest.raises(IngestRunError, match="missing raw partitions"):
        _run(bj_case, ["stock_bar_1d"])
    assert _pending(conn) == []


def test_bj_database_capacity_error_is_pending_and_other_values_survive(bj_case):
    conn, _, write = bj_case
    write("daily_basic", [_valuation("920047.BJ", pe=1e30), _valuation("920001.BJ")])
    result = _run(bj_case, ["valuation_1d"])
    assert result[0].rows_written == 1
    assert _pending(conn)[0][3] == ["strict_record_validation"]


def test_database_connection_error_is_not_a_bj_data_exception(bj_case, monkeypatch):
    conn, _, _ = bj_case

    def offline(*args, **kwargs):
        import psycopg

        raise psycopg.OperationalError("synthetic connection failure")

    monkeypatch.setattr("gr_data.ingest.tushare.bj_pending.upsert_rows", offline)
    with pytest.raises(IngestRunError, match="synthetic connection failure"):
        _run(bj_case, ["stock_bar_1d"])
    assert _pending(conn) == []


def test_main_and_pending_rollback_together_on_final_copy_failure(bj_case, monkeypatch):
    conn, _, write = bj_case
    write("daily", [_daily("920047.BJ", open=-1), _daily("920001.BJ")])

    def fail_copy(*args, **kwargs):
        raise ValueError("forced final COPY failure")

    monkeypatch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
    with pytest.raises(IngestRunError, match="forced final COPY failure"):
        _run(bj_case, ["stock_bar_1d"])
    assert _pending(conn) == []


def test_invalid_bj_date_keeps_original_text_and_partition(bj_case):
    conn, _, write = bj_case
    write(
        "adj_factor",
        [
            {"ts_code": "920047.BJ", "trade_date": "bad-date", "adj_factor": 1.2},
            {"ts_code": "920001.BJ", "trade_date": DAY, "adj_factor": 1.2},
        ],
    )
    assert _run(bj_case, ["adj_factor_ts"])[0].rows_written == 1
    row = conn.execute(
        "SELECT source_date,trading_day,raw_partition FROM ops.tushare_bj_pending"
    ).fetchone()
    assert row == ("bad-date", None, "2010-04")


def test_valid_first_day_bj_without_pre_close_and_limits_is_kept(bj_case):
    conn, _, write = bj_case
    write("daily", [_daily("600000.SH"), _daily("920047.BJ", pre_close=None)])
    write(
        "stk_limit",
        [
            {
                "ts_code": "600000.SH",
                "trade_date": DAY,
                "up_limit": 33,
                "down_limit": 27,
                "pre_close": 30,
            }
        ],
    )
    result = _run(bj_case, ["stock_bar_1d"])
    assert result[0].rows_written == 2 and not result[0].warnings
    assert _pending(conn) == []


def test_invalid_bj_limit_row_and_volume_capacity_are_pending(bj_case):
    conn, _, write = bj_case
    write("daily", [_daily("920047.BJ", vol=1e30), _daily("920001.BJ"), _daily("600000.SH")])
    write(
        "stk_limit",
        [
            {
                "ts_code": c,
                "trade_date": DAY,
                "pre_close": 30,
                "up_limit": -1 if c == "920001.BJ" else 33,
                "down_limit": 27,
            }
            for c in ("600000.SH", "920047.BJ", "920001.BJ")
        ],
    )
    assert _run(bj_case, ["stock_bar_1d"])[0].rows_written == 1
    assert {r[1] for r in _pending(conn)} == {"920047.BJ", "920001.BJ"}


def test_unknown_bj_record_pending_without_affecting_known_code(bj_case):
    conn, _, write = bj_case
    write(
        "adj_factor",
        [{"ts_code": c, "trade_date": DAY, "adj_factor": 1.2} for c in ("999999.BJ", "920047.BJ")],
    )
    assert _run(bj_case, ["adj_factor_ts"])[0].rows_written == 1
    assert _pending(conn)[0][1] == "999999.BJ"


def test_bad_bj_suspension_event_does_not_drop_good_event(bj_case):
    conn, cfg, write = bj_case
    path = write(
        "suspend_d",
        [
            {
                "ts_code": "920047.BJ",
                "trade_date": DAY,
                "suspend_type": "X",
                "suspend_timing": None,
            },
            {
                "ts_code": "920047.BJ",
                "trade_date": DAY,
                "suspend_type": "S",
                "suspend_timing": None,
            },
        ],
    )
    publish_coverage(path, [pd.Timestamp("2010-04-22").date()])
    result = _run(bj_case, ["suspend_d"])
    assert result[0].rows_written == 1
    assert _pending(conn)[0][0] == "suspend_d"
    assert "invalid_suspend_type" in _pending(conn)[0][3]


@pytest.mark.parametrize("bad_last", [False, True])
def test_database_invalid_duplicate_is_not_hidden_by_keep_last(bj_case, bad_last):
    conn, _, write = bj_case
    good, bad = _valuation("920047.BJ"), _valuation("920047.BJ", pe=1e30)
    write("daily_basic", [good, bad] if bad_last else [bad, good])
    result = _run(bj_case, ["valuation_1d"])
    assert result[0].rows_written == 1
    assert conn.execute("SELECT pe FROM fundamental.valuation_1d").fetchone()[0] == 1
    assert len(_pending(conn)) == 1


def test_bj_outside_batch_request_days_is_pending(bj_case):
    conn, cfg, write = bj_case
    write(
        "adj_factor",
        [
            {"ts_code": "920047.BJ", "trade_date": "20100423", "adj_factor": 1.2},
            {"ts_code": "920001.BJ", "trade_date": DAY, "adj_factor": 1.2},
        ],
    )
    result = run_provider(
        "tushare",
        conn,
        cfg,
        only=["adj_factor_ts"],
        months=("2010-04",),
        batch_id=BATCH,
        requested_days=(pd.Timestamp("2010-04-22").date(),),
    )
    assert result[0].rows_written == 1
    assert "outside_requested_days" in _pending(conn)[0][3]
