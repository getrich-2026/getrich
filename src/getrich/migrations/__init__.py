"""Database migration runner for the GetRich platform.

Provides a small, dependency-free migration runner that:

* Reads ``migrations/*.sql`` for PostgreSQL migrations (filename prefix
  ``NNN_``, sorted lexicographically by the numeric prefix).
* Reads ``migrations/clickhouse/*.sql`` for ClickHouse migrations
  (same naming convention).
* Tracks applied migrations in a ``schema_migrations`` table in each
  database.
* Applies only new migrations in numeric order; re-runs are no-ops.
* Fails loudly on out-of-order numeric gaps (e.g. jumping from 003
  to 005) and on duplicate prefixes.

The runner is invoked via ``python -m getrich.migrations.cli`` (see
``getrich.migrations.cli``).
"""
