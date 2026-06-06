"""Tests for ``getrich.libs.quant_duckdb.QuantDuckDB``.

QuantDuckDB is a thin wrapper around a DuckDB connection.
Two design choices drive most of the test surface:

1. **In-memory mode** when ``db_path is None`` — used for
   ad-hoc analysis. The default mode is the only one that
   supports ``read_only=True`` (no — `read_only` is for
   file-based; in-memory is always writable).
2. **Polars-first** return types: `query()` returns
   ``pl.DataFrame`` rather than ``pd.DataFrame``. The
   public surface explicitly favours Polars for the
   high-performance backtest/research use-case.
3. **Virtual views for Parquet** — `read_parquet()` creates
   a SQL view, so subsequent `query()` calls can select
   from the view by name.

These tests use the in-memory backend, so no tempfiles
are created and tests run quickly.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from getrich.libs.quant_duckdb import QuantDuckDB


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> QuantDuckDB:
    """In-memory DuckDB instance for the duration of one
    test. Closed at teardown so the WAL is clean."""
    instance = QuantDuckDB()
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Construction & lifecycle
# ---------------------------------------------------------------------------


def test_default_constructor_uses_in_memory_backend() -> None:
    """With no `db_path`, the wrapper opens an in-memory
    DuckDB. The internal `db_path` string is the canonical
    `":memory:"` sentinel."""
    instance = QuantDuckDB()

    assert instance.db_path == ":memory:"
    assert instance.con is not None

    instance.close()


def test_connection_is_open_after_init() -> None:
    """`_get_connection()` is called from `__init__`, so the
    `con` attribute is non-None immediately after construction."""
    instance = QuantDuckDB()

    assert instance.con is not None
    assert instance._get_connection() is instance.con

    instance.close()


def test_close_clears_connection() -> None:
    """`close()` sets `con` back to None so the next
    `_get_connection()` call re-opens (per the wrapper's
    lazy-reopen pattern)."""
    instance = QuantDuckDB()
    instance.close()

    assert instance.con is None


def test_close_is_idempotent() -> None:
    """Calling `close()` twice must not raise — the
    `if self.con:` guard handles this."""
    instance = QuantDuckDB()
    instance.close()
    instance.close()  # should be a no-op

    assert instance.con is None


def test_get_connection_reopens_after_close() -> None:
    """After `close()`, the next `_get_connection()` call
    transparently re-opens the database. Same db_path."""
    instance = QuantDuckDB()
    instance.close()
    con = instance._get_connection()

    assert instance.con is con
    assert con is not None

    instance.close()


def test_context_manager_closes_on_exit() -> None:
    """`__exit__` calls `close()`, so the connection is
    invalidated when the with-block ends."""
    with QuantDuckDB() as db:
        assert db.con is not None

    assert db.con is None


def test_context_manager_yields_self() -> None:
    """`__enter__` returns the wrapper instance, not the
    raw DuckDB connection."""
    db = QuantDuckDB()
    with db as ctx:
        assert ctx is db
    db.close()


def test_repr_is_not_required_but_no_attribute_error() -> None:
    """The wrapper doesn't define `__repr__` — but the
    default repr must not raise. (Sanity check: we have
    no contract on the string itself.)"""
    db = QuantDuckDB()
    try:
        str(db)
    except Exception as exc:  # pragma: no cover - defensive
        pytest.fail(f"str(db) raised: {exc}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# query() — Polars DataFrame output
# ---------------------------------------------------------------------------


def test_query_returns_polars_dataframe() -> None:
    """`query()` returns `pl.DataFrame`, not `pd.DataFrame`.
    This is the wrapper's main API choice: Polars is the
    preferred research format in the backtest package."""
    db = QuantDuckDB()
    db.register("t", pl.DataFrame({"a": [1, 2, 3]}))

    result = db.query("SELECT * FROM t")

    assert isinstance(result, pl.DataFrame)
    assert result.shape == (3, 1)
    assert result["a"].to_list() == [1, 2, 3]
    db.close()


def test_query_supports_where_clause(db: QuantDuckDB) -> None:
    """The canonical use case: filter with WHERE and
    check the row count + values."""
    db.register("nums", pl.DataFrame({"x": [1, 2, 3, 4, 5]}))

    result = db.query("SELECT * FROM nums WHERE x > 3")

    assert result.shape == (2, 1)
    assert result["x"].to_list() == [4, 5]


def test_query_aggregations_work(db: QuantDuckDB) -> None:
    """DuckDB's SQL engine supports GROUP BY / SUM / etc.
    transparently through `con.sql().pl()`."""
    db.register(
        "sales",
        pl.DataFrame({"region": ["A", "A", "B"], "amount": [10, 20, 5]}),
    )

    result = db.query(
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region ORDER BY region",
    )

    assert result.shape == (2, 2)
    assert result["region"].to_list() == ["A", "B"]
    assert result["total"].to_list() == [30, 5]


# ---------------------------------------------------------------------------
# execute() — DDL/DML without result
# ---------------------------------------------------------------------------


def test_execute_creates_table() -> None:
    """`execute()` runs DDL/DML and returns None. The table
    is then queryable."""
    db = QuantDuckDB()
    db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    db.execute("INSERT INTO t VALUES (1, 'alice'), (2, 'bob')")

    result = db.query("SELECT * FROM t ORDER BY id")

    assert result.shape == (2, 2)
    assert result["name"].to_list() == ["alice", "bob"]
    db.close()


def test_execute_returns_none() -> None:
    """`execute()` is documented to return None for DDL/DML
    (no result)."""
    db = QuantDuckDB()

    assert db.execute("CREATE TABLE t (x INT)") is None
    db.close()


# ---------------------------------------------------------------------------
# register() — virtual tables from Polars or Pandas
# ---------------------------------------------------------------------------


def test_register_polars_dataframe(db: QuantDuckDB) -> None:
    """Polars DFs are registered as a queryable virtual table."""
    df = pl.DataFrame({"k": ["a", "b"], "v": [1, 2]})
    db.register("kv", df)

    result = db.query("SELECT * FROM kv ORDER BY k")

    assert result.shape == (2, 2)
    assert result["k"].to_list() == ["a", "b"]
    assert result["v"].to_list() == [1, 2]


def test_register_pandas_dataframe(db: QuantDuckDB) -> None:
    """Pandas DFs are also supported — DuckDB's `register()`
    accepts both, which makes the wrapper a useful bridge."""
    df = pd.DataFrame({"k": ["x", "y"], "v": [10, 20]})
    db.register("kv_pd", df)

    result = db.query("SELECT * FROM kv_pd ORDER BY k")

    assert result.shape == (2, 2)
    assert result["k"].to_list() == ["x", "y"]
    assert result["v"].to_list() == [10, 20]


def test_register_with_existing_name_replaces(db: QuantDuckDB) -> None:
    """`con.register()` allows re-registration; the second
    call replaces the virtual table contents."""
    db.register("t", pl.DataFrame({"x": [1]}))
    db.register("t", pl.DataFrame({"x": [100, 200]}))

    result = db.query("SELECT * FROM t ORDER BY x")

    assert result["x"].to_list() == [100, 200]


# ---------------------------------------------------------------------------
# read_parquet() / write_parquet() — file roundtrip
# ---------------------------------------------------------------------------


def test_write_parquet_then_read_via_view(tmp_path: Path) -> None:
    """Roundtrip: write a table to Parquet, register the
    file as a view, query it. Verifies that the COPY
    statement and the read_parquet view both work."""
    db = QuantDuckDB()
    db.register(
        "bars",
        pl.DataFrame(
            {
                "symbol": ["rb2410", "rb2410", "cu2412"],
                "close": [3500.0, 3520.0, 78000.0],
            }
        ),
    )

    out = tmp_path / "bars.parquet"
    db.write_parquet("bars", out)

    db.read_parquet("bars_v", str(out))
    result = db.query("SELECT * FROM bars_v ORDER BY close")

    assert result.shape == (3, 2)
    assert result["symbol"].to_list() == ["rb2410", "rb2410", "cu2412"]
    assert result["close"].to_list() == [3500.0, 3520.0, 78000.0]

    db.close()


def test_read_parquet_accepts_list_of_paths(tmp_path: Path) -> None:
    """The list-form of `read_parquet()` builds a
    `read_parquet([...])` SQL expression so DuckDB can
    concatenate multiple files in a single virtual view."""
    db = QuantDuckDB()
    p1 = tmp_path / "a.parquet"
    p2 = tmp_path / "b.parquet"

    db.register("t1", pl.DataFrame({"x": [1, 2]}))
    db.register("t2", pl.DataFrame({"x": [3, 4]}))
    db.write_parquet("t1", p1)
    db.write_parquet("t2", p2)

    db.read_parquet("combined", [str(p1), str(p2)])
    result = db.query("SELECT * FROM combined ORDER BY x")

    assert result["x"].to_list() == [1, 2, 3, 4]
    db.close()


def test_read_parquet_accepts_glob_string(tmp_path: Path) -> None:
    """The string-form supports a glob pattern (DuckDB
    expands it natively)."""
    db = QuantDuckDB()
    p1 = tmp_path / "x1.parquet"
    p2 = tmp_path / "x2.parquet"

    db.register("t", pl.DataFrame({"v": [10]}))
    db.write_parquet("t", p1)
    db.write_parquet("t", p2)

    db.read_parquet("v_glob", str(tmp_path / "*.parquet"))
    result = db.query("SELECT * FROM v_glob")

    assert result.shape == (2, 1)
    assert sorted(result["v"].to_list()) == [10, 10]
    db.close()


def test_write_parquet_uses_zstd_compression_by_default(tmp_path: Path) -> None:
    """The default `compression='zstd'` is encoded in the
    SQL `COPY ... COMPRESSION zstd` clause. We assert by
    confirming the file is readable (a corrupt compression
    codec would raise)."""
    db = QuantDuckDB()
    db.register("t", pl.DataFrame({"v": [1, 2, 3]}))

    out = tmp_path / "default.parquet"
    db.write_parquet("t", out)

    assert out.exists()
    # Roundtrip via DuckDB to confirm the file is valid:
    db.read_parquet("v_check", str(out))
    result = db.query("SELECT * FROM v_check ORDER BY v")
    assert result["v"].to_list() == [1, 2, 3]
    db.close()


def test_write_parquet_with_partition_by(tmp_path: Path) -> None:
    """`partition_by` triggers a Hive-style layout. We
    confirm the directory is created and the data is
    queryable (DuckDB unions all parts transparently)."""
    db = QuantDuckDB()
    db.register(
        "sales",
        pl.DataFrame(
            {
                "region": ["A", "A", "B", "B"],
                "amount": [10, 20, 5, 15],
            }
        ),
    )

    out = tmp_path / "partitioned"
    db.write_parquet("sales", out, partition_by=["region"])

    # The output is a directory of subdirs/parts.
    assert out.exists()
    parts = list(out.rglob("*.parquet"))
    assert len(parts) >= 2  # one part per region, at minimum

    # The directory itself is readable as a Hive dataset:
    db.read_parquet("ds", str(out))
    result = db.query("SELECT region, SUM(amount) AS total FROM ds GROUP BY region ORDER BY region")
    assert result["region"].to_list() == ["A", "B"]
    assert result["total"].to_list() == [30, 20]
    db.close()


def test_write_parquet_accepts_path_object(tmp_path: Path) -> None:
    """`path` accepts `str | Path` — `str(path)` is invoked
    inside the SQL, so the value is wrapped in single
    quotes regardless of input type."""
    db = QuantDuckDB()
    db.register("t", pl.DataFrame({"x": [42]}))

    out = tmp_path / "p.parquet"
    db.write_parquet("t", out)  # Path object, not str

    db.read_parquet("v", str(out))
    result = db.query("SELECT * FROM v")
    assert result["x"].to_list() == [42]
    db.close()


# ---------------------------------------------------------------------------
# list_tables() — introspection
# ---------------------------------------------------------------------------


def test_list_tables_returns_polars_dataframe(db: QuantDuckDB) -> None:
    """`list_tables()` is a thin wrapper around `SHOW TABLES`."""
    db.execute("CREATE TABLE alpha (x INT)")
    db.execute("CREATE TABLE beta (y INT)")

    result = db.list_tables()

    assert isinstance(result, pl.DataFrame)
    names = sorted(result["name"].to_list())
    assert "alpha" in names
    assert "beta" in names


def test_list_tables_includes_views(db: QuantDuckDB, tmp_path: Path) -> None:
    """`SHOW TABLES` in DuckDB returns both tables AND
    views — `read_parquet()` creates a view, so it should
    appear in the listing."""
    db.register("t", pl.DataFrame({"x": [1]}))
    out = tmp_path / "v.parquet"
    db.write_parquet("t", out)
    db.read_parquet("v_view", str(out))

    result = db.list_tables()
    names = result["name"].to_list()

    assert "v_view" in names
