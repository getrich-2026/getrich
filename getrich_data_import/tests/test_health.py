from __future__ import annotations

from getrich_data_import.db.health import DatabaseHealth


def test_database_health_shape() -> None:
    health = DatabaseHealth(
        ok=True,
        server_version="16",
        timescaledb_installed=True,
        timescaledb_version="2.27.2",
        timescaledb_license="apache",
    )

    assert health.ok is True
    assert health.server_version == "16"
    assert health.timescaledb_installed is True
    assert health.timescaledb_version == "2.27.2"
    assert health.timescaledb_license == "apache"
