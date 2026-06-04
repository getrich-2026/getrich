from __future__ import annotations

import re

from getrich_data_import.common.config import Settings
from getrich_data_import.db.postgres import SCHEMA_FILES


def test_schema_manifest_files_exist() -> None:
    settings = Settings.load()
    missing = [name for name in SCHEMA_FILES if not (settings.sql_dir / name).exists()]
    assert missing == []


def test_appendix_a_migration_is_in_manifest() -> None:
    assert "60_review_appendix_a.sql" in SCHEMA_FILES


def test_market_schema_includes_stock_etf_and_raw_source_fields() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_review_appendix_a.sql").read_text(encoding="utf-8")

    for table_name in ["stock_bar_1d", "stock_bar_1m", "etf_bar_1d", "etf_bar_1m"]:
        assert f"market.{table_name}" in sql

    for column_name in ["trading_status", "limit_up", "limit_down", "pre_close", "pre_settle"]:
        assert column_name in sql


def test_appendix_a_incremental_migration_is_idempotent() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_review_appendix_a.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS pre_close" in sql
    assert "CREATE TABLE IF NOT EXISTS market.stock_bar_1d" in sql
    assert "CREATE TABLE IF NOT EXISTS market.etf_bar_1m" in sql


def test_appendix_a_documents_minute_adj_factor_join_paths() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "60_review_appendix_a.sql").read_text(encoding="utf-8")

    for asset in ["index", "future", "option", "stock", "etf"]:
        assert f"COMMENT ON TABLE market.{asset}_bar_1m" in sql
        assert f"join market.{asset}_bar_1d" in sql


def test_compress_ca_regular_materialized_view_fallback_is_plain_postgresql() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")
    fallback_blocks = re.findall(r"EXCEPTION WHEN OTHERS THEN(.*?)(?=END \$\$;)", sql, re.S)

    assert fallback_blocks
    for block in fallback_blocks:
        if "CREATE MATERIALIZED VIEW" not in block:
            continue
        assert not re.search(r"\b(?:first|last)\s*\(", block, re.I)


def test_compress_ca_notice_placeholders_remain_escaped_for_exec_driver_sql() -> None:
    settings = Settings.load()
    sql = (settings.sql_dir / "30_compress_ca.sql").read_text(encoding="utf-8")
    notices_with_sqlerrm = re.findall(r"RAISE NOTICE\s+'[^']+',\s+SQLERRM;", sql)

    assert notices_with_sqlerrm
    assert all("%%" in notice for notice in notices_with_sqlerrm)
