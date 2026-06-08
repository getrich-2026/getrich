from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from datetime import time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from getrich_data_import.adapters.insight import InsightSource
from getrich_data_import.staging import StagedParquetFile
from getrich_data_import.staging import write_staging_parquet


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
P1_SAMPLE_DATASETS: tuple[str, ...] = (
    "stock_adj_factor",
    "stock_daily_basic",
    "stock_valuation",
    "index_component",
    "etf_daily",
    "etf_nav",
    "fund_daily",
    "fund_nav",
    "etf_basket",
    "etf_redemption",
)
P1_DEFAULT_SAMPLE_DATASETS: tuple[str, ...] = (
    "stock_adj_factor",
    "stock_daily_basic",
    "stock_valuation",
    "index_component",
    "etf_daily",
    "etf_nav",
    "fund_daily",
    "fund_nav",
    "etf_basket",
    "etf_redemption",
)
P1_READY_DATASETS: tuple[str, ...] = (
    "stock_adj_factor",
    "stock_daily_basic",
    "stock_valuation",
    "index_component",
    "etf_daily",
    "etf_nav",
    "fund_daily",
    "fund_nav",
    "etf_basket",
)


@dataclass(frozen=True)
class InsightP1Sample:
    """Result for one exported INSIGHT P1 raw sample.

    Attributes:
        dataset_name: Registered P1 dataset name.
        symbol: Source symbol used for the request.
        rows: Number of rows returned by the SDK.
        columns: Raw SDK columns in returned order.
        staged_file: Written Parquet metadata, or None when the SDK returned no rows.
        error: Provider error text when the sample request failed.

    Time Complexity:
        O(1) for construction and field access.
    Space Complexity:
        O(c), where c is the number of column names.
    """

    dataset_name: str
    symbol: str
    rows: int
    columns: tuple[str, ...]
    staged_file: StagedParquetFile | None = None
    error: str | None = None


def export_insight_p1_samples(
    source: InsightSource,
    *,
    root_dir: Path,
    start_date: date,
    end_date: date,
    stock_symbol: str,
    index_symbol: str,
    fund_symbol: str,
    etf_symbol: str,
    dataset_names: tuple[str, ...] = P1_DEFAULT_SAMPLE_DATASETS,
) -> tuple[InsightP1Sample, ...]:
    """Export raw INSIGHT P1 sample datasets to local Parquet.

    Args:
        source: Logged-in INSIGHT source wrapper.
        root_dir: Local Parquet staging root for raw samples.
        start_date: Inclusive sample start date.
        end_date: Inclusive sample end date.
        stock_symbol: Source stock symbol for stock datasets.
        index_symbol: Source index symbol for index component samples.
        fund_symbol: Source ordinary fund symbol for fund datasets.
        etf_symbol: Source ETF symbol for ETF datasets.
        dataset_names: Dataset names to request.

    Time Complexity:
        O(d * (r * c)), where d is dataset count, r is rows returned per dataset,
        and c is returned column count.
    Space Complexity:
        O(r * c), bounded by the largest returned SDK frame held at once.
    """

    query_api = _load_p1_query_api(source)
    output: list[InsightP1Sample] = []
    for dataset_name in dataset_names:
        if dataset_name not in P1_SAMPLE_DATASETS:
            raise ValueError(f"unsupported insight P1 sample dataset: {dataset_name}")
        symbol = _symbol_for_dataset(
            dataset_name,
            stock_symbol=stock_symbol,
            index_symbol=index_symbol,
            fund_symbol=fund_symbol,
            etf_symbol=etf_symbol,
        )
        try:
            frame = fetch_insight_p1_raw_frame(
                source,
                dataset_name=dataset_name,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                query_api=query_api,
            )
        except Exception as exc:
            output.append(
                InsightP1Sample(
                    dataset_name=dataset_name,
                    symbol=symbol,
                    rows=0,
                    columns=(),
                    error=str(exc),
                )
            )
            continue

        if frame.empty:
            output.append(
                InsightP1Sample(
                    dataset_name=dataset_name,
                    symbol=symbol,
                    rows=0,
                    columns=tuple(map(str, frame.columns)),
                )
            )
            continue

        staged = write_staging_parquet(
            frame,
            root_dir=root_dir,
            provider=source.provider,
            dataset_name=dataset_name,
            asset=_asset_for_dataset(dataset_name),
            freq="sample",
            start_date=start_date,
            end_date=end_date,
            partition_key=symbol,
        )
        output.append(
            InsightP1Sample(
                dataset_name=dataset_name,
                symbol=symbol,
                rows=int(frame.shape[0]),
                columns=tuple(map(str, frame.columns)),
                staged_file=staged,
            )
        )
    return tuple(output)


def insight_exchange_code(symbol: str) -> int | None:
    """Return INSIGHT exchange code for ETF redemption queries.

    Args:
        symbol: INSIGHT-style symbol such as ``510300.SH`` or ``159919.SZ``.

    Time Complexity:
        O(1).
    Space Complexity:
        O(1).
    """

    suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
    if suffix in {"SH", "XSHG"}:
        return 101
    if suffix in {"SZ", "XSHE"}:
        return 105
    return None


def fetch_insight_p1_raw_frame(
    source: InsightSource,
    *,
    dataset_name: str,
    symbol: str,
    start_date: date,
    end_date: date,
    query_api: dict[str, Callable[..., object]] | None = None,
) -> pd.DataFrame:
    """Fetch one raw INSIGHT P1 dataset for one source symbol.

    Args:
        source: INSIGHT source wrapper.
        dataset_name: P1 dataset name.
        symbol: INSIGHT source symbol.
        start_date: Inclusive start date.
        end_date: Inclusive end date.
        query_api: Optional already-loaded SDK function mapping.

    Time Complexity:
        O(r * c), where r is returned row count and c is returned column count.
    Space Complexity:
        O(r * c), for the returned SDK frame.
    """

    api = query_api or _load_p1_query_api(source)
    return _fetch_raw_dataset(
        api,
        dataset_name=dataset_name,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )


def _load_p1_query_api(source: InsightSource) -> dict[str, Callable[..., object]]:
    source._load_api()
    from insight_python.com.insight.query import (  # type: ignore[import-not-found]
        get_adj_factor,
        get_daily_basic,
        get_etf_component,
        get_etf_redemption,
        get_fund_info,
        get_fund_target,
        get_index_component,
        get_stock_valuation,
    )

    return {
        "stock_adj_factor": get_adj_factor,
        "stock_daily_basic": get_daily_basic,
        "stock_valuation": get_stock_valuation,
        "index_component": get_index_component,
        "etf_daily": get_fund_info,
        "etf_nav": get_fund_target,
        "fund_daily": get_fund_info,
        "fund_nav": get_fund_target,
        "etf_basket": get_etf_component,
        "etf_redemption": get_etf_redemption,
    }


def _fetch_raw_dataset(
    query_api: dict[str, Callable[..., object]],
    *,
    dataset_name: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    start_ts = _sample_datetime(start_date)
    end_ts = _sample_datetime(end_date)
    date_range = [start_ts, end_ts]
    func = query_api[dataset_name]

    if dataset_name == "stock_adj_factor":
        raw = func(htsc_code=symbol, begin_date=date_range)
    elif dataset_name in {
        "stock_daily_basic",
        "stock_valuation",
        "etf_daily",
        "fund_daily",
    }:
        raw = func(htsc_code=symbol, trading_day=date_range)
    elif dataset_name == "index_component":
        raw = func(htsc_code=symbol, trading_day=start_ts)
    elif dataset_name in {"etf_nav", "fund_nav"}:
        raw = func(htsc_code=symbol, exchange=None, end_date=date_range)
    elif dataset_name == "etf_basket":
        raw = func(htsc_code=symbol, pub_date=None, trading_day=date_range)
    elif dataset_name == "etf_redemption":
        raw = func(
            htsc_code=symbol,
            exchange=insight_exchange_code(symbol),
            trading_day=date_range,
        )
    else:
        raise ValueError(f"unsupported insight P1 sample dataset: {dataset_name}")

    if isinstance(raw, pd.DataFrame):
        return raw.where(pd.notna(raw), None)
    if raw is None:
        return pd.DataFrame()
    if isinstance(raw, str):
        raise RuntimeError(raw)
    raise RuntimeError(f"unexpected INSIGHT result type: {type(raw).__name__}")


def _sample_datetime(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=SHANGHAI_TZ)


def _symbol_for_dataset(
    dataset_name: str,
    *,
    stock_symbol: str,
    index_symbol: str,
    fund_symbol: str,
    etf_symbol: str,
) -> str:
    if dataset_name.startswith("stock_"):
        return stock_symbol
    if dataset_name == "index_component":
        return index_symbol
    if dataset_name.startswith("fund_"):
        return fund_symbol
    return etf_symbol


def _asset_for_dataset(dataset_name: str) -> str:
    if dataset_name.startswith("stock_"):
        return "stock"
    if dataset_name.startswith("index_"):
        return "index"
    if dataset_name.startswith("fund_"):
        return "fund"
    return "etf"
