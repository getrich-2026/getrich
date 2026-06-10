from __future__ import annotations

import os
from datetime import date
from collections.abc import Sequence
from typing import Iterable

import pandas as pd

from getrich_data_import.adapters.base import SourceCoverage
from getrich_data_import.common.config import RicequantSettings
from getrich_data_import.common.logger import get_logger

from getrich_data_import.common.time import to_shanghai_timestamp_series

logger = get_logger(__name__)

RQ_TYPE_MAP = {
    "stock": "CS",
    "index": "Index",
    "etf": "ETF",
    "future": "Future",
    "option": "Option",
}


class RiceQuantSource:
    """RiceQuant historical data adapter backed by rqdatac.

    The adapter exposes normalized frames used by the existing import pipeline,
    while keeping provider-specific API calls isolated in this module.
    """

    name = "ricequant"

    def __init__(self, settings: RicequantSettings, provider: str = "ricequant") -> None:
        self.settings = settings
        self.provider = provider
        self._initialized = False
        self._instruments_cache: dict[str, pd.DataFrame] = {}

    def _init_api(self) -> None:
        if self._initialized:
            return
        import rqdatac

        _load_env_file(self.settings.env_file)
        license_key = os.getenv(self.settings.license_env)
        user = os.getenv(self.settings.username_env)
        password = os.getenv(self.settings.password_env)
        if license_key:
            init_mode = self.settings.init_mode.lower()
            if init_mode == "tcp_license":
                rqdatac.init(
                    f"tcp://license:{license_key}@rqdatad-pro.ricequant.com:16011"
                )
            elif init_mode == "license":
                rqdatac.init("license", license_key)
            else:
                raise ValueError(f"unsupported RiceQuant init_mode: {self.settings.init_mode}")
        elif user and password:
            rqdatac.init(user, password)
        else:
            if getattr(self.settings, "login_required", True):
                raise ValueError(
                    f"RiceQuant credentials required but not found in env vars "
                    f"{self.settings.license_env}, or "
                    f"{self.settings.username_env} and {self.settings.password_env}."
                )
            logger.warning(
                f"RiceQuant credentials not found in env vars "
                f"{self.settings.license_env} or "
                f"{self.settings.username_env}/{self.settings.password_env}. "
                f"Assuming already initialized or using default env."
            )
            try:
                rqdatac.init()
            except Exception as exc:
                raise RuntimeError("Failed to initialize rqdatac") from exc
        self._initialized = True

    def scan(self) -> SourceCoverage:
        return SourceCoverage(
            calendar_files=0,
            instruments={"configured_symbols": len(self.settings.symbols)},
            kline_day_files=0,
            kline_min1_files=0,
        )

    def convert_symbols(
        self, symbols: str | Sequence[str], *, to: str | None = None
    ) -> str | list[str]:
        """Convert external symbols to or from RiceQuant order_book_id values.

        Args:
            symbols: One symbol or a sequence of symbols accepted by
                `rqdatac.id_convert`.
            to: Optional conversion target. RiceQuant uses `to="normal"` for
                order_book_id to exchange-style codes.

        Returns:
            The converted symbol string for scalar input, or a list for
            sequence input.

        Time Complexity:
            O(n), where n is the number of symbols.

        Space Complexity:
            O(n), for the converted result.
        """
        self._init_api()
        import rqdatac

        return rqdatac.id_convert(symbols, to=to)

    def calendar_frames(self) -> Iterable[pd.DataFrame]:
        self._init_api()
        import rqdatac

        start_date = self.settings.default_start_date
        end_date = self.settings.default_end_date
        if start_date is None or end_date is None:
            return

        raw_days = rqdatac.get_trading_dates(
            start_date, end_date, market=self.settings.market
        )
        if not raw_days:
            return

        dates = [d.date() if hasattr(d, "date") else d for d in pd.to_datetime(raw_days)]
        series = pd.Series(sorted(dates))

        # 注意：当前所有交易所共用 A 股 get_trading_dates() 结果，是已知近似，期货交易所细微差异未处理。
        # CNI（国证指数）/CSI（中证指数）是指数编制机构，不是交易所，不写入 trading_calendar。
        for exchange in ["XSHG", "XSHE", "CCFX", "XSGE", "XDCE", "XZCE", "XGFE", "XINE"]:
            df = pd.DataFrame(
                {
                    "exchange": exchange,
                    "trading_day": series.values,
                    "is_open": True,
                    "has_night": exchange in {"CCFX", "XSGE", "XDCE", "XZCE", "XGFE", "XINE"},
                    "prev_trading_day": series.shift(1).values,
                    "next_trading_day": series.shift(-1).values,
                }
            )
            yield df.where(pd.notna(df), None)

    def _get_all_instruments(self, rq_type: str) -> pd.DataFrame:
        if rq_type in self._instruments_cache:
            return self._instruments_cache[rq_type]
        self._init_api()
        import rqdatac
        try:
            raw = rqdatac.all_instruments(type=rq_type, market=self.settings.market)
            if isinstance(raw, pd.DataFrame):
                self._instruments_cache[rq_type] = raw
            return raw
        except Exception:
            logger.warning("rqdatac all_instruments failed", extra={"rq_type": rq_type}, exc_info=True)
            return pd.DataFrame()

    def instrument_frame(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for asset, rq_type in RQ_TYPE_MAP.items():
            raw = self._get_all_instruments(rq_type)

            if not isinstance(raw, pd.DataFrame) or raw.empty:
                continue

            out = pd.DataFrame()
            out["symbol"] = raw["order_book_id"].astype(str)
            out["asset"] = asset
            out["exchange"] = raw["exchange"] if "exchange" in raw.columns else out["symbol"].apply(lambda x: x.split(".")[1] if "." in x else "")
            # raw["symbol"] in rqdatac is actually the Chinese display name (e.g., "平安银行")
            out["name"] = raw["symbol"].astype(str) if "symbol" in raw.columns else None
            status_col = "status" if "status" in raw.columns else None
            if status_col:
                out["status"] = raw[status_col].astype(str)
            else:
                out["status"] = "active"
            frames.append(out)

        if not frames:
            return pd.DataFrame(columns=["symbol", "asset", "exchange", "name", "status"])

        return pd.concat(frames, ignore_index=True).drop_duplicates(["asset", "exchange", "symbol"])

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
        raw = self._get_all_instruments("Future")

        if not isinstance(raw, pd.DataFrame) or raw.empty:
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

        out = pd.DataFrame()
        out["asset"] = "future"
        out["symbol"] = raw["order_book_id"].astype(str)
        out["exchange"] = raw["exchange"] if "exchange" in raw.columns else out["symbol"].apply(lambda x: x.split(".")[1] if "." in x else "")
        out["underlying"] = raw["underlying_symbol"] if "underlying_symbol" in raw.columns else None
        out["multiplier"] = pd.to_numeric(raw["contract_multiplier"], errors="coerce") if "contract_multiplier" in raw.columns else None
        out["price_tick"] = pd.to_numeric(raw["tick_size"], errors="coerce") if "tick_size" in raw.columns else None
        out["list_date"] = pd.to_datetime(raw["listed_date"], errors="coerce").dt.date if "listed_date" in raw.columns else None
        out["last_trade_date"] = pd.to_datetime(raw["de_listed_date"], errors="coerce").dt.date if "de_listed_date" in raw.columns else None
        out["delivery_date"] = pd.to_datetime(raw["maturity_date"], errors="coerce").dt.date if "maturity_date" in raw.columns else None
        return out

    def option_contract_frame(self) -> pd.DataFrame:
        raw = self._get_all_instruments("Option")

        if not isinstance(raw, pd.DataFrame) or raw.empty:
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

        out = pd.DataFrame()
        out["asset"] = "option"
        out["symbol"] = raw["order_book_id"].astype(str)
        out["exchange"] = raw["exchange"] if "exchange" in raw.columns else out["symbol"].apply(lambda x: x.split(".")[1] if "." in x else "")
        out["underlying_symbol"] = raw["underlying_symbol"] if "underlying_symbol" in raw.columns else None
        out["option_type"] = raw["option_type"] if "option_type" in raw.columns else None
        out["exercise_style"] = raw["exercise_style"] if "exercise_style" in raw.columns else None
        out["strike"] = pd.to_numeric(raw["strike_price"], errors="coerce") if "strike_price" in raw.columns else None
        out["multiplier"] = pd.to_numeric(raw["contract_multiplier"], errors="coerce") if "contract_multiplier" in raw.columns else None
        out["list_date"] = pd.to_datetime(raw["listed_date"], errors="coerce").dt.date if "listed_date" in raw.columns else None
        out["last_trade_date"] = pd.to_datetime(raw["de_listed_date"], errors="coerce").dt.date if "de_listed_date" in raw.columns else None
        out["exercise_date"] = pd.to_datetime(raw["maturity_date"], errors="coerce").dt.date if "maturity_date" in raw.columns else None
        return out

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
        self._init_api()
        import rqdatac

        effective_start = start_date or self.settings.default_start_date or since
        effective_end = end_date or self.settings.default_end_date
        if effective_start is None or effective_end is None:
            raise ValueError("ricequant import requires start_date and end_date")

        source_symbols = list(symbols or self.settings.symbols)
        if not source_symbols:
            source_symbols = self._symbols_for_asset(asset)
        if not source_symbols:
            raise ValueError(f"no ricequant symbols configured for asset={asset}")

        rq_freq = "1d" if freq == "1d" else "1m"

        chunk_size = self.settings.batch_size
        for i in range(0, len(source_symbols), max(1, chunk_size)):
            chunk = source_symbols[i:i+chunk_size]
            try:
                raw = rqdatac.get_price(
                    chunk,
                    start_date=effective_start,
                    end_date=effective_end,
                    frequency=rq_freq,
                    adjust_type="none",
                    market=self.settings.market,
                )
            except Exception:
                logger.warning(
                    "rqdatac get_price failed",
                    extra={"chunk": f"{chunk[0]}...({len(chunk)})", "asset": asset, "freq": freq},
                    exc_info=True,
                )
                continue

            if raw is None or raw.empty:
                continue

            raw = raw.reset_index()

            if "order_book_id" not in raw.columns:
                if len(chunk) == 1:
                    # rqdatac 对单标的请求不返回 order_book_id 列（用 DatetimeIndex），安全回填
                    raw["order_book_id"] = chunk[0]
                else:
                    # 多标的缺少 order_book_id 无法区分数据归属，跳过以防静默污染
                    logger.warning(
                        "rqdatac get_price returned data without order_book_id",
                        extra={"chunk": f"{chunk[0]}...({len(chunk)})", "asset": asset, "freq": freq}
                    )
                    continue

            out = pd.DataFrame()
            out["source_symbol"] = raw["order_book_id"].astype(str)

            time_col = "date" if "date" in raw.columns else "datetime"

            if freq == "1d":
                out["trading_day"] = pd.to_datetime(raw[time_col]).dt.date
                out["dt"] = out["trading_day"]
            else:
                out["dt"] = to_shanghai_timestamp_series(raw[time_col])
                if asset in {"future", "option"} and "trading_date" in raw.columns:
                    out["trading_day"] = pd.to_datetime(raw["trading_date"]).dt.date
                else:
                    out["trading_day"] = out["dt"].dt.date

            for source_col, target_col in [
                ("open", "open"),
                ("high", "high"),
                ("low", "low"),
                ("close", "close"),
                ("volume", "volume"),
                ("total_turnover", "amount"),
                ("open_interest", "open_interest"),
                ("settlement", "settle"),
                ("prev_close", "pre_close"),
                ("prev_settlement", "pre_settle"),
                ("limit_up", "limit_up"),
                ("limit_down", "limit_down"),
            ]:
                if source_col in raw.columns:
                    out[target_col] = pd.to_numeric(raw[source_col], errors="coerce")
                else:
                    if target_col not in out.columns:
                        out[target_col] = None

            out["trading_status"] = None
            # adj_factor=1.0 means data is unadjusted
            out["adj_factor"] = 1.0 if freq == "1d" and asset in {"stock", "etf"} else None
            out["source"] = self.provider

            if since is not None:
                out = out[out["trading_day"] > since]
            if not out.empty:
                yield out.dropna(subset=["dt", "trading_day", "source_symbol"])

    def trading_period_frames(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        frequency: str = "1m",
    ) -> Iterable[pd.DataFrame]:
        """Fetch continuous trading periods for configured RiceQuant symbols.

        Args:
            start_date: Optional inclusive start date. Defaults to provider
                config.
            end_date: Optional inclusive end date. Defaults to provider config.
            symbols: Optional RiceQuant order_book_id list. Defaults to
                configured symbols.
            frequency: RiceQuant frequency, usually `1m` or `tick`.

        Yields:
            DataFrames with `source_symbol`, `trading_day`, `frequency`,
            `trading_hours`, and `source`.

        Time Complexity:
            O(n * r), where n is requested symbols and r is returned rows per
            symbol/date.

        Space Complexity:
            O(r), per yielded batch.
        """
        self._init_api()
        import rqdatac

        effective_start = start_date or self.settings.default_start_date
        effective_end = end_date or self.settings.default_end_date
        if effective_start is None or effective_end is None:
            raise ValueError("ricequant trading periods require start_date and end_date")

        source_symbols = list(symbols or self.settings.symbols)
        if not source_symbols:
            raise ValueError("no ricequant symbols configured for trading periods")

        chunk_size = self.settings.batch_size
        for i in range(0, len(source_symbols), max(1, chunk_size)):
            chunk = source_symbols[i : i + chunk_size]
            try:
                raw = rqdatac.get_trading_periods(
                    chunk,
                    start_date=effective_start,
                    end_date=effective_end,
                    frequency=frequency,
                    market=self.settings.market,
                )
            except Exception:
                logger.warning(
                    "rqdatac get_trading_periods failed",
                    extra={
                        "chunk": f"{chunk[0]}...({len(chunk)})",
                        "frequency": frequency,
                    },
                    exc_info=True,
                )
                continue

            if raw is None or raw.empty:
                continue

            normalized = raw.reset_index()
            if "order_book_id" not in normalized.columns:
                if len(chunk) == 1:
                    normalized["order_book_id"] = chunk[0]
                else:
                    logger.warning(
                        "rqdatac get_trading_periods returned data without order_book_id",
                        extra={"chunk": f"{chunk[0]}...({len(chunk)})"},
                    )
                    continue

            date_col = "date" if "date" in normalized.columns else "trading_date"
            if date_col not in normalized.columns or "trading_hours" not in normalized.columns:
                logger.warning(
                    "rqdatac get_trading_periods returned unsupported schema",
                    extra={"columns": ",".join(map(str, normalized.columns))},
                )
                continue

            out = pd.DataFrame()
            out["source_symbol"] = normalized["order_book_id"].astype(str)
            out["trading_day"] = pd.to_datetime(normalized[date_col]).dt.date
            out["frequency"] = frequency
            out["trading_hours"] = normalized["trading_hours"].astype(str)
            out["source"] = self.provider
            yield out.dropna(subset=["source_symbol", "trading_day", "trading_hours"])

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


def _load_env_file(path: object | None) -> None:
    """Load dotenv-style key/value pairs without overriding existing env vars.

    Args:
        path: Optional local env file path.

    Time Complexity:
        O(n), where n is the number of lines in the env file.

    Space Complexity:
        O(1), excluding environment storage.
    """
    if path is None:
        return
    env_path = os.fspath(path)
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8", errors="ignore") as file:
        for line in file:
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
