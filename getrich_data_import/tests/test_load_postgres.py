from __future__ import annotations

from datetime import date

import pandas as pd

from getrich_data_import.load.postgres import (
    attach_instrument_ids,
    finish_job_run,
    insert_job_run,
    upsert_dataframe,
)


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


def test_job_run_audit_writes_dataset_request_and_checkpoint() -> None:
    class _ScalarResult:
        def scalar_one(self):
            return 99

    class _AuditConn:
        def __init__(self) -> None:
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((str(sql), params))
            return _ScalarResult()

    conn = _AuditConn()
    run_id = insert_job_run(
        conn,  # type: ignore[arg-type]
        job_name="fetch_fund_nav_parquet",
        provider="insight",
        dataset_name="fund_nav",
        start_date=date(2026, 6, 4),
        end_date=date(2026, 6, 4),
        request={"symbols": ["161725.SZ"]},
    )
    finish_job_run(
        conn,  # type: ignore[arg-type]
        run_id=run_id,
        status="success",
        rows_written=1,
        warning_count=2,
        checkpoint={"files_written": 1},
    )

    insert_sql, insert_params = conn.calls[0]
    update_sql, update_params = conn.calls[1]
    assert run_id == 99
    assert "provider" in insert_sql
    assert insert_params["dataset_name"] == "fund_nav"
    assert '"161725.SZ"' in insert_params["request"]
    assert "warning_count = :warning_count" in update_sql
    assert update_params["warning_count"] == 2
    assert '"files_written": 1' in update_params["checkpoint"]
