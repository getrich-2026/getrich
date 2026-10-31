"""历史换码须归入同一证券身份；不猜代码、不覆盖冲突。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.ingest.tushare.symbols import stock_alias_ids
from gr_data.raw.base import RawContext
from gr_data.raw.tushare.fetchers.reference import InstrumentsFetcher


def test_verified_aliases_resolve_same_instrument():
    mapping = pd.DataFrame({"o_code": ["831396.BJ"], "n_code": ["920496.BJ"]})
    assert stock_alias_ids({"920496.BJ": 11, "302132.SZ": 22}, mapping) == {
        "831396.BJ": 11,
        "300114.SZ": 22,
    }


def test_old_snapshot_without_aliases_stays_compatible():
    assert stock_alias_ids({"600000.SH": 1}, None) == {}


@pytest.mark.parametrize(
    "old_code,new_code", [("000022.SZ", "001872.SZ"), ("000043.SZ", "001914.SZ")]
)
def test_pre_2024_aliases_share_existing_instrument(old_code, new_code):
    assert stock_alias_ids({new_code: 17}, None) == {old_code: 17}
    with pytest.raises(ValueError, match="canonical instrument"):
        stock_alias_ids({old_code: 18, new_code: 17}, None)


@pytest.mark.parametrize(
    "old_code,new_code", [("000022.SZ", "001872.SZ"), ("000043.SZ", "001914.SZ")]
)
@pytest.mark.parametrize("existing_id", [17, 99])
def test_historical_alias_import_preserves_identity_and_rejects_remap(
    tmp_path, old_code, new_code, existing_id
):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import SymbolMapImporter

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(new_code, 17)],
        [(new_code, 17)],
        [(old_code, existing_id)],
    ]
    importer = SymbolMapImporter(conn, IngestContext(RawPaths(tmp_path)))
    if existing_id != 17:
        with pytest.raises(ValueError, match="existing source mapping"):
            importer.build()
    else:
        result = importer.build().set_index("source_symbol")
        assert result["instrument_id"].tolist() == [17, 17]
        assert set(result.index) == {old_code, new_code}
        assert len(result) == 2


@pytest.mark.parametrize(
    "records,stocks,error",
    [
        ([("831396.BJ", "920496.BJ")], {}, "target missing"),
        ([("831396.BJ", "920496.BJ")], {"831396.BJ": 1, "920496.BJ": 2}, "canonical instrument"),
        (
            [("831396.BJ", "920496.BJ"), ("831396.BJ", "920001.BJ")],
            {"920496.BJ": 1, "920001.BJ": 2},
            "Conflicting",
        ),
        ([("831396.BJ", "920496.SH")], {"920496.SH": 1}, "Invalid"),
        ([(None, "920496.BJ")], {"920496.BJ": 1}, "Invalid"),
    ],
)
def test_invalid_aliases_are_rejected(records, stocks, error):
    with pytest.raises(ValueError, match=error):
        stock_alias_ids(stocks, pd.DataFrame(records, columns=["o_code", "n_code"]))


def test_raw_fetch_preserves_supplier_mapping(tmp_path):
    client = MagicMock()
    mapping = pd.DataFrame(
        {
            "o_code": ["831396.BJ"],
            "n_code": ["920496.BJ"],
            "name": ["许昌智能"],
            "list_date": ["20240126"],
        }
    )
    client.query_all.return_value = mapping
    fetcher = InstrumentsFetcher(
        client, RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    )
    fetcher._stock = lambda: pd.DataFrame({"ts_code": ["920496.BJ"]})
    fetcher._index = lambda: pd.DataFrame()
    fetcher._future = lambda: pd.DataFrame()
    assert fetcher.fetch() == 2
    saved = pd.read_parquet(tmp_path / "tushare/instruments/bse_mapping.parquet")
    pd.testing.assert_frame_equal(saved, mapping)
    assert client.query_all.call_args.args[0] == "bse_mapping"


@pytest.mark.parametrize("existing_id", [22, 99])
def test_symbol_map_importer_retains_alias_and_rejects_remap(tmp_path, existing_id):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import SymbolMapImporter

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [("302132.SZ", 22)],
        [("302132.SZ", 22)],
        [("300114.SZ", existing_id)],
    ]
    importer = SymbolMapImporter(conn, IngestContext(RawPaths(tmp_path)))
    if existing_id != 22:
        with pytest.raises(ValueError, match="existing source mapping"):
            importer.build()
    else:
        result = importer.build().set_index("source_symbol")
        assert (
            result.loc["300114.SZ", "instrument_id"]
            == result.loc["302132.SZ", "instrument_id"]
            == 22
        )
        assert len(result) == 2


def test_aliases_pg_migration_and_idempotent_import(pg_conn, tmp_raw_root):
    """真实 DDL 允许同一证券多代码，重复导入幂等，正向唯一仍有效。"""
    import psycopg
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import SymbolMapImporter

    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.instruments(symbol,asset,exchange) "
            "VALUES ('302132.SZ','stock','XSHE'),('920496.BJ','stock','XBSE')"
        )
    pg_conn.commit()
    path = tmp_raw_root.dataset_file("tushare", "instruments", "bse_mapping")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"o_code": ["831396.BJ"], "n_code": ["920496.BJ"]}).to_parquet(
        path, compression="zstd"
    )
    importer = SymbolMapImporter(pg_conn, IngestContext(tmp_raw_root))
    assert importer.run().rows_written == 4
    assert importer.run().rows_written == 4
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT source_symbol,instrument_id FROM meta.symbol_map WHERE source='tushare'"
        )
        ids = dict(cur.fetchall())
        assert ids["300114.SZ"] == ids["302132.SZ"]
        assert ids["831396.BJ"] == ids["920496.BJ"]
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
                "VALUES (%s,'tushare','300114.SZ')",
                (ids["920496.BJ"],),
            )
    pg_conn.rollback()


def test_alias_rows_coalesce_and_reject_value_conflicts():
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    frame = pd.DataFrame(
        {
            "instrument_id": [1, 1],
            "trading_day": ["20240102"] * 2,
            "ts_code": ["302132.SZ", "300114.SZ"],
            "close": [44.31, 44.31],
            "pb": [None, None],
            "limit_status": [1, 0],
        }
    )
    result = collapse_alias_rows(frame, {1: "302132.SZ"})
    assert result.ts_code.tolist() == ["302132.SZ"]
    assert result.limit_status.tolist() == [1]
    frame.loc[1, "close"] = 44.30
    with pytest.raises(ValueError, match="Conflicting alias observations"):
        collapse_alias_rows(frame, {1: "302132.SZ"})


def test_alias_rows_cannot_guess_preferred_code_or_hide_same_code_duplicates():
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    frame = pd.DataFrame(
        {
            "instrument_id": [1, 1],
            "dt": ["20240102"] * 2,
            "ts_code": ["831396.BJ", "920496.BJ"],
            "close": [10.0, 10.0],
        }
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        collapse_alias_rows(frame, {})
    frame["ts_code"] = "920496.BJ"
    assert len(collapse_alias_rows(frame, {1: "920496.BJ"})) == 2


def _legacy_pair_frame(old_code="000043.SZ", new_code="001914.SZ", /, **columns):
    from datetime import date

    return pd.DataFrame(
        {
            "instrument_id": [17, 17],
            "trading_day": [date(2010, 1, 4)] * 2,
            "ts_code": [old_code, new_code],
            "close": [14.92, 14.92],
            **columns,
        }
    )


@pytest.mark.parametrize("field", ["dv_ratio", "dv_ttm"])
@pytest.mark.parametrize("old,new", [(0.34, 0.3351), (1.0, 1.01), (100.0, 100.5), (0, 0.01)])
def test_legacy_dividend_tolerance_preserves_canonical_and_audits(field, old, new):
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    audits = []
    frame = _legacy_pair_frame(**{field: [old, new]})
    original = frame.copy(deep=True)
    result = collapse_alias_rows(frame, {17: "001914.SZ"}, audit=audits.append)
    assert result["ts_code"].tolist() == ["001914.SZ"]
    assert result[field].tolist() == [new]
    assert len(audits) == 1
    assert audits[0] == {
        "old_code": "000043.SZ",
        "canonical_code": "001914.SZ",
        "trading_day": "2010-01-04",
        "field": field,
        "old_value": str(frame.iloc[0][field]),
        "new_value": str(frame.iloc[1][field]),
        "old_raw_value": str(frame.iloc[0][field]),
        "new_raw_value": str(frame.iloc[1][field]),
        "selected_value": str(frame.iloc[1][field]),
        "processing_rule": "finite_within_tolerance",
    }
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("field", ["dv_ratio", "dv_ttm"])
@pytest.mark.parametrize(
    "old,new",
    [(0.1, 0.2), (100, 101.1), (1.0, None), (1.0, float("inf"))],
)
def test_legacy_dividend_outside_tolerance_or_nonfinite_stops_without_audit(field, old, new):
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    audits = []
    with pytest.raises(ValueError, match="tolerance_stop|new_missing_stop"):
        collapse_alias_rows(
            _legacy_pair_frame(**{field: [old, new]}), {17: "001914.SZ"}, audit=audits.append
        )
    assert audits == []


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["dv_ratio", "dv_ttm"])
def test_legacy_old_missing_uses_finite_new_value_with_audit(missing, field):
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    audits = []
    result = collapse_alias_rows(
        _legacy_pair_frame("000022.SZ", "001872.SZ", **{field: [missing, 3.2852]}),
        {17: "001872.SZ"},
        audit=audits.append,
    )
    assert result[field].tolist() == [3.2852]
    assert audits[0]["old_value"] is None
    assert audits[0]["new_value"] == "3.2852"
    assert audits[0]["processing_rule"] == "old_missing_use_new"


@pytest.mark.parametrize(
    "old,new", [(None, None), (float("nan"), float("inf")), (float("inf"), float("inf"))]
)
@pytest.mark.parametrize("field", ["dv_ratio", "dv_ttm", "limit_status"])
def test_legacy_both_missing_keeps_null_and_audits_rule_without_mutating_input(old, new, field):
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    frame = _legacy_pair_frame(**{field: [old, new]})
    original = frame.copy(deep=True)
    audits = []
    result = collapse_alias_rows(frame, {17: "001914.SZ"}, audit=audits.append)
    assert len(result) == 1 and pd.isna(result.iloc[0][field])
    assert audits[0]["processing_rule"] == "both_missing_keep_null"
    assert audits[0]["old_value"] is None and audits[0]["new_value"] is None
    assert audits[0]["selected_value"] is None
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("field", ["close", "volume", "amount", "adj_factor", "pb"])
def test_legacy_reconciliation_cannot_hide_other_field_conflicts(field):
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    with pytest.raises(ValueError, match="Conflicting alias observations"):
        collapse_alias_rows(
            _legacy_pair_frame(**{field: [1.0, 1.001], "dv_ratio": [0.34, 0.3351]}),
            {17: "001914.SZ"},
            audit=lambda detail: None,
        )


def test_legacy_exception_does_not_apply_to_other_alias_pairs_or_without_audit():
    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    with pytest.raises(ValueError, match="Conflicting alias observations"):
        collapse_alias_rows(
            _legacy_pair_frame("831396.BJ", "920496.BJ", dv_ratio=[0.34, 0.3351]),
            {17: "920496.BJ"},
            audit=lambda detail: None,
        )
    with pytest.raises(ValueError, match="requires audit"):
        collapse_alias_rows(_legacy_pair_frame(dv_ratio=[0.34, 0.3351]), {17: "001914.SZ"})


@pytest.mark.parametrize(
    "status,prices",
    [
        (0, {"open": 10, "high": 10.5, "low": 9.5, "close": 10}),
        (1, {"open": 10, "high": 10.8, "low": 9.9, "close": 10.5}),
        (2, {"open": 10.5, "high": 11, "low": 10.2, "close": 11}),
        (3, {"open": 11, "high": 11, "low": 11, "close": 11}),
        (4, {"open": 10, "high": 10, "low": 9.2, "close": 9.5}),
        (5, {"open": 9.8, "high": 10, "low": 9, "close": 9}),
        (6, {"open": 9, "high": 9, "low": 9, "close": 9}),
    ],
)
def test_legacy_limit_status_is_recomputed_from_actual_prices(status, prices):
    from datetime import date

    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    frame = _legacy_pair_frame(
        limit_status=[6 if status == 0 else 0, status], close=[prices["close"]] * 2
    )
    audits = []
    result = collapse_alias_rows(
        frame,
        {17: "001914.SZ"},
        price_evidence={
            (17, date(2010, 1, 4)): {**prices, "pre_close": 10, "limit_up": 11, "limit_down": 9}
        },
        audit=audits.append,
    )
    assert result["limit_status"].tolist() == [status]
    assert audits[0]["field"] == "limit_status"
    assert audits[0]["new_value"] == str(status)


@pytest.mark.parametrize("evidence", [None, {}, {"close": 14.92}])
def test_legacy_limit_status_requires_complete_matching_evidence(evidence):
    from datetime import date

    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    with pytest.raises(ValueError, match="limit_status_mismatch_stop|Non-comparable"):
        collapse_alias_rows(
            _legacy_pair_frame(limit_status=[0, 4]),
            {17: "001914.SZ"},
            price_evidence={(17, date(2010, 1, 4)): evidence} if evidence is not None else None,
            audit=lambda detail: None,
        )


def test_stock_auxiliary_aliases_copy_only_missing_keys_and_preserve_conflicts():
    from gr_data.ingest.tushare.symbols import expand_stock_auxiliary_aliases

    frame = pd.DataFrame(
        {
            "ts_code": ["000043.SZ", "000043.SZ", "001914.SZ"],
            "trade_date": ["20100104", "20100105", "20100105"],
            "adj_factor": [2.3, 2.4, 2.5],
        }
    )
    original = frame.copy(deep=True)
    result = expand_stock_auxiliary_aliases(frame)
    assert len(result) == 4
    assert result.query("ts_code == '001914.SZ'")["adj_factor"].tolist() == [2.5, 2.3]
    assert len(result[result["trade_date"].eq("20100105")]) == 2
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    "old_code,new_code,dual_limits",
    [("000043.SZ", "001914.SZ", False), ("000022.SZ", "001872.SZ", True)],
)
def test_alias_bars_use_equivalent_auxiliary_keys_without_diagnostic_conflicts(
    tmp_raw_root, monkeypatch, old_code, new_code, dual_limits
):
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.market import StockBars1dImporter

    def write(dataset, records):
        p = tmp_raw_root.dataset_file("tushare", dataset, "2010-01")
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_parquet(p, compression="zstd")

    write(
        "daily",
        [
            {
                "ts_code": code,
                "trade_date": "20100104",
                "open": 15.27,
                "high": 15.28,
                "low": 14.85,
                "close": 14.92,
                "pre_close": 15.13,
                "vol": 100,
                "amount": 200,
            }
            for code in (old_code, new_code)
        ],
    )
    write("adj_factor", [{"ts_code": old_code, "trade_date": "20100104", "adj_factor": 2.399}])
    bounds = [
        {
            "ts_code": old_code,
            "trade_date": "20100104",
            "pre_close": None if dual_limits else 15.13,
            "up_limit": 16.64,
            "down_limit": 13.62,
        }
    ]
    if dual_limits:
        bounds.append({**bounds[0], "ts_code": new_code, "pre_close": 15.13})
    write("stk_limit", bounds)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [(17, new_code)]
    importer = StockBars1dImporter(conn, IngestContext(tmp_raw_root))
    monkeypatch.setattr(importer, "_id_map", lambda: {old_code: 17, new_code: 17})
    monkeypatch.setattr(
        importer, "_trading_status", lambda market, months: pd.Series("NORMAL", index=market.index)
    )
    result = importer.build()
    assert len(result) == 1
    assert result.iloc[0]["instrument_id"] == 17
    assert result.iloc[0]["adj_factor"] == 2.399
    assert result.iloc[0]["limit_up"] == 16.64
    assert result.iloc[0]["limit_down"] == 13.62
    assert result.iloc[0]["price_limit_status"] == "LIMITED"
    assert importer.soft_warnings == []


def test_alias_override_audit_commits_and_rolls_back_with_valuation(
    pg_conn, tmp_raw_root, monkeypatch
):
    from pathlib import Path

    from gr_data.config.pipeline import Config
    from gr_data.ingest import IngestRunError, run_provider
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.tushare.importers.reference import SymbolMapImporter
    from gr_tools.config import Environment

    pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) VALUES ('001914.SZ','stock','XSHE')"
    )
    pg_conn.commit()
    SymbolMapImporter(pg_conn, IngestContext(tmp_raw_root)).run()

    def write(dataset, records):
        path = tmp_raw_root.dataset_file("tushare", dataset, "2010-01")
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_parquet(path, compression="zstd")

    shared = {
        "trade_date": "20100104",
        "close": 14.92,
        **{
            column: 1.0
            for column in (
                "turnover_rate",
                "turnover_rate_f",
                "volume_ratio",
                "pe",
                "pe_ttm",
                "pb",
                "ps",
                "ps_ttm",
                "total_share",
                "float_share",
                "free_share",
                "total_mv",
                "circ_mv",
            )
        },
    }
    write(
        "daily_basic",
        [
            {**shared, "ts_code": "000043.SZ", "dv_ratio": 0.34, "dv_ttm": 0.34, "limit_status": 0},
            {
                **shared,
                "ts_code": "001914.SZ",
                "dv_ratio": 0.3351,
                "dv_ttm": 0.3351,
                "limit_status": 4,
            },
        ],
    )
    write(
        "daily",
        [
            {
                "ts_code": "000043.SZ",
                "trade_date": "20100104",
                "open": 15.27,
                "high": 15.28,
                "low": 14.85,
                "close": 14.92,
                "pre_close": 15.13,
            }
        ],
    )
    write(
        "stk_limit",
        [
            {
                "ts_code": "000043.SZ",
                "trade_date": "20100104",
                "pre_close": 15.13,
                "up_limit": 16.64,
                "down_limit": 13.62,
            }
        ],
    )
    cfg = Config({}, Environment(Path.cwd(), {"RAW_PARQUET_ROOT": str(tmp_raw_root.root)}))
    result = run_provider("tushare", pg_conn, cfg, only=["valuation_1d"], months=("2010-01",))
    assert result[0].rows_written == 1
    details = [
        r[0]
        for r in pg_conn.execute(
            "SELECT detail FROM ops.data_quality_check WHERE rule=%s",
            ("tushare_stock_alias_metadata_override",),
        ).fetchall()
    ]
    assert {r["field"] for r in details} == {"dv_ratio", "dv_ttm", "limit_status"}
    assert all(r["trading_day"] == "2010-01-04" for r in details)
    assert all(r["old_code"] == "000043.SZ" and r["canonical_code"] == "001914.SZ" for r in details)
    dv = next(r for r in details if r["field"] == "dv_ratio")
    assert dv["old_value"] == "0.34" and dv["new_value"] == "0.3351"
    pg_conn.commit()

    def fail_copy(*args, **kwargs):
        raise ValueError("forced COPY failure after audit staging")

    monkeypatch.setattr("gr_data.ingest.base.upsert_rows", fail_copy)
    with pytest.raises(IngestRunError, match="forced COPY failure"):
        run_provider("tushare", pg_conn, cfg, only=["valuation_1d"], months=("2010-01",))
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.data_quality_check WHERE rule=%s",
            ("tushare_stock_alias_metadata_override",),
        ).fetchone()[0]
        == 3
    )
    assert pg_conn.execute("SELECT count(*) FROM fundamental.valuation_1d").fetchone()[0] == 1


@pytest.mark.parametrize(
    "status,quote",
    [
        (4, {"open": 10, "high": 10.8, "low": 9.9, "close": 10.5}),
        (2, {"open": 11, "high": 11, "low": 11, "close": 11}),
        (7, {"open": 10, "high": 10.8, "low": 9.9, "close": 10.5}),
    ],
)
def test_legacy_limit_status_must_match_recomputed_enum_and_audit_nothing(status, quote):
    from datetime import date

    from gr_data.ingest.tushare.symbols import collapse_alias_rows

    audits = []
    with pytest.raises(ValueError, match="limit_status_mismatch_stop|invalid_limit_status_stop"):
        collapse_alias_rows(
            _legacy_pair_frame(
                limit_status=[0, status], close=[quote["close"]] * 2, dv_ratio=[0.34, 0.3351]
            ),
            {17: "001914.SZ"},
            price_evidence={
                (17, date(2010, 1, 4)): {**quote, "pre_close": 10, "limit_up": 11, "limit_down": 9}
            },
            audit=audits.append,
        )
    assert audits == []
