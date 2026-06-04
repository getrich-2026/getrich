from __future__ import annotations

import pandas as pd

from getrich_data_import.load.postgres import upsert_dataframe


class _Result:
    rowcount = 1


class _Conn:
    def __init__(self) -> None:
        self.sql = None

    def execute(self, sql):
        self.sql = sql
        return _Result()


def test_upsert_dataframe_returns_database_rowcount(monkeypatch) -> None:
    conn = _Conn()
    frame = pd.DataFrame([{"id": 1, "value": "a"}, {"id": 1, "value": "a"}])
    to_sql_calls = []

    monkeypatch.setattr("getrich_data_import.load.postgres.table_columns", lambda *_args: ["id", "value"])
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
