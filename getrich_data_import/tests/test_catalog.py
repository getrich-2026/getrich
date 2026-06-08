from __future__ import annotations

import pytest

from getrich_data_import.catalog import dataset_specs_for_provider, get_dataset_spec


def test_insight_catalog_includes_parquet_staging_and_ready_bars() -> None:
    specs = dataset_specs_for_provider("insight")
    names = {spec.name for spec in specs}

    assert "parquet_staging" in names
    assert "stock_bar_1d" in names
    assert "stock_adj_factor" in names
    assert "etf_daily" in names
    assert "etf_nav" in names
    assert "fund_nav" in names
    assert "etf_redemption" in names

    staging = get_dataset_spec("insight", "parquet-staging")
    assert staging.storage == "parquet_staging"
    assert staging.target == "staging.parquet_file"

    stock_bar = get_dataset_spec("insight", "stock_bar_1d")
    assert stock_bar.status == "ready"
    assert stock_bar.target == "market.stock_bar_1d"

    etf_nav = get_dataset_spec("insight", "etf_nav")
    assert etf_nav.target == "market.etf_nav"
    assert etf_nav.status == "ready"

    fund_nav = get_dataset_spec("insight", "fund_nav")
    assert fund_nav.target == "market.fund_nav"
    assert fund_nav.status == "planned"

    etf_redemption = get_dataset_spec("insight", "etf_redemption")
    assert etf_redemption.status == "planned"


def test_get_dataset_spec_rejects_unknown_dataset() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        get_dataset_spec("insight", "missing")
