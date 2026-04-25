from pathlib import Path

import duckdb
import pandas as pd
import polars as pl


class QuantDuckDB:
    """
    QuantDuckDB: A wrapper around DuckDB optimized for quantitative research.

    Features:
    - Default integration with Polars for high-performance data exchange.
    - Context manager support.
    - Simplified Parquet I/O.
    """

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        """
        Initialize QuantDuckDB.

        Args:
            db_path: Path to the DuckDB file. If None, creates an in-memory database.
            read_only: If True, opens the database in read-only mode (only for file-based).
        """
        self.db_path = str(db_path) if db_path else ":memory:"
        self.read_only = read_only
        self.con: duckdb.DuckDBPyConnection | None = None
        self._get_connection()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Ensure connection is open."""
        if self.con is None:
            self.con = duckdb.connect(database=self.db_path, read_only=self.read_only)
        return self.con

    def __enter__(self) -> "QuantDuckDB":
        self._get_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        if self.con:
            self.con.close()
            self.con = None

    def query(self, sql: str) -> pl.DataFrame:
        """
        Execute a SQL query and return the result as a Polars DataFrame.

        Args:
            sql: SQL query string.

        Returns:
            pl.DataFrame: Query result.
        """
        con = self._get_connection()
        return con.sql(sql).pl()

    def execute(self, sql: str) -> None:
        """
        Execute a SQL statement (DDL/DML) without returning a result.

        Args:
            sql: SQL statement.
        """
        con = self._get_connection()
        con.execute(sql)

    def register(self, name: str, df: pl.DataFrame | pd.DataFrame) -> None:
        """
        Register a DataFrame (Polars or Pandas) as a virtual table.

        Args:
            name: Name of the virtual table.
            df: Polars or Pandas DataFrame.
        """
        con = self._get_connection()
        # DuckDB supports direct registration of Polars and Pandas DataFrames
        con.register(name, df)

    def read_parquet(self, name: str, path: str | Path | list[str]) -> None:
        """
        Create a view from Parquet file(s).

        Args:
            name: Name of the view to create.
            path: Path to parquet file(s). Can be a glob string or list of paths.
        """
        con = self._get_connection()
        if isinstance(path, (list, tuple)):
            # Handle list of files: read_parquet(['a.parquet', 'b.parquet'])
            path_str = "[" + ", ".join([f"'{str(p)}'" for p in path]) + "]"
            sql = f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet({path_str})"
        else:
            sql = f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{str(path)}')"

        con.execute(sql)

    def write_parquet(
        self,
        table: str,
        path: str | Path,
        partition_by: list[str] | None = None,
        compression: str = "zstd",
    ) -> None:
        """
        Export a table or view to a Parquet file.

        Args:
            table: Table or view name.
            path: Destination path.
            partition_by: List of columns to partition by (optional).
            compression: Compression codec (default: zstd).
        """
        con = self._get_connection()
        sql = f"COPY (SELECT * FROM {table}) TO '{str(path)}' (FORMAT PARQUET, COMPRESSION {compression}"

        if partition_by:
            cols = ", ".join(partition_by)
            sql += f", PARTITION_BY ({cols})"

        sql += ")"
        con.execute(sql)

    def list_tables(self) -> pl.DataFrame:
        """
        List all tables and views in the database.

        Returns:
            pl.DataFrame: List of tables/views with details.
        """
        return self.query("SHOW TABLES")


if __name__ == "__main__":
    # Minimal smoke test
    print("Running QuantDuckDB smoke test...")

    # In-memory test
    with QuantDuckDB() as db:
        df = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        db.register("test_table", df)

        result = db.query("SELECT * FROM test_table WHERE a > 1")
        print("Query Result:")
        print(result)

        assert result.height == 2
        assert result["a"].sum() == 5

        print("Smoke test passed!")
