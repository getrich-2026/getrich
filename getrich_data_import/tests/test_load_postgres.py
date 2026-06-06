from __future__ import annotations

import pandas as pd

from getrich_data_import.load.postgres import attach_instrument_ids, upsert_dataframe


class _Result:
    rowcount = 1


class _Conn:
    def __init__(self) -> None:
        self.sqls = []

    def execute(self, sql):
        self.sqls.append(sql)
        return _Result()


def test_upsert_dataframe_returns_database_rowcount(monkeypatch) -> None:
    conn = _Conn()
    frame = pd.DataFrame([{"id": 1, "value": "a"}, {"id": 1, "value": "a"}])
    to_sql_calls = []

    monkeypatch.setattr("getrich_data_import.load.postgres.table_columns", lambda *_args: ["id", "value"])
    monkeypatch.setattr(
        "getrich_data_import.load.postgres.table_column_types",
        lambda *_args: {"id": "bigint", "value": "text"},
    )
    monkeypatch.setattr(pd.DataFrame, "to_sql", lambda self, *args, **kwargs: to_sql_calls.append((args, kwargs)))

    written = upsert_dataframe(
        conn,  # type: ignore[arg-type]
        frame,
        schema="public",
        table="example",
        primary_keys=("id",),
    )

    assert written == 1
    assert len(to_sql_calls) == 1
    assert '"id"::bigint' in str(conn.sqls[0])
    assert '"value"::text' in str(conn.sqls[0])
    assert "DROP TABLE IF EXISTS pg_temp." in str(conn.sqls[1])


def test_attach_instrument_ids_keeps_mapping_dimensions(monkeypatch) -> None:
    class _Mapping:
        instrument_id = 10
        asset = "stock"
        exchange = "SH"
        symbol = "600000.SH"

    monkeypatch.setattr(
        "getrich_data_import.load.postgres.SymbolMapService.resolve_many",
        lambda self, **kwargs: {"600000.SH": _Mapping()},
    )
    frame = pd.DataFrame([{"source_symbol": "600000.SH", "close": 1}])

    out = attach_instrument_ids(object(), frame, source="yinhe")  # type: ignore[arg-type]

    assert out.loc[0, "instrument_id"] == 10
    assert out.loc[0, "asset"] == "stock"
    assert out.loc[0, "exchange"] == "SH"
    assert out.loc[0, "symbol"] == "600000.SH"
