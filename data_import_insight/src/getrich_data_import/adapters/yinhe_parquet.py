from __future__ import annotations

from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Hashable, Iterable

import pandas as pd
import pyarrow.parquet as pq

from getrich_data_import.adapters.base import SourceCoverage, require_dir
from getrich_data_import.common.time import int_yyyymmdd_to_date, to_date_series, to_shanghai_timestamp_series


SECURITY_TYPE_ASSET = {
    # AmazingData has emitted both IDNEX and INDEX spellings for the same index universe.
    "EXTRA_IDNEX_A_SH_SZ": "index",
    "EXTRA_INDEX_A_SH_SZ": "index",
    "EXTRA_FUTURE_CFFEX": "future",
    "EXTRA_OPTION_CFFEX": "option",
    "EXTRA_STOCK_A_SH_SZ": "stock",
    "EXTRA_ETF": "etf",
}

SECURITY_TYPE_EXCHANGE = {
    "EXTRA_IDNEX_A_SH_SZ": "CN",
    "EXTRA_INDEX_A_SH_SZ": "CN",
    "EXTRA_FUTURE_CFFEX": "CFFEX",
    "EXTRA_OPTION_CFFEX": "CFFEX",
}

A_SHARE_CALENDAR_ALIASES = {
    "SH": ("SZ",),
    "SZ": ("SH",),
}


class YinheParquetSource:
    name = "yinhe"

    def __init__(self, data_dir: Path, provider: str = "yinhe") -> None:
        self.data_dir = require_dir(data_dir)
        self.provider = provider
        self._factor_cache: dict[str, pd.Series] = {}

    def scan(self) -> SourceCoverage:
        instruments = {
            security_type: len(self._hist_codes(security_type))
            for security_type in SECURITY_TYPE_ASSET
        }
        return SourceCoverage(
            calendar_files=len(self._calendar_paths()),
            instruments=instruments,
            kline_day_files=len(self._kline_paths("1d")),
            kline_min1_files=len(self._kline_paths("1m")),
        )

    def calendar_frames(self) -> Iterable[pd.DataFrame]:
        available_exchanges = {path.stem.replace("calendar_", "", 1) for path in self._calendar_paths()}
        for path in self._calendar_paths():
            exchange = path.stem.replace("calendar_", "", 1)
            raw = pd.read_parquet(path)
            dates = raw.index.to_series().map(int_yyyymmdd_to_date).sort_values()
            if dates.empty:
                continue
            for output_exchange in self._calendar_output_exchanges(exchange, available_exchanges):
                df = pd.DataFrame(
                    {
                        "exchange": output_exchange,
                        "trading_day": dates.values,
                        "is_open": True,
                        "has_night": False,
                        "prev_trading_day": dates.shift(1).values,
                        "next_trading_day": dates.shift(-1).values,
                    }
                )
                yield df.where(pd.notna(df), None)

    def instrument_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for security_type, asset in SECURITY_TYPE_ASSET.items():
            for symbol in self._hist_codes(security_type):
                rows.append(
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "exchange": self._exchange_for_symbol(symbol, security_type),
                        "name": None,
                        "status": "active",
                    }
                )
        columns = ["symbol", "asset", "exchange", "name", "status"]
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns).drop_duplicates(["asset", "exchange", "symbol"])

    def symbol_map_frame(self) -> pd.DataFrame:
        instruments = self.instrument_frame()
        if instruments.empty:
            return pd.DataFrame(columns=["asset", "exchange", "symbol", "source", "source_symbol"])
        out = instruments.loc[:, ["asset", "exchange", "symbol"]].copy()
        out["source"] = self.provider
        out["source_symbol"] = out["symbol"]
        return out

    def future_contract_frame(self) -> pd.DataFrame:
        return self._future_contracts_from_hist_code_list("EXTRA_FUTURE_CFFEX")

    def option_contract_frame(self) -> pd.DataFrame:
        return self._option_contracts_from_hist_code_list("EXTRA_OPTION_CFFEX")

    def bar_frames(
        self,
        *,
        asset: str,
        freq: str,
        since: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> Iterable[pd.DataFrame]:
        symbol_filter = set(symbols or [])
        for path in self._kline_paths(freq, symbols=symbol_filter):
            raw = pd.read_parquet(path)
            if raw.empty:
                continue
            df = self._normalize_bar_frame(path, raw, freq=freq)
            df["asset"] = df["source_symbol"].map(self.asset_by_symbol).fillna("")
            df = df[df["asset"] == asset]
            if symbol_filter:
                df = df[df["source_symbol"].isin(symbol_filter)]
            if since is not None:
                df = df[df["trading_day"] > since]
            if start_date is not None:
                df = df[df["trading_day"] >= start_date]
            if end_date is not None:
                df = df[df["trading_day"] <= end_date]
            if not df.empty:
                yield df

    def _calendar_paths(self) -> list[Path]:
        return sorted((self.data_dir / "calendar").glob("calendar_*.parquet"))

    def _calendar_output_exchanges(self, exchange: str, available_exchanges: set[str]) -> tuple[str, ...]:
        aliases = tuple(
            alias
            for alias in A_SHARE_CALENDAR_ALIASES.get(exchange, ())
            if alias not in available_exchanges
        )
        return (exchange, *aliases)

    def _hist_path(self, security_type: str) -> Path:
        return self.data_dir / "hist_code_list" / f"hist_code_list_{security_type}.parquet"

    def _hist_codes(self, security_type: str) -> list[str]:
        path = self._hist_path(security_type)
        if not path.exists():
            return []
        raw = pd.read_parquet(path)
        if raw.empty:
            return []
        return sorted(set(raw.iloc[:, 0].dropna().astype(str).tolist()))

    def _hist_frame(self, security_type: str) -> pd.DataFrame:
        path = self._hist_path(security_type)
        if not path.exists():
            return pd.DataFrame()
        raw = pd.read_parquet(path)
        if raw.empty:
            return pd.DataFrame()
        return raw

    def _future_contracts_from_hist_code_list(self, security_type: str) -> pd.DataFrame:
        raw = self._hist_frame(security_type)
        columns = [
            "asset",
            "exchange",
            "symbol",
            "underlying",
            "multiplier",
            "price_tick",
            "list_date",
            "last_trade_date",
            "delivery_date",
        ]
        if raw.empty:
            return pd.DataFrame(columns=columns)
        symbol_col = _first_existing(raw, ["symbol", "code", "htsc_code", 0])
        if symbol_col is None:
            return pd.DataFrame(columns=columns)
        out = pd.DataFrame(index=raw.index)
        out["asset"] = "future"
        out["symbol"] = raw[symbol_col].astype(str)
        out["exchange"] = out["symbol"].map(lambda symbol: self._exchange_for_symbol(symbol, security_type))
        out["underlying"] = _optional_string(raw, ["underlying", "underlying_symbol", "product"])
        out["multiplier"] = _optional_numeric(raw, ["multiplier", "contract_multiplier"])
        out["price_tick"] = _optional_numeric(raw, ["price_tick", "min_price_change", "tick_size"])
        out["list_date"] = _optional_date(raw, ["list_date", "listed_date"])
        out["last_trade_date"] = _optional_date(raw, ["last_trade_date", "last_trading_date"])
        out["delivery_date"] = _optional_date(raw, ["delivery_date"])
        return out.dropna(subset=["symbol", "exchange"])

    def _option_contracts_from_hist_code_list(self, security_type: str) -> pd.DataFrame:
        raw = self._hist_frame(security_type)
        columns = [
            "asset",
            "exchange",
            "symbol",
            "underlying_symbol",
            "option_type",
            "exercise_style",
            "strike",
            "multiplier",
            "list_date",
            "last_trade_date",
            "exercise_date",
        ]
        if raw.empty:
            return pd.DataFrame(columns=columns)
        symbol_col = _first_existing(raw, ["symbol", "code", "htsc_code", 0])
        if symbol_col is None:
            return pd.DataFrame(columns=columns)
        out = pd.DataFrame(index=raw.index)
        out["asset"] = "option"
        out["symbol"] = raw[symbol_col].astype(str)
        out["exchange"] = out["symbol"].map(lambda symbol: self._exchange_for_symbol(symbol, security_type))
        out["underlying_symbol"] = _optional_string(raw, ["underlying", "underlying_symbol"])
        out["option_type"] = _normalize_option_type(_optional_string(raw, ["option_type", "call_put", "cp"]))
        out["exercise_style"] = _optional_string(raw, ["exercise_style"])
        out["strike"] = _optional_numeric(raw, ["strike", "strike_price", "exercise_price"])
        out["multiplier"] = _optional_numeric(raw, ["multiplier", "contract_multiplier"])
        out["list_date"] = _optional_date(raw, ["list_date", "listed_date"])
        out["last_trade_date"] = _optional_date(raw, ["last_trade_date", "last_trading_date"])
        out["exercise_date"] = _optional_date(raw, ["exercise_date"])
        out = out.dropna(subset=["symbol", "exchange", "option_type", "strike"])
        return out

    def _kline_paths(self, freq: str, symbols: set[str] | None = None) -> list[Path]:
        if freq == "1d":
            root = self.data_dir / "kline_day"
        elif freq == "1m":
            root = self.data_dir / "kline_min1"
        else:
            raise ValueError(f"unsupported freq: {freq}")
        if not root.exists():
            return []
        if symbols:
            paths: list[Path] = []
            for symbol in sorted(symbols):
                flat = root / f"{symbol}.parquet"
                if flat.exists():
                    paths.append(flat)
                partition = root / symbol
                if partition.exists():
                    paths.extend(sorted(partition.glob("*.parquet")))
            return paths
        flat = sorted(root.glob("*.parquet"))
        partitioned = sorted(root.glob("*/*.parquet"))
        return flat + partitioned

    def _normalize_bar_frame(self, path: Path, raw: pd.DataFrame, *, freq: str) -> pd.DataFrame:
        df = raw.copy()
        source_symbol = self._symbol_from_path(path)
        if "code" in df.columns and df["code"].notna().any():
            source_symbol = str(df["code"].dropna().iloc[0])
        if "kline_time" not in df.columns:
            df["kline_time"] = df.index

        out = pd.DataFrame(index=df.index)
        out["source_symbol"] = source_symbol
        if freq == "1d":
            out["trading_day"] = to_date_series(df["kline_time"])
            out["dt"] = out["trading_day"]
        else:
            out["dt"] = to_shanghai_timestamp_series(df["kline_time"])
            out["trading_day"] = out["dt"].dt.date

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "open_interest",
            "settle",
            "pre_close",
            "pre_settle",
            "limit_up",
            "limit_down",
        ]:
            out[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else None
        if "trading_status" in df.columns:
            out["trading_status"] = df["trading_status"].astype("string")
        elif "status" in df.columns:
            out["trading_status"] = df["status"].astype("string")
        else:
            out["trading_status"] = None
        if "adj_factor" in df.columns:
            out["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")
        elif freq == "1d":
            factor = self.factor_series(source_symbol)
            if factor is None:
                out["adj_factor"] = None
            else:
                out = out.join(factor, on="trading_day")
        else:
            out["adj_factor"] = None
        out["source"] = self.provider
        return out.dropna(subset=["dt", "trading_day", "source_symbol"])

    @cached_property
    def asset_by_symbol(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for security_type, asset in SECURITY_TYPE_ASSET.items():
            for symbol in self._hist_codes(security_type):
                mapping.setdefault(symbol, asset)
        return mapping

    def _exchange_for_symbol(self, symbol: str, security_type: str) -> str:
        if "." in symbol:
            return symbol.rsplit(".", 1)[-1].upper()
        return SECURITY_TYPE_EXCHANGE.get(security_type, "")

    def _symbol_from_path(self, path: Path) -> str:
        if path.parent.name in {"kline_day", "kline_min1"}:
            return path.stem
        return path.parent.name

    def factor_series(self, symbol: str) -> pd.Series | None:
        if symbol in self._factor_cache:
            return self._factor_cache[symbol]
        path = self.factor_path_by_symbol.get(symbol)
        if path is None:
            return None
        series = pd.read_parquet(path, columns=[symbol])[symbol]
        series.index = pd.to_datetime(series.index).date
        series = pd.to_numeric(series, errors="coerce")
        series.name = "adj_factor"
        self._factor_cache[symbol] = series
        return series

    @cached_property
    def factor_path_by_symbol(self) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for path in sorted((self.data_dir / "backward_factor").glob("*.parquet")):
            schema = pq.ParquetFile(path).schema_arrow
            for name in schema.names:
                paths.setdefault(str(name), path)
        return paths


def _first_existing(df: pd.DataFrame, names: list[Hashable]) -> Hashable | None:
    return next((name for name in names if name in df.columns), None)


def _optional_string(df: pd.DataFrame, names: list[Hashable]) -> object:
    col = _first_existing(df, names)
    if col is None:
        return None
    return df[col].astype("string")


def _optional_numeric(df: pd.DataFrame, names: list[Hashable]) -> object:
    col = _first_existing(df, names)
    if col is None:
        return None
    return pd.to_numeric(df[col], errors="coerce")


def _optional_date(df: pd.DataFrame, names: list[Hashable]) -> object:
    col = _first_existing(df, names)
    if col is None:
        return None
    return pd.to_datetime(df[col], errors="coerce").dt.date


def _normalize_option_type(values: object) -> object:
    if values is None:
        return None
    series = pd.Series(values, copy=False).astype("string").str.upper().str.strip()
    return series.replace({"CALL": "C", "PUT": "P", "认购": "C", "认沽": "P"})
