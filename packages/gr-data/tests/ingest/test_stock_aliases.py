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
