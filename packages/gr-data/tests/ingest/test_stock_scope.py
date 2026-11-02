"""B 股范围外登记与沪深／BJ 原有门禁的边界、事务回归。"""

from __future__ import annotations

import hashlib
import json
from typing import cast
from unittest.mock import MagicMock

import pandas as pd
import psycopg
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.config.pipeline import Config
from gr_data.ingest import IngestRunError, run_provider
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.importers.market import AdjFactorTsImporter
from gr_data.ingest.tushare.importers.reference import InstrumentsImporter, SymbolMapImporter
from gr_data.ingest.tushare.stock_scope import B_SHARE_RULE, StockScopeAdapter, b_share_mask
from gr_tools.config import Environment


@pytest.mark.parametrize(
    "code,excluded",
    [
        ("900000.SH", True),
        ("900999.SH", True),
        ("200000.SZ", True),
        ("200999.SZ ", True),
        ("201872.SZ", True),
        ("201873.SZ", False),
        ("202872.SZ", False),
        ("209872.SZ", False),
        ("600000.SH", False),
        ("000001.SZ", False),
        ("920047.BJ", False),
        ("900906.SZ", False),
        ("200001.SH", False),
        ("90090.SH", False),
        ("9009060.SH", False),
        ("900906.sh", False),
        ("900１２３.SH", False),
        (None, False),
    ],
)
def test_only_explicit_b_share_segments_are_excluded(code, excluded):
    assert bool(b_share_mask(pd.Series([code])).iloc[0]) is excluded


def _partition(paths, codes, factors):
    path = paths.dataset_file("tushare", "adj_factor", "2018-08")
    write_parquet(
        pd.DataFrame(
            {"ts_code": codes, "trade_date": ["20180816"] * len(codes), "adj_factor": factors}
        ),
        path,
        append=False,
    )
    return path


def test_b_shares_excluded_before_value_and_mapping_checks_raw_preserved(tmp_raw_root):
    path = _partition(tmp_raw_root, ["600000.SH", "900906.SH", "200001.SZ"], [2, -1, None])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    importer = AdjFactorTsImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2018-08",))
    )
    # 即使外部错误地提供了 B 股→A 股身份，范围过滤仍先执行。
    importer._id_map = lambda: {"600000.SH": 1, "900906.SH": 1, "200001.SZ": 1}
    result = importer.build()
    assert result.instrument_id.tolist() == [1]
    assert result.adj_factor.tolist() == [2]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_non_b_share_unmapped_symbol_still_stops(tmp_raw_root):
    _partition(tmp_raw_root, ["600999.SH", "900906.SH"], [1, 1])
    importer = AdjFactorTsImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2018-08",))
    )
    importer._id_map = lambda: {}
    with pytest.raises(IngestGateError, match="600999.SH"):
        importer.build()


def test_all_out_of_scope_is_distinct_from_truly_empty_raw(tmp_raw_root):
    _partition(tmp_raw_root, ["900906.SH"], [1])
    importer = AdjFactorTsImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2018-08",))
    )
    result = importer.build()
    assert result.empty and not importer._check_quality(result)
    _partition(tmp_raw_root, [], [])
    empty = AdjFactorTsImporter(
        cast(psycopg.Connection, None), IngestContext(tmp_raw_root, months=("2018-08",))
    )
    assert empty._check_quality(empty.build())


def test_scope_is_not_applied_to_index_or_future_datasets(tmp_raw_root):
    importer = AdjFactorTsImporter(cast(psycopg.Connection, None), IngestContext(tmp_raw_root))
    frame = pd.DataFrame({"ts_code": ["900906.SH"]})
    write_parquet(frame, tmp_raw_root.dataset_file("tushare", "index_daily", "2018-08"))
    result = StockScopeAdapter(importer).read_month("index_daily", "2018-08")
    assert result is not None
    pd.testing.assert_frame_equal(result, frame)


def test_range_audit_preserves_nonfinite_raw_values_without_committing(tmp_raw_root):
    conn = MagicMock()
    importer = AdjFactorTsImporter(conn, IngestContext(tmp_raw_root, batch_id="stock:2018-08"))
    frame = pd.DataFrame(
        {"ts_code": ["200001.SZ"], "trade_date": ["bad-date"], "adj_factor": [float("inf")]}
    )
    result = importer.exclude_b_shares(frame, "adj_factor", "2018-08")
    assert result.empty
    records = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    assert len(records) == 1 and records[0][:2] == (B_SHARE_RULE, "info")
    detail = json.loads(records[0][2])
    assert detail["raw_values"]["adj_factor"] == "inf"
    assert detail["source_date"] == "bad-date"
    assert detail["batch_id"] == "stock:2018-08" and detail["disposition"] == "out_of_scope"
    conn.commit.assert_not_called()


def test_instruments_and_symbol_mapping_do_not_create_b_share_identity(tmp_raw_root):
    stock = pd.DataFrame(
        {
            "ts_code": ["600000.SH", "900906.SH"],
            "name": ["A", "B"],
            "list_status": ["L", "L"],
            "list_date": ["19991110"] * 2,
            "delist_date": [None] * 2,
        }
    )
    write_parquet(stock, tmp_raw_root.dataset_file("tushare", "instruments", "stock"))
    built = InstrumentsImporter(cast(psycopg.Connection, None), IngestContext(tmp_raw_root)).build()
    assert built.symbol.tolist() == ["600000.SH"]
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [("600000.SH", 1), ("900906.SH", 2)],
        [("600000.SH", 1), ("900906.SH", 2)],
        [],
        [],
    ]
    mapped = SymbolMapImporter(conn, IngestContext(tmp_raw_root)).build()
    assert mapped.source_symbol.tolist() == ["600000.SH"]
    assert mapped.instrument_id.tolist() == [1]


def test_scope_audit_and_main_rows_commit_replay_and_rollback_together(
    pg_conn, tmp_raw_root, monkeypatch
):
    iid = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) "
        "VALUES ('600000.SH','stock','XSHG') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(source,source_symbol,instrument_id) "
        "VALUES ('tushare','600000.SH',%s)",
        (iid,),
    )
    pg_conn.commit()
    path = _partition(tmp_raw_root, ["600000.SH", "900906.SH", "200001.SZ"], [2, 1, 1])
    original = path.read_bytes()
    cfg = Config({}, Environment(tmp_raw_root.root, {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))

    def run(batch):
        return run_provider(
            "tushare", pg_conn, cfg, only=["adj_factor_ts"], months=("2018-08",), batch_id=batch
        )

    def audit_count(batch):
        return pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check WHERE rule=%s AND detail->>'batch_id'=%s",
            (B_SHARE_RULE, batch),
        ).fetchone()[0]

    for _ in range(2):
        result = run("scope:test:commit")
        assert result[0].rows_written == 1 and not result[0].warnings
        assert audit_count("scope:test:commit") == 2
        pg_conn.commit()
    assert pg_conn.execute(
        "SELECT instrument_id,adj_factor FROM market.adj_factor_ts"
    ).fetchall() == [(iid, 2)]
    assert not pg_conn.execute(
        "SELECT source_symbol FROM meta.symbol_map "
        "WHERE source_symbol LIKE '900%' OR source_symbol LIKE '200%'"
    ).fetchall()
    pg_conn.commit()

    def fail_copy(*args, **kwargs):
        raise ValueError("forced scope COPY failure")

    with monkeypatch.context() as patch:
        patch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
        with pytest.raises(IngestRunError, match="forced scope COPY failure"):
            run("scope:test:rollback")
    assert audit_count("scope:test:rollback") == 0
    pg_conn.commit()
    assert run("scope:test:rollback")[0].rows_written == 1
    assert audit_count("scope:test:rollback") == 2
    assert path.read_bytes() == original


def test_verified_exception_requires_live_missing_mapping_check(tmp_raw_root):
    frame = pd.DataFrame({"ts_code": ["201872.SZ"], "trade_date": ["20200918"]})
    offline = AdjFactorTsImporter(cast(psycopg.Connection, None), IngestContext(tmp_raw_root))
    with pytest.raises(IngestGateError, match="Cannot verify missing mapping"):
        offline.exclude_b_shares(frame, "adj_factor", "2020-09")
    conn = MagicMock()
    conn.execute.side_effect = psycopg.OperationalError("mapping connection unavailable")
    importer = AdjFactorTsImporter(conn, IngestContext(tmp_raw_root))
    with pytest.raises(psycopg.OperationalError, match="mapping connection unavailable"):
        importer.exclude_b_shares(frame, "adj_factor", "2020-09")


def _september_valuation(paths, extra_code="201872.SZ"):
    fields = (
        "close",
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
        "limit_status",
    )
    records = [
        {
            "ts_code": "001872.SZ",
            "trade_date": "20200918",
            **{c: 0 if c == "limit_status" else 1.0 for c in fields},
        }
    ]
    for code in [*(f"200{i:03d}.SZ" for i in range(1, 38)), extra_code]:
        records.append({"ts_code": code, "trade_date": "20200918", **dict.fromkeys(fields)})
    path = paths.dataset_file("tushare", "daily_basic", "2020-09")
    write_parquet(pd.DataFrame(records), path, append=False)
    return path


@pytest.mark.parametrize(
    "extra_code,mapped", [("201872.SZ", False), ("201873.SZ", False), ("201872.SZ", True)]
)
def test_verified_b_share_missing_mapping_only_and_adjacent_code_still_stops(
    pg_conn, tmp_raw_root, extra_code, mapped
):
    iid = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) "
        "VALUES ('001872.SZ','stock','XSHE') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
        "VALUES (%s,'tushare','001872.SZ')",
        (iid,),
    )
    if mapped:
        pg_conn.execute(
            "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
            "VALUES (%s,'tushare','201872.SZ')",
            (iid,),
        )
    pg_conn.commit()
    path = _september_valuation(tmp_raw_root, extra_code)
    original = path.read_bytes()
    cfg = Config({}, Environment(tmp_raw_root.root, {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    kwargs = {"only": ["valuation_1d"], "months": ("2020-09",), "batch_id": "b-share:2020-09"}
    if mapped or extra_code != "201872.SZ":
        with pytest.raises(IngestRunError, match="requires missing mapping|201873"):
            run_provider("tushare", pg_conn, cfg, **kwargs)
        assert pg_conn.execute("SELECT count(*) FROM fundamental.valuation_1d").fetchone()[0] == 0
        assert (
            pg_conn.execute(
                "SELECT count(*) FROM ops.data_quality_check WHERE rule=%s", (B_SHARE_RULE,)
            ).fetchone()[0]
            == 0
        )
    else:
        for _ in range(2):
            result = run_provider("tushare", pg_conn, cfg, **kwargs)
            assert result[0].rows_written == 1 and not result[0].warnings
            details = [
                r[0]
                for r in pg_conn.execute(
                    "SELECT detail FROM ops.data_quality_check WHERE rule=%s", (B_SHARE_RULE,)
                ).fetchall()
            ]
            assert len(details) == 38
            special = [d for d in details if d["source_code"] == "201872.SZ"]
            assert len(special) == 1 and special[0]["mapping_missing_verified"] is True
            assert special[0]["rule"] == "verified_201872.SZ_missing_mapping"
            assert special[0]["source_date"] == "20200918"
            assert special[0]["raw_values"]["total_share"] == "nan"
            pg_conn.commit()
        assert (
            pg_conn.execute(
                "SELECT count(*) FROM meta.symbol_map "
                "WHERE source='tushare' AND source_symbol='201872.SZ'"
            ).fetchone()[0]
            == 0
        )
        assert (
            pg_conn.execute(
                "SELECT count(*) FROM meta.instruments WHERE symbol='201872.SZ'"
            ).fetchone()[0]
            == 0
        )
    assert path.read_bytes() == original
