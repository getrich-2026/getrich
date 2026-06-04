from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class DatabaseHealth:
    ok: bool
    server_version: str | None
    timescaledb_installed: bool
    timescaledb_version: str | None
    timescaledb_license: str | None


def check_database(engine: Engine) -> DatabaseHealth:
    with engine.begin() as conn:
        version = conn.execute(text("SHOW server_version")).scalar()
        timescaledb_installed = bool(
            conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_extension
                        WHERE extname = 'timescaledb'
                    )
                    """
                )
            ).scalar()
        )
        timescaledb_version = None
        timescaledb_license = None
        if timescaledb_installed:
            timescaledb_version = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar()
            timescaledb_license = conn.execute(text("SHOW timescaledb.license")).scalar()
    return DatabaseHealth(
        ok=True,
        server_version=str(version) if version else None,
        timescaledb_installed=timescaledb_installed,
        timescaledb_version=str(timescaledb_version) if timescaledb_version else None,
        timescaledb_license=str(timescaledb_license) if timescaledb_license else None,
    )
