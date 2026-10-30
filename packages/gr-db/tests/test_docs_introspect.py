"""Tests for catalog reflection used by the data dictionary."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from gr_db.docs.introspect import introspect_clickhouse, introspect_postgres
from psycopg import errors as pg_errors


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]] | Exception) -> None:
        self._rows = rows

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: object = None) -> None:
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
            pg_errors.UndefinedTable("relation timescaledb_information.hypertables does not exist"),
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


def _catalog_rows(row_estimate: int | None, total_bytes: int) -> list[list[tuple[Any, ...]]]:
    return [
        [("market", "stock_bar_1d", "日线", row_estimate, total_bytes)],
        [("market", "stock_bar_1d", "dt", "date", False, None, "交易日")],
        [],
        [],
    ]


def test_introspect_postgres_uses_chunk_totals_for_hypertables() -> None:
    """超表父表统计接近 0，必须用 Timescale 汇总的行数与大小替换。"""
    conn = _Connection(
        [*_catalog_rows(0, 8192), [("market", "stock_bar_1d", "dt", "enabled", 5_000_000, 3 << 30)]]
    )

    table = introspect_postgres(conn)[0].tables[0]

    assert table.row_estimate == 5_000_000
    assert table.total_bytes == 3 << 30
    assert table.hypertable == "dt"
    assert table.compression == "enabled"


def test_introspect_postgres_propagates_non_timescale_errors() -> None:
    """权限等非「扩展不存在」错误不能被当成降级吞掉。"""
    conn = _Connection([*_catalog_rows(None, 0), pg_errors.InsufficientPrivilege("denied")])

    with pytest.raises(pg_errors.InsufficientPrivilege):
        introspect_postgres(conn)


def test_introspect_clickhouse_derives_nullable_from_outer_type() -> None:
    """只有最外层 Nullable 包装才算列可空，默认表达式应保留。"""
    results = iter(
        [
            SimpleNamespace(
                result_rows=[
                    ("factor", "factors_long", "MergeTree", "toYYYYMM(dt)", "factor, dt", "", 10, 1)
                ]
            ),
            SimpleNamespace(
                result_rows=[
                    ("factor", "factors_long", "dt", "DateTime64(3, 'Asia/Shanghai')", "", ""),
                    ("factor", "factors_long", "value", "Nullable(Float64)", "", "因子值"),
                    ("factor", "factors_long", "tag", "LowCardinality(Nullable(String))", "", ""),
                    ("factor", "factors_long", "tags", "Array(Nullable(String))", "[]", ""),
                ]
            ),
        ]
    )
    client = SimpleNamespace(query=lambda _sql: next(results))

    table = introspect_clickhouse(client)[0]

    assert [column.nullable for column in table.columns] == [False, True, True, False]
    assert table.columns[3].default == "[]"
    assert table.columns[1].comment == "因子值"
    assert table.partition_key == "toYYYYMM(dt)"
