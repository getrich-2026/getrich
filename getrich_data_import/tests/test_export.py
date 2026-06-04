from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from getrich_data_import.export.duckdb import query_parquet
from getrich_data_import.export.parquet import export_bars_to_parquet


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Engine:
    def connect(self):
        return _Conn()


def test_export_bars_to_parquet_uses_filters_and_writes_atomically(tmp_path, monkeypatch) -> None:
    calls = {}

    def fake_read_sql_query(sql, conn, params):
        calls["sql"] = str(sql)
        calls["conn"] = conn
        calls["params"] = params
        return pd.DataFrame([{"symbol": "000300.XSHG", "close": 1.0}])

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    output = tmp_path / "bars.parquet"
    result = export_bars_to_parquet(
        _Engine(),  # type: ignore[arg-type]
        output_path=output,
        asset="index",
        freq="1d",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 2),
        symbols=["000300.XSHG"],
    )

    assert result.path == output
    assert result.rows == 1
    assert output.exists()
    assert calls["params"] == {
        "start_date": date(2026, 5, 1),
        "end_date": date(2026, 5, 2),
        "symbols": ["000300.XSHG"],
    }
    assert "market" in calls["sql"]
    assert "index_bar_1d" in calls["sql"]


def test_query_parquet_requires_duckdb_when_not_installed(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="DuckDB support requires"):
        query_parquet(tmp_path / "missing.parquet")
