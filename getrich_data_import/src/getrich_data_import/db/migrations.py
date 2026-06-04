from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from getrich_data_import.db.postgres import SCHEMA_FILES


@dataclass(frozen=True)
class MigrationResult:
    file_name: str
    status: str


def apply_migrations(engine: Engine, sql_dir: Path) -> list[MigrationResult]:
    results: list[MigrationResult] = []
    with engine.begin() as conn:
        _ensure_table(conn)
        for file_name in SCHEMA_FILES:
            path = sql_dir / file_name
            sql = path.read_text(encoding="utf-8")
            checksum = _checksum(sql)
            existing = conn.execute(
                text(
                    """
                    SELECT checksum
                    FROM ops.schema_migrations
                    WHERE file_name = :file_name
                    """
                ),
                {"file_name": file_name},
            ).scalar()
            if existing:
                if existing != checksum:
                    raise ValueError(
                        f"migration checksum changed for {file_name}: "
                        f"database={existing} current={checksum}"
                    )
                results.append(MigrationResult(file_name, "skipped"))
                continue

            conn.exec_driver_sql(sql)
            conn.execute(
                text(
                    """
                    INSERT INTO ops.schema_migrations (file_name, checksum, applied_at)
                    VALUES (:file_name, :checksum, now())
                    """
                ),
                {"file_name": file_name, "checksum": checksum},
            )
            results.append(MigrationResult(file_name, "applied"))
    return results


def _ensure_table(conn) -> None:
    conn.exec_driver_sql(
        """
        CREATE SCHEMA IF NOT EXISTS ops;
        CREATE TABLE IF NOT EXISTS ops.schema_migrations (
            file_name  TEXT PRIMARY KEY,
            checksum   TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()

