"""D-024 精确哨兵对、近似值拒绝与事务审计回归。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
import psycopg
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.config.pipeline import Config
from gr_data.ingest import IngestRunError, run_provider
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.importers.market import StockBars1dImporter
from gr_data.ingest.tushare.limit_sentinels import (
    EXACT_NO_LIMIT_PROCESSING_RULE,
    EXACT_NO_LIMIT_RULE,
    exact_no_limit_mask,
)
from gr_data.raw.tushare.suspension_store import publish_coverage
from gr_tools.config import Environment


@pytest.mark.parametrize(
    "up,down,expected",
    [
        (10000.0, 0.001, True),
        ("10000.00", "0.0010", True),
        (10000.0, 0.01, True),
        (10000.0, 0.02, False),
        (9999.99, 0.01, False),
        (10000.01, 0.01, False),
        (10000.0, "0.0100000000000000001", False),
        (9999.0, 0.001, False),
        (10000.0, 3.10, False),
        (3.40, 0.001, False),
        (10000.000001, 0.001, False),
        (10000.0, 0.001000001, False),
        ("10000.0000000000000001", "0.001", False),
        ("10000", "0.0010000000000000000001", False),
        (None, 0.001, False),
        (10000.0, float("nan"), False),
        (float("inf"), 0.001, False),
    ],
)
def test_exact_pair_uses_source_decimal_values_without_rounding(up, down, expected):
    assert (
        bool(exact_no_limit_mask(pd.Series([up]), pd.Series([down]), pd.Series(["600145.SH"]))[0])
        is expected
    )


def test_nullable_and_empty_series_are_not_sentinels():
    assert exact_no_limit_mask(
        pd.Series([pd.NA], dtype="Float64"),
        pd.Series([0.001], dtype="Float64"),
        pd.Series(["600145.SH"]),
    ).tolist() == [False]
    assert (
        exact_no_limit_mask(
            pd.Series([], dtype=float), pd.Series([], dtype=float), pd.Series([], dtype=str)
        ).size
        == 0
    )


def _raw(paths, up, down, code="600610.SH"):
    frames = {
        "daily": pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": "20200817",
                    "open": 7.0,
                    "high": 7.04,
                    "low": 4.89,
                    "close": 4.89,
                    "pre_close": 3.26,
                    "vol": 137300.0,
                    "amount": 80702.126,
                }
            ]
        ),
        "adj_factor": pd.DataFrame(
            [{"ts_code": code, "trade_date": "20200817", "adj_factor": 1.25}]
        ),
        "stk_limit": pd.DataFrame(
            [
                {
                    "ts_code": code,
                    "trade_date": "20200817",
                    "pre_close": 3.26,
                    "up_limit": up,
                    "down_limit": down,
                }
            ]
        ),
        "suspend_d": pd.DataFrame(
            columns=["ts_code", "trade_date", "suspend_type", "suspend_timing"]
        ),
    }
    for dataset, frame in frames.items():
        write_parquet(frame, paths.dataset_file("tushare", dataset, "2020-08"), append=False)
    publish_coverage(paths.dataset_file("tushare", "suspend_d", "2020-08"), [date(2020, 8, 17)])


@pytest.mark.parametrize(
    "up,down", [(10000.0, 0.001), (10000.0, 0.01), (1000000.0, 0.01), (99999.99, 0.0)]
)
def test_new_exact_pair_and_existing_threshold_keep_no_limit(tmp_raw_root, up, down):
    _raw(tmp_raw_root, up, down)
    importer = StockBars1dImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2020-08",))
    )
    importer._id_map = lambda: {"600610.SH": 1}
    result = importer.build().iloc[0]
    assert result.price_limit_status == "NO_LIMIT"
    assert pd.isna(result.limit_up) and pd.isna(result.limit_down)
    assert importer.collect_soft_warnings() == []


@pytest.mark.parametrize(
    "up,down",
    [
        (10000.0, 0.02),
        (9999.99, 0.01),
        (10000.01, 0.01),
        (9999.0, 0.001),
        (10000.0, 3.10),
        (3.40, 0.001),
        ("10000.0000000000000001", "0.001"),
        (10000.0, 0.001000001),
    ],
)
def test_other_combinations_keep_warning_gate_and_unknown(tmp_raw_root, up, down):
    _raw(tmp_raw_root, up, down)
    importer = StockBars1dImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2020-08",))
    )
    importer._id_map = lambda: {"600610.SH": 1}
    assert importer.build().iloc[0].price_limit_status == "UNKNOWN"
    # 月度验收拒绝任何未审核 warning；不以单侧或近似值走正常未知例外。
    assert importer.collect_soft_warnings()


@pytest.mark.parametrize("down", [0.001, 0.01])
def test_exact_pair_audit_commits_replays_and_rolls_back_with_bars(
    pg_conn, tmp_raw_root, monkeypatch, down
):
    _raw(tmp_raw_root, 10000.0, down)
    instrument = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange,list_date) "
        "VALUES ('600610.SH','stock','XSHG','1992-08-05') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','600610.SH')",
        (instrument,),
    )
    pg_conn.commit()
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    run_provider("tushare", pg_conn, cfg, only=["suspend_d"], months=("2020-08",))
    for attempt in range(2):
        result = run_provider(
            "tushare",
            pg_conn,
            cfg,
            only=["stock_bar_1d"],
            months=("2020-08",),
            batch_id="sentinel-test:2020-08",
        )
        assert not result[0].warnings
        assert pg_conn.execute(
            "SELECT price_limit_status,limit_up,limit_down FROM market.stock_bar_1d"
        ).fetchall() == [("NO_LIMIT", None, None)]
        audits = [
            r[0]
            for r in pg_conn.execute(
                "SELECT detail FROM ops.data_quality_check WHERE rule=%s", (EXACT_NO_LIMIT_RULE,)
            ).fetchall()
        ]
        assert len(audits) == attempt + 1
        assert all(
            d["source_code"] == "600610.SH"
            and d["trading_day"] == "2020-08-17"
            and d["raw_up_limit"] == "10000.0"
            and d["raw_down_limit"] == str(down)
            and d["processing_rule"] == EXACT_NO_LIMIT_PROCESSING_RULE
            for d in audits
        )
        pg_conn.commit()

    def fail_copy(*args, **kwargs):
        raise ValueError("forced exact sentinel COPY failure")

    monkeypatch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
    with pytest.raises(IngestRunError, match="forced exact sentinel COPY failure"):
        run_provider("tushare", pg_conn, cfg, only=["stock_bar_1d"], months=("2020-08",))
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check WHERE rule=%s", (EXACT_NO_LIMIT_RULE,)
        ).fetchone()[0]
        == 2
    )


@pytest.mark.parametrize("code", ["000001.SZ", "920001.BJ", None, "600145.SZ", "600145.SHX"])
@pytest.mark.parametrize("down", [0.001, 0.01])
def test_exact_pair_requires_shanghai_source_code(code, down):
    assert not exact_no_limit_mask(pd.Series([10000.0]), pd.Series([down]), pd.Series([code]))[0]


@pytest.mark.parametrize("code", ["000001.SZ", "920001.BJ"])
@pytest.mark.parametrize("down", [0.001, 0.01])
def test_other_markets_keep_exact_pair_warning_gate(tmp_raw_root, code, down):
    _raw(tmp_raw_root, 10000.0, down, code=code)
    importer = StockBars1dImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2020-08",))
    )
    importer._id_map = lambda: {code: 1}
    with pytest.raises(IngestGateError, match="Unreviewed non-Shanghai"):
        importer.build()


@pytest.mark.parametrize("code,exchange", [("000001.SZ", "XSHE"), ("920001.BJ", "XBSE")])
@pytest.mark.parametrize("down", [0.001, 0.01, 0.02])
def test_foreign_10000_stops_whole_import_before_bj_pending(
    pg_conn, tmp_raw_root, code, exchange, down
):
    _raw(tmp_raw_root, 10000.0, down, code=code)
    instrument = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange,list_date) "
        "VALUES (%s,'stock',%s,'2000-01-01') RETURNING instrument_id",
        (code, exchange),
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) VALUES (%s,'tushare',%s)",
        (instrument, code),
    )
    pg_conn.commit()
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    with pytest.raises(IngestRunError, match="Unreviewed non-Shanghai"):
        run_provider("tushare", pg_conn, cfg, only=["stock_bar_1d"], months=("2020-08",))
    assert pg_conn.execute("SELECT count(*) FROM market.stock_bar_1d").fetchone()[0] == 0
    assert pg_conn.execute("SELECT count(*) FROM ops.tushare_bj_pending").fetchone()[0] == 0
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check WHERE rule=%s",
            (EXACT_NO_LIMIT_RULE,),
        ).fetchone()[0]
        == 0
    )
