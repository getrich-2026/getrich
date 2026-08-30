"""Tests for catalog reflection used by the data dictionary."""

from __future__ import annotations

from typing import Any

from gr_db.docs.introspect import introspect_postgres


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]] | Exception) -> None:
        self._rows = rows

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str) -> None:
        if isinstance(self._rows, Exception):
            raise self._rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


class _Connection:
    def __init__(self, responses: list[list[tuple[Any, ...]] | Exception]) -> None:
        self._responses = iter(responses)

    def cursor(self) -> _Cursor:
        return _Cursor(next(self._responses))


def test_introspect_postgres_returns_catalog_when_timescaledb_is_unavailable() -> None:
    """Timescale 元数据失败时仍返回完整的普通表 catalog。"""
    conn = _Connection(
        [
            [("market", "stock_bar_1d", "日线", 120, 4096)],
            [
                ("market", "stock_bar_1d", "dt", "date", False, None, "交易日"),
                ("market", "stock_bar_1d", "close", "numeric", True, "0", None),
            ],
            [("market", "stock_bar_1d", "stock_bar_1d_pkey", "PRIMARY KEY (dt)")],
            [("market", "stock_bar_1d", "idx_close", "CREATE INDEX idx_close ON ...")],
            RuntimeError("timescaledb is not installed"),
        ]
    )

    schemas = introspect_postgres(conn)

    assert len(schemas) == 1
    table = schemas[0].tables[0]
    assert table.qualified == "market.stock_bar_1d"
    assert table.row_estimate == 120
    assert table.columns[0].comment == "交易日"
    assert table.columns[1].nullable is True
    assert table.hypertable is None
    assert "stock_bar_1d_pkey" in table.constraints[0]
