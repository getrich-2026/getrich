from __future__ import annotations

import sys
import os
import ctypes
import importlib.util
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from getrich_data_import.adapters.base import SourceCoverage
from getrich_data_import.common.config import InsightSettings
from getrich_data_import.common.logger import get_logger
from getrich_data_import.common.time import to_date_series, to_shanghai_timestamp_series


logger = get_logger(__name__)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


TYPE_EXCHANGE = {
    "index": ["XSHG", "XSHE", "CNI", "CSI"],
    "future": ["CCFX", "XSGE", "XDCE", "XZCE", "XGFE"],
    "option": ["CCFX", "XSGE", "XDCE", "XZCE", "XGFE", "XSHG", "XSHE"],
    "stock": ["XSHG", "XSHE"],
    "etf": ["XSHG", "XSHE"],
}

INSIGHT_FREQUENCY = {
    "1d": "daily",
    "1m": "1min",
}


@dataclass(frozen=True)
class _InsightApi:
    get_all_basic_info: Any
    get_kline: Any
    get_trading_days: Any


class InsightSource:
    name = "insight"

    def __init__(self, settings: InsightSettings, provider: str = "insight") -> None:
        self.settings = settings
        self.provider = provider
        self._api: _InsightApi | None = None

    def scan(self) -> SourceCoverage:
        symbols = len(self.settings.symbols)
        return SourceCoverage(
            calendar_files=0,
            instruments={"configured_symbols": symbols},
            kline_day_files=0,
            kline_min1_files=0,
        )

    def calendar_frames(self) -> Iterable[pd.DataFrame]:
        start_date = self.settings.default_start_date
        end_date = self.settings.default_end_date
        if start_date is None or end_date is None:
            return

        api = self._load_api()
        for exchange in sorted(
            {e for values in TYPE_EXCHANGE.values() for e in values}
        ):
            raw_days = api.get_trading_days(
                exchange=exchange,
                trading_day=[
                    pd.Timestamp.combine(start_date, time.min),
                    pd.Timestamp.combine(end_date, time.min),
                ],
            )
            dates = _trading_days_to_dates(raw_days)
            if not dates:
                continue
            series = pd.Series(sorted(dates))
            df = pd.DataFrame(
                {
                    "exchange": exchange,
                    "trading_day": series.values,
                    "is_open": True,
                    "has_night": exchange in {"CCFX", "XSGE", "XDCE", "XZCE", "XGFE"},
                    "prev_trading_day": series.shift(1).values,
                    "next_trading_day": series.shift(-1).values,
                }
            )
            yield df.where(pd.notna(df), None)

    def instrument_frame(self) -> pd.DataFrame:
        api = self._load_api()
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        for asset, exchanges in TYPE_EXCHANGE.items():
            try:
                raw = api.get_all_basic_info(
                    security_type=asset,
                    today=(asset == "option"),
                    exchange=exchanges,
                )
            except Exception as exc:
                errors.append(f"{asset}: {exc}")
                logger.warning(
                    "insight basic info request failed",
                    extra={"asset": asset, "exchanges": ",".join(exchanges)},
                    exc_info=True,
                )
                continue
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                logger.warning(
                    "insight basic info request returned no rows",
                    extra={"asset": asset, "exchanges": ",".join(exchanges)},
                )
                continue
            frames.append(_normalize_instruments(raw, asset=asset))
        if not frames:
            if errors:
                raise RuntimeError(
                    f"insight basic info failed for all requested assets: {'; '.join(errors)}"
                )
            logger.warning("insight basic info returned no instrument rows")
            return pd.DataFrame(
                columns=["symbol", "asset", "exchange", "name", "status"]
            )
        return pd.concat(frames, ignore_index=True).drop_duplicates(
            ["asset", "exchange", "symbol"]
        )

    def symbol_map_frame(self) -> pd.DataFrame:
        instruments = self.instrument_frame()
        if instruments.empty:
            return pd.DataFrame(
                columns=["asset", "exchange", "symbol", "source", "source_symbol"]
            )
        out = instruments.loc[:, ["asset", "exchange", "symbol"]].copy()
        out["source"] = self.provider
        out["source_symbol"] = out["symbol"]
        return out

    def future_contract_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
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
        )

    def option_contract_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
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
        )

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
        api = self._load_api()
        frequency = INSIGHT_FREQUENCY.get(freq)
        if frequency is None:
            raise ValueError(f"unsupported insight freq: {freq}")

        effective_start = start_date or self.settings.default_start_date or since
        effective_end = end_date or self.settings.default_end_date
        if effective_start is None or effective_end is None:
            raise ValueError("insight import requires start_date and end_date")

        source_symbols = list(symbols or self.settings.symbols)
        if not source_symbols:
            source_symbols = self._symbols_for_asset(asset)
        if not source_symbols:
            raise ValueError(f"no insight symbols configured for asset={asset}")

        for chunk in _chunks(source_symbols, self.settings.batch_size):
            raw = api.get_kline(
                htsc_code=chunk,
                time=[
                    _request_start(effective_start, freq),
                    _request_end(effective_end, freq),
                ],
                frequency=frequency,
                fq="none",
            )
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                continue
            frame = _normalize_bars(raw, asset=asset, freq=freq, provider=self.provider)
            if since is not None:
                frame = frame[frame["trading_day"] > since]
            if not frame.empty:
                yield frame

    def _symbols_for_asset(self, asset: str) -> list[str]:
        instruments = self.instrument_frame()
        if instruments.empty:
            return []
        return sorted(
            instruments[instruments["asset"] == asset]["symbol"]
            .dropna()
            .astype(str)
            .unique()
        )

    def _load_api(self) -> _InsightApi:
        if self._api is not None:
            return self._api

        _load_env_file(self.settings.env_file)
        for runtime_path in self.settings.runtime_paths:
            _prepend_sys_path(runtime_path)
        _prepare_insight_native_libs()

        try:
            try:
                from _insight_runtime_bootstrap import prepare_insight_runtime

                prepare_insight_runtime()
            except ModuleNotFoundError:
                pass

            from insight_python.com.insight.query import (
                get_all_basic_info,
                get_kline,
                get_trading_days,
            )
            from insight_python.com.insight.common import login
            from insight_python.com.insight.market_service import market_service
        except Exception as exc:
            raise RuntimeError(
                "Insight SDK is not available. Set insight.runtime_path or install "
                "insight_python in this environment."
            ) from exc

        user = os.getenv(self.settings.username_env)
        password = os.getenv(self.settings.password_env)
        if user and password:
            result = login(market_service(), user, password)
            if self.settings.login_required and not result:
                raise RuntimeError("Insight login returned a falsy result")
        elif self.settings.login_required:
            raise RuntimeError(
                f"Insight credentials not found in env vars "
                f"{self.settings.username_env}/{self.settings.password_env}"
            )

        self._api = _InsightApi(
            get_all_basic_info=get_all_basic_info,
            get_kline=get_kline,
            get_trading_days=get_trading_days,
        )
        return self._api


def _prepend_sys_path(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


def _prepare_insight_native_libs() -> None:
    spec = importlib.util.find_spec("insight_python")
    if spec is None or not spec.submodule_search_locations:
        return
    package_dir = Path(next(iter(spec.submodule_search_locations)))
    lib_dir = (
        package_dir
        / "com"
        / "libs"
        / "linux"
        / f"python{sys.version_info.major}{sys.version_info.minor}"
    )
    if not lib_dir.exists():
        return
    for name in ["libcrypto.so.10", "libssl.so.10"]:
        path = lib_dir / name
        if path.exists():
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)


def _normalize_instruments(raw: pd.DataFrame, *, asset: str) -> pd.DataFrame:
    symbol_col = _first_existing(raw, ["htsc_code", "symbol", "security_code", "code"])
    exchange_col = _first_existing(raw, ["exchange", "exchange_code", "market"])
    name_col = _first_existing(raw, ["security_name", "name", "display_name"])
    if symbol_col is None:
        return pd.DataFrame(columns=["symbol", "asset", "exchange", "name", "status"])

    out = pd.DataFrame()
    out["symbol"] = raw[symbol_col].astype(str)
    out["asset"] = asset
    if exchange_col is not None:
        out["exchange"] = raw[exchange_col].astype(str)
    else:
        out["exchange"] = out["symbol"].map(_exchange_from_symbol)
    out["name"] = raw[name_col].astype(str) if name_col is not None else None
    out["status"] = "active"
    return out.dropna(subset=["symbol", "exchange"])


def _normalize_bars(
    raw: pd.DataFrame, *, asset: str, freq: str, provider: str
) -> pd.DataFrame:
    time_col = _first_existing(raw, ["time", "datetime", "trade_time"])
    symbol_col = _first_existing(raw, ["htsc_code", "symbol", "security_code"])
    if time_col is None or symbol_col is None:
        raise ValueError("insight kline result must include time and htsc_code columns")

    out = pd.DataFrame(index=raw.index)
    out["source_symbol"] = raw[symbol_col].astype(str)
    if freq == "1d":
        out["trading_day"] = to_date_series(raw[time_col])
        out["dt"] = out["trading_day"]
    else:
        out["dt"] = to_shanghai_timestamp_series(raw[time_col])
        out["trading_day"] = out["dt"].dt.date

    for source_col, target_col in [
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("value", "amount"),
        ("amount", "amount"),
        ("open_interest", "open_interest"),
        ("settle", "settle"),
        ("pre_close", "pre_close"),
        ("prev_close", "pre_close"),
        ("pre_settle", "pre_settle"),
        ("prev_settle", "pre_settle"),
        ("limit_up", "limit_up"),
        ("limit_down", "limit_down"),
    ]:
        if source_col in raw.columns and target_col not in out.columns:
            out[target_col] = pd.to_numeric(raw[source_col], errors="coerce")

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
        if col not in out.columns:
            out[col] = None
    status_col = _first_existing(raw, ["trading_status", "status", "suspend_status"])
    out["trading_status"] = (
        raw[status_col].astype("string") if status_col is not None else None
    )
    out["adj_factor"] = 1.0 if freq == "1d" and asset in {"stock", "etf"} else None
    out["source"] = provider
    return out.dropna(subset=["dt", "trading_day", "source_symbol"])


def _trading_days_to_dates(raw: object) -> list[date]:
    value = raw
    if isinstance(value, tuple):
        if not value:
            return []
        value = value[1] if len(value) > 1 else value[0]
    if isinstance(value, pd.DataFrame):
        if "IfTradingDay" in value.columns:
            value = value[value["IfTradingDay"] == 1]
        if "TradingDate" in value.columns:
            value = value["TradingDate"]
    dates = pd.to_datetime(value, errors="coerce")
    if hasattr(dates, "dropna"):
        dates = dates.dropna()
    return [ts.date() for ts in dates]


def _first_existing(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((name for name in names if name in df.columns), None)


def _exchange_from_symbol(symbol: str) -> str:
    if "." in symbol:
        return symbol.rsplit(".", 1)[-1].upper()
    return ""


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), max(1, size)):
        yield items[i : i + size]


def _request_start(day: date, freq: str) -> datetime:
    hour = 9 if freq == "1m" else 0
    return datetime.combine(day, time(hour=hour), tzinfo=SHANGHAI_TZ)


def _request_end(day: date, freq: str) -> datetime:
    if freq == "1m":
        return datetime.combine(day, time(hour=16), tzinfo=SHANGHAI_TZ)
    return datetime.combine(day, time(23, 59, 59), tzinfo=SHANGHAI_TZ)
