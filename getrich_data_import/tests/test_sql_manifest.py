from __future__ import annotations

import re

from getrich_data_import.common.config import Settings
from getrich_data_import.db.postgres import SCHEMA_FILES


def test_schema_manifest_files_exist() -> None:
    settings = Settings.load()
    missing = [name for name in SCHEMA_FILES if not (settings.sql_dir / name).exists()]
    assert missing == []


def test_review_schema_additions_are_folded_into_base_market_schema() -> None:
    assert "60_review_appendix_a.sql" not in SCHEMA_FILES
    assert "70_review_followup.sql" not in SCHEMA_FILES


def test_market_schema_includes_stock_etf_and_raw_source_fields() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "20_market.sql").read_text(encoding="utf-8")

    for table_name in ["stock_bar_1d", "stock_bar_1m", "etf_bar_1d", "etf_bar_1m"]:
        assert f"market.{table_name}" in sql

    for column_name in [
        "trading_status",
        "limit_up",
        "limit_down",
        "pre_close",
        "pre_settle",
    ]:
        assert column_name in sql


def test_market_schema_creates_stock_etf_tables_directly() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "20_market.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS market.stock_bar_1d" in sql
    assert "CREATE TABLE IF NOT EXISTS market.etf_bar_1m" in sql
    assert "ADD COLUMN IF NOT EXISTS" not in sql


def test_market_schema_documents_minute_adj_factor_join_paths() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "20_market.sql").read_text(encoding="utf-8")

    for asset in ["index", "future", "option", "stock", "etf"]:
        assert f"COMMENT ON TABLE market.{asset}_bar_1m" in sql
        assert f"join market.{asset}_bar_1d" in sql


def test_market_schema_keeps_minute_raw_fields_in_schema() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "20_market.sql").read_text(encoding="utf-8")

    for asset in ["index", "future", "option", "stock", "etf"]:
        table_sql = re.search(
            rf"CREATE TABLE IF NOT EXISTS market\.{asset}_bar_1m \((.*?)\);",
            sql,
            re.S,
        )
        assert table_sql is not None
        for column in ["limit_up", "limit_down", "trading_status"]:
            assert column in table_sql.group(1)


def test_compress_ca_groups_day_rollups_by_trading_day() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")
    executable_sql = re.sub(r"--.*", "", sql)

    assert "GROUP BY instrument_id, trading_day" in sql
    assert "WITH (timescaledb.continuous)" not in executable_sql
    assert "GROUP BY instrument_id, date_trunc('day', dt)" not in executable_sql
    assert "time_bucket(" not in executable_sql


def test_compress_ca_covers_all_minute_market_tables() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")

    for asset in ["index", "stock", "etf", "future", "option"]:
        assert f"ALTER TABLE market.{asset}_bar_1m SET" in sql
        assert f"add_compression_policy('market.{asset}_bar_1m'" in sql
        assert f"CREATE MATERIALIZED VIEW IF NOT EXISTS market.{asset}_bar_1d_ca" in sql


def test_compress_ca_materialized_views_are_plain_postgresql() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")
    materialized_view_blocks = re.findall(
        r"CREATE MATERIALIZED VIEW IF NOT EXISTS .*?WITH NO DATA;",
        sql,
        re.S,
    )

    assert materialized_view_blocks


def test_compress_ca_notice_placeholders_remain_escaped_for_exec_driver_sql() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")
    notices_with_sqlerrm = re.findall(r"RAISE NOTICE\s+'[^']+',\s+SQLERRM;", sql)

    assert notices_with_sqlerrm
    assert all("%%" in notice for notice in notices_with_sqlerrm)


def test_meta_schema_has_fk_indexes_without_redundant_symbol_map_index() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "10_meta.sql").read_text(encoding="utf-8")

    assert "idx_symbol_map_instrument" not in sql
    assert "chk_calendar_exchange_not_blank" in sql
    assert "idx_option_contracts_underlying" in sql


def test_market_schema_has_cross_sectional_minute_dt_indexes() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "20_market.sql").read_text(encoding="utf-8")

    for asset in ["index", "stock", "etf", "future", "option"]:
        assert f"idx_{asset}_bar_1m_dt" in sql
        assert f"ON market.{asset}_bar_1m USING brin (dt)" in sql


def test_realtime_schema_compresses_tick_buffer_before_retention() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "40_realtime.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE realtime.tick_buffer SET" in sql
    assert "add_compression_policy('realtime.tick_buffer', INTERVAL '2 days'" in sql
    assert "add_retention_policy('realtime.tick_buffer', INTERVAL '7 days'" in sql


def test_ops_schema_has_api_key_and_quality_indexes() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "50_ops.sql").read_text(encoding="utf-8")

    assert "api_key_hash VARCHAR(128) UNIQUE NOT NULL" in sql
    assert "REFERENCES ops.users(user_id) ON DELETE CASCADE" in sql
    assert "idx_api_keys_user_id" in sql
    assert "chk_etl_job_run_timestamps" in sql
    assert "idx_quality_check_detail" in sql


def test_insight_schema_creates_staging_schema_for_local_parquet_manifest() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_insight.sql").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS staging" in sql


def test_insight_schema_tracks_parquet_staging_and_artifacts() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_insight.sql").read_text(encoding="utf-8")

    for table_name in [
        "ops.dataset_catalog",
        "ops.import_checkpoint",
        "staging.parquet_file",
        "ops.duckdb_artifact",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql

    assert "UNIQUE (provider, dataset_name, source_path)" in sql
    assert "status IN ('written', 'loaded', 'failed', 'superseded')" in sql
    assert (
        "artifact_type IN ('raw_sample', 'validation', 'adjustment', 'snapshot')" in sql
    )


def test_insight_schema_adds_p1_canonical_market_tables() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_insight.sql").read_text(encoding="utf-8")

    for table_name in [
        "stock_adj_factor",
        "stock_daily_basic",
        "stock_valuation",
        "index_component",
        "fund_daily",
        "fund_nav",
        "etf_basket",
        "etf_redemption",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS market.{table_name}" in sql


def test_insight_schema_makes_time_series_tables_hypertables() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_insight.sql").read_text(encoding="utf-8")

    for table_name in [
        "stock_adj_factor",
        "stock_daily_basic",
        "stock_valuation",
        "index_component",
        "fund_daily",
        "fund_nav",
        "etf_basket",
        "etf_redemption",
    ]:
        assert f"create_hypertable('market.{table_name}'" in sql
