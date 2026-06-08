from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DatasetStorage = Literal[
    "postgres", "timescale", "parquet_staging", "duckdb_temp", "config"
]
DatasetStatus = Literal["ready", "planned"]


@dataclass(frozen=True)
class DatasetSpec:
    """Declarative import dataset contract.

    Attributes:
        provider: Upstream provider name.
        name: Stable dataset name used by CLI and job audit.
        description: Human-readable dataset purpose.
        source_method: Adapter method or SDK function family.
        storage: Target storage class.
        target: Target table, workspace, or config surface.
        primary_keys: Canonical target primary keys.
        required_columns: Columns that normalized frames must provide.
        optional_columns: Nullable or source-permission-dependent columns.
        asset: Asset class when the dataset is asset-specific.
        freq: Frequency when the dataset is frequency-specific.
        phase: Product roadmap phase.
        status: Whether the dataset is already importable or only planned.
        permission_tier: Required source permission tier.
        supports_incremental: Whether checkpointed incremental imports are expected.

    Time Complexity:
        O(1) for construction and field access.
    Space Complexity:
        O(1), excluding referenced tuple contents.
    """

    provider: str
    name: str
    description: str
    source_method: str
    storage: DatasetStorage
    target: str
    primary_keys: tuple[str, ...]
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    asset: str | None = None
    freq: str | None = None
    phase: str = "P0"
    status: DatasetStatus = "planned"
    permission_tier: str = "standard"
    supports_incremental: bool = True


_INSIGHT_BAR_ASSETS = ("index", "future", "option", "stock", "etf")
_INSIGHT_BAR_FREQS = ("1d", "1m")


def registered_dataset_specs() -> tuple[DatasetSpec, ...]:
    """Return all declarative dataset specs.

    Time Complexity:
        O(n), where n is the number of registered datasets.
    Space Complexity:
        O(n), for the returned tuple.
    """

    return _DATASET_SPECS


def dataset_specs_for_provider(provider: str) -> tuple[DatasetSpec, ...]:
    """Return dataset specs for one provider.

    Args:
        provider: Provider name, case-insensitive. Hyphens and underscores are treated equivalently.

    Time Complexity:
        O(n), where n is the number of registered datasets.
    Space Complexity:
        O(k), where k is the number of matching datasets.
    """

    normalized = _normalize_provider(provider)
    return tuple(
        spec
        for spec in _DATASET_SPECS
        if _normalize_provider(spec.provider) == normalized
    )


def get_dataset_spec(provider: str, name: str) -> DatasetSpec:
    """Return one dataset spec by provider and dataset name.

    Args:
        provider: Provider name.
        name: Dataset name.

    Raises:
        ValueError: If the provider/name pair is not registered.

    Time Complexity:
        O(n), where n is the number of registered datasets.
    Space Complexity:
        O(1).
    """

    normalized_provider = _normalize_provider(provider)
    normalized_name = _normalize_name(name)
    for spec in _DATASET_SPECS:
        if (
            _normalize_provider(spec.provider) == normalized_provider
            and _normalize_name(spec.name) == normalized_name
        ):
            return spec
    raise ValueError(f"unknown dataset for provider={provider!r}: {name!r}")


def _normalize_provider(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _normalize_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _insight_bar_specs() -> tuple[DatasetSpec, ...]:
    specs: list[DatasetSpec] = []
    for asset in _INSIGHT_BAR_ASSETS:
        for freq in _INSIGHT_BAR_FREQS:
            specs.append(
                DatasetSpec(
                    provider="insight",
                    name=f"{asset}_bar_{freq}",
                    description=f"INSIGHT {asset} historical {freq} K-line bars loaded from local Parquet staging.",
                    source_method="InsightSource.bar_frames",
                    storage="timescale",
                    target=f"market.{asset}_bar_{freq}",
                    primary_keys=("instrument_id", "dt"),
                    required_columns=(
                        "source_symbol",
                        "dt",
                        "trading_day",
                        "open",
                        "high",
                        "low",
                        "close",
                        "source",
                    ),
                    optional_columns=(
                        "pre_close",
                        "volume",
                        "amount",
                        "open_interest",
                        "settle",
                        "pre_settle",
                        "limit_up",
                        "limit_down",
                        "trading_status",
                        "adj_factor",
                    ),
                    asset=asset,
                    freq=freq,
                    phase="P0",
                    status="ready",
                    permission_tier="standard",
                )
            )
    return tuple(specs)


_DATASET_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        provider="insight",
        name="parquet_staging",
        description="Local Parquet staging manifest for INSIGHT raw or lightly normalized files.",
        source_method="fetch-to-parquet",
        storage="parquet_staging",
        target="staging.parquet_file",
        primary_keys=("provider", "dataset_name", "source_path"),
        required_columns=("provider", "dataset_name", "source_path", "status"),
        optional_columns=(
            "content_hash",
            "row_count",
            "start_date",
            "end_date",
            "schema_fingerprint",
        ),
        phase="P0",
        status="planned",
        supports_incremental=False,
    ),
    DatasetSpec(
        provider="insight",
        name="metadata",
        description="INSIGHT instruments, symbol map, trading calendars, and empty contract placeholders.",
        source_method="ImportPipeline.load_metadata",
        storage="postgres",
        target="meta.instruments/meta.symbol_map/meta.trading_calendar",
        primary_keys=("asset", "exchange", "symbol"),
        required_columns=("symbol", "asset", "exchange"),
        optional_columns=("name", "list_date", "delist_date", "status"),
        phase="P0",
        status="ready",
        supports_incremental=False,
    ),
    *_insight_bar_specs(),
    DatasetSpec(
        provider="insight",
        name="stock_adj_factor",
        description="Sparse INSIGHT stock adjustment factors xdy, b_xdy, and f_xdy.",
        source_method="get_adj_factor",
        storage="timescale",
        target="market.stock_adj_factor",
        primary_keys=("instrument_id", "begin_date", "source"),
        required_columns=(
            "source_symbol",
            "begin_date",
            "xdy",
            "b_xdy",
            "f_xdy",
            "source",
        ),
        asset="stock",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="stock_daily_basic",
        description="INSIGHT stock daily basic fields including source backward-adjusted close.",
        source_method="get_daily_basic",
        storage="timescale",
        target="market.stock_daily_basic",
        primary_keys=("instrument_id", "trading_day", "source"),
        required_columns=(
            "source_symbol",
            "trading_day",
            "open",
            "high",
            "low",
            "close",
            "source",
        ),
        optional_columns=(
            "backward_adjusted_closing_price",
            "turnover_rate",
            "amplitude",
            "market_cap",
        ),
        asset="stock",
        freq="1d",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="stock_valuation",
        description="INSIGHT stock valuation and front/back adjusted close source fields.",
        source_method="get_stock_valuation",
        storage="timescale",
        target="market.stock_valuation",
        primary_keys=("instrument_id", "trading_day", "source"),
        required_columns=("source_symbol", "trading_day", "close", "source"),
        optional_columns=(
            "front_adjusted_close",
            "back_adjusted_close",
            "pe",
            "pe_ttm",
            "pb",
            "pc",
            "ps",
        ),
        asset="stock",
        freq="1d",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="index_component",
        description="INSIGHT point-in-time index components and weights.",
        source_method="get_index_component",
        storage="timescale",
        target="market.index_component",
        primary_keys=(
            "index_instrument_id",
            "component_instrument_id",
            "trading_day",
            "source",
        ),
        required_columns=(
            "index_symbol",
            "component_symbol",
            "trading_day",
            "weight",
            "source",
        ),
        optional_columns=("in_date", "out_date"),
        asset="index",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="fund_daily",
        description="INSIGHT fund and ETF daily market, NAV, and discount or premium fields.",
        source_method="get_fund_info",
        storage="timescale",
        target="market.fund_daily",
        primary_keys=("instrument_id", "trading_day", "source"),
        required_columns=(
            "source_symbol",
            "trading_day",
            "open",
            "high",
            "low",
            "close",
            "source",
        ),
        optional_columns=(
            "unit_nav",
            "accumulated_nav",
            "discount_rate",
            "premium_rate",
        ),
        asset="etf",
        freq="1d",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="etf_basket",
        description="INSIGHT ETF creation and redemption component basket.",
        source_method="get_etf_component",
        storage="timescale",
        target="market.etf_basket",
        primary_keys=("etf_instrument_id", "component_symbol", "trading_day", "source"),
        required_columns=("etf_symbol", "component_symbol", "trading_day", "source"),
        optional_columns=(
            "pub_date",
            "quantity",
            "cash_substitute_flag",
            "cash_substitute_amount",
        ),
        asset="etf",
        phase="P1",
    ),
    DatasetSpec(
        provider="insight",
        name="adjustment_reconciliation",
        description="Temporary multi-source adjustment comparison output.",
        source_method="validate-adjustments",
        storage="duckdb_temp",
        target="duckdb.adjustment/{run_id}.duckdb",
        primary_keys=("source_symbol", "trading_day", "source_name"),
        required_columns=("source_symbol", "trading_day", "source_name", "close"),
        optional_columns=("difference", "tolerance", "status"),
        asset="stock",
        freq="1d",
        phase="P1",
    ),
)
