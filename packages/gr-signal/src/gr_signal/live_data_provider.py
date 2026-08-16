"""ClickHouse-backed live bar provider for signal production."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from contextlib import AbstractContextManager
from decimal import Decimal
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol

import polars as pl
from gr_backtest.data.schema import validate_bar_schema
from gr_backtest.strategy.context import (
    AccountView,
    BarContext,
    HistoryView,
    set_ctx_factors,
)
from gr_backtest.types import FREQ_TO_MINUTES
from gr_data.db.clickhouse.pool import ClickHouseConnectionPool

from gr_signal.errors import LiveDataError
from gr_signal.metrics import LIVE_DATA_LOAD_SECONDS


if TYPE_CHECKING:
    import pandas as pd
    from gr_backtest.calendar import Session

    from gr_signal.account_loader import AccountStateLoader


logger = logging.getLogger(__name__)

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\.]*$")
_BAR_SCHEMA = {
    "dt": pl.Datetime("ms", "Asia/Shanghai"),
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


class _ClickHouseClientLike(Protocol):
    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame: ...


class _ClickHousePoolLike(Protocol):
    def connection(self) -> AbstractContextManager[_ClickHouseClientLike]: ...


class LiveDataProvider:
    """Read the latest ClickHouse OHLCV bars and build live strategy contexts."""

    def __init__(
        self,
        pool: _ClickHousePoolLike | None = None,
        *,
        table_name: str = "md_bars_1m",
        account_loader: AccountStateLoader | None = None,
        sessions: Sequence[Session] | None = None,
    ) -> None:
        if not _TABLE_NAME_RE.fullmatch(table_name):
            raise LiveDataError("invalid ClickHouse table name")
        self._pool = pool if pool is not None else ClickHouseConnectionPool()
        self.table_name = table_name
        self._account_loader = account_loader
        self._sessions = tuple(sessions) if sessions is not None else None

    def load_latest_bars(
        self,
        symbols: Sequence[str],
        *,
        n_bars: int = 1,
    ) -> pl.DataFrame:
        """Load the latest ``n_bars`` completed bars per symbol from ClickHouse."""
        normalized_symbols = self._normalize_symbols(symbols)
        if n_bars <= 0:
            raise LiveDataError("n_bars must be positive")

        sql = f"""
            SELECT dt, symbol, open, high, low, close, volume
            FROM (
                SELECT
                    dt,
                    symbol,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    row_number() OVER (PARTITION BY symbol ORDER BY dt DESC) AS rn
                FROM {self.table_name}
                WHERE symbol IN {{symbols:Array(String)}}
            )
            WHERE rn <= {{n_bars:UInt32}}
            ORDER BY dt, symbol
        """
        params = {"symbols": normalized_symbols, "n_bars": n_bars}

        try:
            with self._pool.connection() as client:
                df = client.query(sql, params=params)
        except Exception as exc:
            raise LiveDataError(f"failed to load live bars: {exc}") from exc

        if df.empty:
            return self._empty_bars()

        try:
            bars = pl.from_pandas(df)
            bars = self._normalize_datetime(bars)
            return validate_bar_schema(bars.select(list(_BAR_SCHEMA.keys())))
        except Exception as exc:
            raise LiveDataError(f"invalid live bar data: {exc}") from exc

    # ------------------------------------------------------------------
    # Factors
    # ------------------------------------------------------------------

    def load_latest_factors(
        self,
        symbols: Sequence[str],
        factor_names: Sequence[str],
        *,
        n_bars: int = 1,
        table_name: str = "factors_long",
    ) -> dict[str, pl.DataFrame]:
        """Load the latest ``n_bars`` factor values per (symbol, factor).

        Returns a dictionary ``{factor_name: pl.DataFrame[dt, symbol, value]}``
        ready for ``set_ctx_factors()``.  Returns an empty dict when the
        factor table is unavailable or yields no rows — callers can
        safely pass the result through without further checks.
        """
        if not factor_names:
            return {}

        normalized_names = list(
            dict.fromkeys(str(n).strip() for n in factor_names if str(n).strip())
        )
        if not normalized_names:
            return {}

        normalized_symbols = self._normalize_symbols(symbols)

        if not _TABLE_NAME_RE.fullmatch(table_name):
            raise LiveDataError("invalid ClickHouse factor table name")

        sql = f"""
            SELECT dt, symbol, factor, value
            FROM (
                SELECT
                    dt,
                    symbol,
                    factor,
                    value,
                    row_number() OVER (
                        PARTITION BY symbol, factor ORDER BY dt DESC
                    ) AS rn
                FROM {table_name}
                WHERE symbol IN {{symbols:Array(String)}}
                  AND factor IN {{factors:Array(String)}}
            )
            WHERE rn <= {{n_bars:UInt32}}
            ORDER BY factor, dt, symbol
        """
        params = {
            "symbols": normalized_symbols,
            "factors": normalized_names,
            "n_bars": n_bars,
        }

        try:
            with self._pool.connection() as client:
                df = client.query(sql, params=params)
        except Exception:
            logger.warning(
                "Failed to load live factors from ClickHouse table %s — "
                "signals will be produced without factor data",
                table_name,
                exc_info=True,
            )
            return {}

        if df.empty:
            return {}

        try:
            bars_like = pl.from_pandas(df)
        except Exception:
            logger.warning("Failed to convert factor result to Polars", exc_info=True)
            return {}

        try:
            bars_like = self._normalize_datetime(bars_like)
        except Exception:
            logger.warning("Failed to normalize factor datetime column", exc_info=True)
            return {}

        result: dict[str, pl.DataFrame] = {}
        for factor_name, group in bars_like.group_by("factor"):
            key = str(factor_name[0]) if hasattr(factor_name, "__getitem__") else str(factor_name)
            result[key] = (
                group.drop("factor").select(["dt", "symbol", "value"]).sort(["dt", "symbol"])
            )
        return result

    async def build_context(
        self,
        symbols: Sequence[str],
        *,
        n_bars: int = 1,
        run_id: str = "live",
        factor_names: Sequence[str] | None = None,
        extra_freqs: Sequence[str] | None = None,
        strategy_id: str | None = None,
        sessions: Sequence[Session] | None = None,
    ) -> BarContext | None:
        """Build a ``BarContext`` from the latest loaded bars.

        When an ``AccountStateLoader`` is configured the context will
        include the real live account state.  Otherwise it falls back
        to a zero-state ``AccountView``.

        When *strategy_id* is provided it is forwarded to the account
        loader so that the returned ``AccountView`` reflects the
        sub-account for that strategy rather than the global account.

        When *factor_names* is a non-empty sequence the latest factor
        values are loaded from ClickHouse and injected into the context
        so that ``ctx.factor(name)`` returns data.

        When *extra_freqs* is a non-empty sequence the primary 1m bars
        are resampled in-memory to each coarser frequency and stored
        in ``ctx.extra_history`` so that multi-frequency strategies can
        access e.g. ``ctx.extra_history["5m"].lookback(n=10)``.

        *n_bars* is automatically increased when the coarsest extra
        frequency requires more 1m bars than the caller requested.

        *sessions* overrides constructor-level sessions for session-aligned
        extra-frequency resampling.
        """
        # Auto-increase n_bars for extra frequencies
        if extra_freqs:
            coarsest = max(extra_freqs, key=lambda f: FREQ_TO_MINUTES.get(f, 0))
            min_needed = FREQ_TO_MINUTES.get(coarsest, 0)
            effective_n_bars = max(n_bars, min_needed)
        else:
            effective_n_bars = n_bars

        bars_t0 = perf_counter()
        bars = self.load_latest_bars(symbols, n_bars=effective_n_bars)
        LIVE_DATA_LOAD_SECONDS.labels("bars").observe(perf_counter() - bars_t0)
        if bars.is_empty():
            return None

        if self._account_loader is not None:
            account_t0 = perf_counter()
            account = await self._account_loader.load_account_view(strategy_id=strategy_id)
            LIVE_DATA_LOAD_SECONDS.labels("account").observe(perf_counter() - account_t0)
        else:
            account = AccountView(cash=Decimal("0"), available_cash=Decimal("0"))

        current_dt = bars.select(pl.col("dt").max()).item()
        current_bar = bars.filter(pl.col("dt") == current_dt)

        history = HistoryView(bars)
        effective_sessions = tuple(sessions) if sessions is not None else self._sessions

        # In-memory resampling for extra (coarser) frequencies
        extra_history: dict[str, HistoryView] | None = None
        if extra_freqs:
            extra_history = {}
            for ef in extra_freqs:
                try:
                    extra_history[ef] = history.resampled(
                        ef,
                        source_freq="1m",
                        sessions=effective_sessions,
                    )
                # silent-fail-ok: best-effort resample — a coarser
                # frequency that we cannot synthesize is just dropped
                # from extra_history; the strategy still runs on the
                # base 1m history. Surfaced to ops via the warning log.
                except Exception:
                    logger.warning(
                        "Failed to resample 1m bars to %s for extra_freqs", ef, exc_info=True
                    )

        ctx = BarContext(
            now=current_dt,
            run_id=run_id,
            account=account,
            bar=current_bar,
            history=history,
            extra_history=extra_history or None,
        )

        if factor_names:
            factors_t0 = perf_counter()
            factors_dict = self.load_latest_factors(symbols, factor_names, n_bars=effective_n_bars)
            LIVE_DATA_LOAD_SECONDS.labels("factors").observe(perf_counter() - factors_t0)
            if factors_dict:
                set_ctx_factors(ctx, factors_dict)

        return ctx

    @staticmethod
    def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
        result = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
        if not result:
            raise LiveDataError("symbols must be non-empty")
        return result

    @staticmethod
    def _empty_bars() -> pl.DataFrame:
        return pl.DataFrame(
            {name: pl.Series(name, [], dtype=dtype) for name, dtype in _BAR_SCHEMA.items()}
        )

    @staticmethod
    def _empty_factor_df() -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "dt": pl.Datetime("ms", "Asia/Shanghai"),
                "symbol": pl.Utf8,
                "value": pl.Float64,
            }
        )

    @staticmethod
    def _normalize_datetime(bars: pl.DataFrame) -> pl.DataFrame:
        dtype = bars.schema.get("dt")
        if not isinstance(dtype, pl.Datetime):
            return bars.with_columns(pl.col("dt").cast(pl.Datetime("ms", "Asia/Shanghai")))
        if dtype.time_zone is None:
            return bars.with_columns(
                pl.col("dt").dt.cast_time_unit("ms").dt.replace_time_zone("Asia/Shanghai")
            )
        if dtype.time_zone != "Asia/Shanghai":
            return bars.with_columns(
                pl.col("dt").dt.cast_time_unit("ms").dt.convert_time_zone("Asia/Shanghai")
            )
        return bars.with_columns(pl.col("dt").dt.cast_time_unit("ms"))


__all__ = ["LiveDataProvider"]
