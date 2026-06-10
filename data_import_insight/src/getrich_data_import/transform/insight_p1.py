from __future__ import annotations

import json

import pandas as pd


P1_CANONICAL_DATASETS: tuple[str, ...] = (
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


def normalize_insight_p1_dataset(
    dataset_name: str, raw: pd.DataFrame, *, source: str
) -> pd.DataFrame:
    """Normalize one raw INSIGHT P1 dataset into canonical load columns.

    Args:
        dataset_name: P1 dataset name.
        raw: Raw SDK DataFrame read from staged Parquet.
        source: Provider name stored in canonical tables.

    Raises:
        ValueError: If the dataset is unsupported or required source columns are missing.

    Time Complexity:
        O(n * c), where n is row count and c is source column count.
    Space Complexity:
        O(n * c), for the normalized output and raw payload JSON.
    """

    if raw.empty:
        return pd.DataFrame()
    if dataset_name == "stock_adj_factor":
        return _normalize_stock_adj_factor(raw, source=source)
    if dataset_name == "stock_daily_basic":
        return _normalize_stock_daily_basic(raw, source=source)
    if dataset_name == "stock_valuation":
        return _normalize_stock_valuation(raw, source=source)
    if dataset_name == "index_component":
        return _normalize_index_component(raw, source=source)
    if dataset_name in {"etf_daily", "fund_daily"}:
        return _normalize_fund_family_daily(
            raw, dataset_name=dataset_name, source=source
        )
    if dataset_name in {"etf_nav", "fund_nav"}:
        return _normalize_fund_family_nav(raw, dataset_name=dataset_name, source=source)
    if dataset_name == "etf_basket":
        return _normalize_etf_basket(raw, source=source)
    raise ValueError(f"unsupported INSIGHT P1 canonical dataset: {dataset_name}")


def _normalize_stock_adj_factor(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    _require_columns(raw, "stock_adj_factor", ("htsc_code", "begin_date"))
    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = _text(raw, "htsc_code")
    out["begin_date"] = _date(raw, "begin_date")
    _copy_numeric(
        raw,
        out,
        {
            "xdy": "xdy",
            "b_xdy": "b_xdy",
            "f_xdy": "f_xdy",
        },
    )
    return _finish(
        out,
        raw,
        source=source,
        required=("source_symbol", "begin_date", "xdy", "b_xdy", "f_xdy"),
    )


def _normalize_stock_daily_basic(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    _require_columns(raw, "stock_daily_basic", ("htsc_code", "trading_day"))
    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = _text(raw, "htsc_code")
    out["trading_day"] = _date(raw, "trading_day")
    out["trading_state"] = _text(raw, "trading_state")
    _copy_numeric(
        raw,
        out,
        {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "prev_close": "pre_close",
            "backward_adjusted_closing_price": "backward_adjusted_closing_price",
            "volume": "volume",
            "value": "amount",
            "day_change": "day_change",
            "turnover_rate": "turnover_rate",
            "amplitude": "amplitude",
            "avg_price": "avg_price",
            "avg_vol_per_deal": "avg_volume_per_trade",
            "avg_value_per_deal": "avg_amount_per_trade",
            "floating_market_val": "float_market_cap",
            "total_market_val": "total_market_cap",
            "turnover_deals": "num_trades",
        },
    )
    return _finish(out, raw, source=source, required=("source_symbol", "trading_day"))


def _normalize_stock_valuation(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    _require_columns(raw, "stock_valuation", ("htsc_code", "trading_day"))
    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = _text(raw, "htsc_code")
    out["trading_day"] = _date(raw, "trading_day")
    _copy_numeric(
        raw,
        out,
        {
            "close": "close",
            "forward_adjusted_closing_price": "front_adjusted_close",
            "backward_adjusted_closing_price": "back_adjusted_close",
            "pe": "pe",
            "pettm": "pe_ttm",
            "pb": "pb",
            "pc": "pc",
            "pcttm": "pc_ttm",
            "ps": "ps",
            "psttm": "ps_ttm",
            "avg_price": "avg_price",
            "avg_vol_per_deal": "avg_volume_per_trade",
            "avg_value_per_deal": "avg_amount_per_trade",
            "floating_market_val": "float_market_cap",
            "total_market_val": "total_market_cap",
        },
    )
    return _finish(out, raw, source=source, required=("source_symbol", "trading_day"))


def _normalize_index_component(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    _require_columns(raw, "index_component", ("htsc_code", "stock_code", "trading_day"))
    out = pd.DataFrame(index=raw.index)
    out["index_source_symbol"] = _text(raw, "htsc_code")
    out["component_source_symbol"] = _text(raw, "stock_code")
    out["trading_day"] = _date(raw, "trading_day")
    out["weight"] = _number(raw, "weight")
    out["in_date"] = _optional_date(raw, "in_date")
    out["out_date"] = _optional_date(raw, "out_date")
    return _finish(
        out,
        raw,
        source=source,
        required=("index_source_symbol", "component_source_symbol", "trading_day"),
    )


def _normalize_fund_family_daily(
    raw: pd.DataFrame, *, dataset_name: str, source: str
) -> pd.DataFrame:
    _require_columns(raw, dataset_name, ("htsc_code", "trading_day"))
    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = _text(raw, "htsc_code")
    out["trading_day"] = _date(raw, "trading_day")
    out["delisting_date"] = _optional_date(raw, "delisting_date")
    out["trading_state"] = _text(raw, "trading_state")
    _copy_numeric(
        raw,
        out,
        {
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "prev_close": "pre_close",
            "backward_adjusted_closing_price": "backward_adjusted_close",
            "unit_nav": "unit_nav",
            "discount_rate": "discount_rate",
            "discount": "discount",
            "discount_ratio": "discount_ratio",
            "day_change": "day_change",
            "day_change_rate": "day_change_rate",
            "turnover_rate": "turnover_rate",
            "amplitude": "amplitude",
            "volume": "volume",
            "value": "amount",
            "turnover_deals": "num_trades",
        },
    )
    return _finish(out, raw, source=source, required=("source_symbol", "trading_day"))


def _normalize_fund_family_nav(
    raw: pd.DataFrame, *, dataset_name: str, source: str
) -> pd.DataFrame:
    _require_columns(raw, dataset_name, ("htsc_code", "end_date"))
    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = _text(raw, "htsc_code")
    out["end_date"] = _date(raw, "end_date")
    _copy_numeric(
        raw,
        out,
        {
            "net_unit": "unit_nav",
            "total_net_unit": "accumulated_nav",
            "post_net_unit": "adjusted_nav",
            "d1_navgr": "return_1d",
            "w1_navg": "return_1w",
            "w1_navgr": "return_1w_rank",
            "w4_navg": "return_1m",
            "w4_navgr": "return_1m_rank",
            "w13_navg": "return_3m",
            "w13_navgr": "return_3m_rank",
            "w26_navg": "return_6m",
            "w26_navgr": "return_6m_rank",
            "w52_navg": "return_1y",
            "w52_navgr": "return_1y_rank",
            "ytdn_avg": "return_ytd",
            "ytdn_avgr": "return_ytd_rank",
            "y3_navg": "return_3y",
            "y5_navg": "return_5y",
            "sl_navg": "return_since_listing",
            "navg_vol": "nav_volatility",
            "beta": "beta",
            "sharper": "sharpe",
            "jensenid": "jensen",
            "treynorid": "treynor",
            "r2": "r_squared",
        },
    )
    return _finish(out, raw, source=source, required=("source_symbol", "end_date"))


def _normalize_etf_basket(raw: pd.DataFrame, *, source: str) -> pd.DataFrame:
    _require_columns(raw, "etf_basket", ("htsc_code", "stock_code", "trading_day"))
    out = pd.DataFrame(index=raw.index)
    out["etf_source_symbol"] = _text(raw, "htsc_code")
    out["component_symbol"] = _text(raw, "stock_code")
    out["trading_day"] = _date(raw, "trading_day")
    out["pub_date"] = _optional_date(raw, "pub_date")
    out["sub_component_list"] = _text(raw, "sub_comp_list")
    out["component_type"] = _text(raw, "c_type")
    out["unit"] = _text(raw, "unit")
    out["cash_substitute_flag"] = _text(raw, "is_cash_substitute")
    _copy_numeric(
        raw,
        out,
        {
            "component_num": "quantity",
            "cash_substitute_rate": "cash_substitute_rate",
            "cash_substitute": "cash_substitute_amount",
            "sub_replace": "subscription_substitute_amount",
            "red_replace": "redemption_substitute_amount",
        },
    )
    return _finish(
        out,
        raw,
        source=source,
        required=("etf_source_symbol", "component_symbol", "trading_day"),
    )


def _require_columns(
    raw: pd.DataFrame, dataset_name: str, columns: tuple[str, ...]
) -> None:
    missing = [column for column in columns if column not in raw.columns]
    if missing:
        raise ValueError(f"{dataset_name}: missing required raw columns: {missing}")


def _copy_numeric(
    raw: pd.DataFrame, out: pd.DataFrame, mapping: dict[str, str]
) -> None:
    for source_col, target_col in mapping.items():
        out[target_col] = _number(raw, source_col)


def _number(raw: pd.DataFrame, column: str) -> pd.Series:
    if column not in raw.columns:
        return pd.Series(None, index=raw.index, dtype="object")
    return pd.to_numeric(raw[column], errors="coerce")


def _text(raw: pd.DataFrame, column: str) -> pd.Series:
    if column not in raw.columns:
        return pd.Series(None, index=raw.index, dtype="object")
    return raw[column].where(pd.notna(raw[column]), None).astype("string")


def _date(raw: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_datetime(raw[column], errors="coerce").dt.date


def _optional_date(raw: pd.DataFrame, column: str) -> pd.Series:
    if column not in raw.columns:
        return pd.Series(None, index=raw.index, dtype="object")
    return _date(raw, column)


def _raw_payload(raw: pd.DataFrame) -> pd.Series:
    records: list[str] = []
    for row in raw.where(pd.notna(raw), None).to_dict(orient="records"):
        records.append(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str))
    return pd.Series(records, index=raw.index, dtype="object")


def _finish(
    out: pd.DataFrame,
    raw: pd.DataFrame,
    *,
    source: str,
    required: tuple[str, ...],
) -> pd.DataFrame:
    out["source"] = source
    out["raw_payload"] = _raw_payload(raw)
    mask = pd.Series(True, index=out.index)
    for column in required:
        values = out[column]
        mask &= values.notna() & (values.astype(str).str.strip() != "")
    normalized = out.loc[mask].copy()
    return normalized.where(pd.notna(normalized), None)
