from __future__ import annotations

import pytest

from getrich_data_import.catalog import dataset_specs_for_provider, get_dataset_spec


def test_insight_catalog_includes_parquet_staging_and_ready_bars() -> None:
    specs = dataset_specs_for_provider("insight")
    names = {spec.name for spec in specs}

    assert "parquet_staging" in names
    assert "stock_bar_1d" in names
    assert "stock_adj_factor" in names

    staging = get_dataset_spec("insight", "parquet-staging")
    assert staging.storage == "parquet_staging"
    assert staging.target == "staging.parquet_file"

    stock_bar = get_dataset_spec("insight", "stock_bar_1d")
    assert stock_bar.status == "ready"
    assert stock_bar.target == "market.stock_bar_1d"


def test_get_dataset_spec_rejects_unknown_dataset() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        get_dataset_spec("insight", "missing")
