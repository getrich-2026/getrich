from __future__ import annotations

import pandas as pd


ASSET_TABLE = {
    ("index", "1d"): "index_bar_1d",
    ("future", "1d"): "future_bar_1d",
    ("option", "1d"): "option_bar_1d",
    ("stock", "1d"): "stock_bar_1d",
    ("etf", "1d"): "etf_bar_1d",
    ("index", "1m"): "index_bar_1m",
    ("future", "1m"): "future_bar_1m",
    ("option", "1m"): "option_bar_1m",
    ("stock", "1m"): "stock_bar_1m",
    ("etf", "1m"): "etf_bar_1m",
}


def market_table(asset: str, freq: str) -> str:
    try:
        return ASSET_TABLE[(asset, freq)]
    except KeyError as exc:
        raise ValueError(f"unsupported market table for asset={asset!r}, freq={freq!r}") from exc


def to_market_frame(df: pd.DataFrame, *, freq: str) -> pd.DataFrame:
    base_cols = [
        "instrument_id",
        "dt",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "pre_settle",
        "limit_up",
        "limit_down",
        "trading_status",
        "source",
    ]
    out = df.copy()
    for col in ["open_interest", "settle", "pre_settle", "volume", "amount"]:
        if col not in out.columns:
            out[col] = None
    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "pre_settle",
        "limit_up",
        "limit_down",
        "adj_factor",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if freq == "1d":
        if "adj_factor" in out.columns and out["adj_factor"].notna().any():
            out["adj_factor"] = out["adj_factor"].fillna(1.0)
            base_cols.append("adj_factor")
    return out.loc[:, [col for col in base_cols if col in out.columns]]
