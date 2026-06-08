from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from getrich_data_import.db.postgres import SCHEMA_FILES


EXPECTED_TABLES = {
    "market.future_bar_1d",
    "market.future_bar_1m",
    "market.etf_bar_1d",
    "market.etf_bar_1m",
    "market.index_bar_1d",
    "market.index_bar_1m",
    "market.index_component",
    "market.option_bar_1d",
    "market.option_bar_1m",
    "market.option_greeks_1d",
    "market.etf_basket",
    "market.etf_redemption",
    "market.fund_daily",
    "market.fund_nav",
    "market.stock_adj_factor",
    "market.stock_bar_1d",
    "market.stock_bar_1m",
    "market.stock_daily_basic",
    "market.stock_valuation",
    "meta.future_contracts",
    "meta.instruments",
    "meta.option_contracts",
    "meta.symbol_map",
    "meta.trading_calendar",
    "ops.api_keys",
    "ops.data_quality_check",
    "ops.dataset_catalog",
    "ops.duckdb_artifact",
    "ops.etl_job_run",
    "ops.import_checkpoint",
    "ops.schema_migrations",
    "ops.users",
    "realtime.tick_buffer",
    "staging.parquet_file",
}

EXPECTED_HYPERTABLES = {
    "market.future_bar_1d",
    "market.future_bar_1m",
    "market.etf_bar_1d",
    "market.etf_bar_1m",
    "market.index_bar_1d",
    "market.index_bar_1m",
    "market.index_component",
    "market.option_bar_1d",
    "market.option_bar_1m",
    "market.etf_basket",
    "market.etf_redemption",
    "market.fund_daily",
    "market.fund_nav",
    "market.stock_adj_factor",
    "market.stock_bar_1d",
    "market.stock_bar_1m",
    "market.stock_daily_basic",
    "market.stock_valuation",
    "realtime.tick_buffer",
}


@dataclass(frozen=True)
class SchemaCheckResult:
    missing_tables: tuple[str, ...]
    missing_hypertables: tuple[str, ...]
    missing_migrations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (
            not self.missing_tables
            and not self.missing_hypertables
            and not self.missing_migrations
        )


def check_schema(engine: Engine) -> SchemaCheckResult:
    with engine.begin() as conn:
        tables = set(
            conn.execute(
                text(
                    """
                    SELECT table_schema || '.' || table_name
                    FROM information_schema.tables
                    WHERE table_schema IN ('meta', 'market', 'realtime', 'ops', 'staging')
                      AND table_type = 'BASE TABLE'
                    """
                )
            ).scalars()
        )
        hypertables = set(
            conn.execute(
                text(
                    """
                    SELECT hypertable_schema || '.' || hypertable_name
                    FROM timescaledb_information.hypertables
                    """
                )
            ).scalars()
        )
        migrations = set(
            conn.execute(text("SELECT file_name FROM ops.schema_migrations")).scalars()
        )

    return SchemaCheckResult(
        missing_tables=tuple(sorted(EXPECTED_TABLES - tables)),
        missing_hypertables=tuple(sorted(EXPECTED_HYPERTABLES - hypertables)),
        missing_migrations=tuple(sorted(set(SCHEMA_FILES) - migrations)),
    )
