"""极端估值原值入库、字段扩容及事务审计的回归。"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.config.pipeline import Config
from gr_data.ingest import IngestRunError, run_provider
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.market import ValuationImporter
from gr_tools.config import Environment


def test_extreme_audit_threshold_is_strict_and_negative_values_are_preserved(tmp_raw_root):
    conn = MagicMock()
    importer = ValuationImporter(conn, IngestContext(tmp_raw_root))
    frame = pd.DataFrame(
        {
            "instrument_id": [1] * 6,
            "trading_day": [date(2010, 1, 4)] * 6,
            "ts_code": ["000555.SZ"] * 6,
            "pe": [1_000_000, 1_000_000.0001, -1_000_000.0001, None, float("nan"), float("inf")],
            "pe_ttm": [None] * 6,
            "ps": [0] * 6,
            "ps_ttm": [-1_000_000] * 6,
        }
    )
    for field in ("pe", "pe_ttm", "ps", "ps_ttm"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    original = frame.copy(deep=True)
    importer._audit_extreme_ratios(frame)
    pd.testing.assert_frame_equal(frame, original)
    records = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    details = [json.loads(record[2]) for record in records]
    assert len(details) == 2
    assert {d["source_value"] for d in details} == {"1000000.0001", "-1000000.0001"}
    assert all(d["source_value"] == d["retained_value"] for d in details)
    assert all(d["note"] == "极端值保留原值、因子层处理" for d in details)
    assert all(
        d["trading_day"] == "2010-01-04" and d["source_code"] == "000555.SZ" for d in details
    )
    conn.commit.assert_not_called()


def test_precision_migration_preserves_existing_values_and_does_not_rewrite_chunks(pg_conn):
    migration = (
        Path(__file__).resolve().parents[4]
        / "packages/gr-db/src/gr_db/ddl/postgres/050_valuation_ratio_precision.sql"
    ).read_text()
    instrument = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) "
        "VALUES ('000555.SZ','stock','XSHE') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "ALTER TABLE fundamental.valuation_1d ALTER COLUMN pe TYPE NUMERIC(12,4), "
        "ALTER COLUMN pe_ttm TYPE NUMERIC(12,4), ALTER COLUMN ps TYPE NUMERIC(12,4), "
        "ALTER COLUMN ps_ttm TYPE NUMERIC(12,4)"
    )
    pg_conn.execute(
        "INSERT INTO fundamental.valuation_1d "
        "(instrument_id,trading_day,pe,pe_ttm,ps,ps_ttm,source,available_at) "
        "VALUES (%s,'2010-01-04',123.4567,-123.4567,1.0001,2.0002,"
        "'tushare','2010-01-04 17:00:00+08')",
        (instrument,),
    )
    pg_conn.commit()

    def snapshot():
        rows = pg_conn.execute(
            "SELECT pe,pe_ttm,ps,ps_ttm FROM fundamental.valuation_1d"
        ).fetchall()
        files = pg_conn.execute(
            "SELECT oid,relfilenode FROM pg_catalog.pg_class "
            "WHERE oid='fundamental.valuation_1d'::regclass OR oid IN "
            "(SELECT inhrelid FROM pg_catalog.pg_inherits "
            "WHERE inhparent='fundamental.valuation_1d'::regclass) ORDER BY oid"
        ).fetchall()
        return rows, files

    before = snapshot()
    for _ in range(2):
        pg_conn.execute(migration)
        pg_conn.commit()
        assert snapshot() == before
    precision = dict(
        pg_conn.execute(
            "SELECT column_name,numeric_precision FROM information_schema.columns "
            "WHERE table_schema='fundamental' AND table_name='valuation_1d' "
            "AND column_name IN ('pe','pe_ttm','ps','ps_ttm','pb')"
        ).fetchall()
    )
    assert precision == {"pe": 20, "pe_ttm": 20, "ps": 20, "ps_ttm": 20, "pb": 12}


def test_extreme_valuation_values_and_audits_commit_and_rollback_together(
    pg_conn, tmp_raw_root, monkeypatch
):
    instrument = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) "
        "VALUES ('000555.SZ','stock','XSHE') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','000555.SZ')",
        (instrument,),
    )
    pg_conn.commit()
    values = {
        "pe": 4_496_139_900.1234,
        "pe_ttm": -4_496_139_900.1234,
        "ps": 4_455_860_933.3333,
        "ps_ttm": 4_496_139_900.0,
    }
    row = {
        "ts_code": "000555.SZ",
        "trade_date": "20100104",
        "close": 8.93,
        "limit_status": 4,
        **{
            field: 1.0
            for field in (
                *ValuationImporter._PASSTHROUGH,
                "total_mv",
                "circ_mv",
                "total_share",
                "float_share",
                "free_share",
            )
        },
        **values,
    }
    path = tmp_raw_root.dataset_file("tushare", "daily_basic", "2010-01")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_parquet(path, compression="zstd")
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    result = run_provider("tushare", pg_conn, cfg, only=["valuation_1d"], months=("2010-01",))
    assert result[0].rows_written == 1 and not result[0].warnings
    stored = pg_conn.execute("SELECT pe,pe_ttm,ps,ps_ttm FROM fundamental.valuation_1d").fetchone()
    assert stored == tuple(Decimal(str(v)).quantize(Decimal("0.0001")) for v in values.values())
    details = [
        r[0]
        for r in pg_conn.execute(
            "SELECT detail FROM ops.data_quality_check WHERE rule='tushare_valuation_extreme_ratio'"
        ).fetchall()
    ]
    assert {d["field"] for d in details} == set(values)
    assert all(d["source_value"] == d["retained_value"] for d in details)
    assert all(d["note"] == "极端值保留原值、因子层处理" for d in details)
    pg_conn.commit()

    def fail_copy(*args, **kwargs):
        raise ValueError("forced extreme valuation COPY failure")

    monkeypatch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
    with pytest.raises(IngestRunError, match="forced extreme valuation COPY failure"):
        run_provider("tushare", pg_conn, cfg, only=["valuation_1d"], months=("2010-01",))
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check "
            "WHERE rule='tushare_valuation_extreme_ratio'"
        ).fetchone()[0]
        == 4
    )
    assert pg_conn.execute("SELECT count(*) FROM fundamental.valuation_1d").fetchone()[0] == 1
