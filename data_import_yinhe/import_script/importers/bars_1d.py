from __future__ import annotations

import numpy as np
import pandas as pd

from ..importer import BaseImporter, ImportContext, ResolvedMode
from ..utils import to_date_series


class Bars1dImporter(BaseImporter):
    name = "bars_1d"
    target_table = "md.bars_1d"
    primary_keys = ("symbol", "dt")
    watermark_column = "dt"

    def stream_frames(self, ctx: ImportContext, mode: ResolvedMode, since: object | None):
        for path in ctx.store.kline_day_paths():
            raw = pd.read_parquet(path)
            if raw.empty:
                continue

            df = raw.copy()
            if "code" not in df.columns:
                df["code"] = path.stem
            if "kline_time" not in df.columns:
                df["kline_time"] = df.index

            symbol = str(df["code"].dropna().iloc[0]) if df["code"].notna().any() else path.stem
            df["dt"] = to_date_series(df["kline_time"])
            df = df.dropna(subset=["dt"]).sort_values("dt")
            df["pre_close"] = pd.to_numeric(df.get("close", 0), errors="coerce").shift(1)
            if mode == "incremental" and since is not None:
                df = df[df["dt"] > since]
            if df.empty:
                continue

            out = pd.DataFrame()
            out["dt"] = df["dt"]
            out["symbol"] = symbol
            out["raw_symbol"] = symbol
            out["type"] = ctx.store.instrument_types.get(symbol, "")
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                out[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)

            out["pre_close"] = pd.to_numeric(df["pre_close"], errors="coerce").fillna(0)
            valid_pre_close = out["pre_close"] > 0
            out["pct_chg"] = np.where(
                valid_pre_close, out["close"] / out["pre_close"] - 1.0, 0.0
            )
            out["pct_chg_log"] = np.where(
                valid_pre_close & (out["close"] > 0),
                np.log(out["close"] / out["pre_close"]),
                0.0,
            )
            out["amplitude"] = np.where(
                valid_pre_close, (out["high"] - out["low"]) / out["pre_close"], 0.0
            )

            factor = ctx.store.factor_series(symbol)
            if factor is None:
                out["adj_factor"] = 1.0
            else:
                out = out.join(factor, on="dt")
                out["adj_factor"] = out["adj_factor"].fillna(1.0)

            out["limit_up"] = 0.0
            out["limit_down"] = 0.0
            out["open_interest"] = 0.0
            out["settle"] = 0.0
            out["pre_settle"] = 0.0
            out["trading_status"] = "NORMAL"
            out["provider"] = ctx.config.provider

            cols = [
                "dt",
                "symbol",
                "raw_symbol",
                "type",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pre_close",
                "pct_chg",
                "pct_chg_log",
                "adj_factor",
                "amplitude",
                "limit_up",
                "limit_down",
                "open_interest",
                "settle",
                "pre_settle",
                "trading_status",
                "provider",
            ]
            yield out.loc[:, cols]
