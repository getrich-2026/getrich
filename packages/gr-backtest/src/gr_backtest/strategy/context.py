"""Strategy context and read-only account/history views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

import polars as pl

from gr_backtest.data.schema import validate_bar_schema
from gr_backtest.exceptions import StrategyError
from gr_backtest.time import require_shanghai_aware


if TYPE_CHECKING:
    from gr_backtest.calendar import Calendar, Session


_DECIMAL_ZERO = Decimal("0")


@dataclass(frozen=True)
class PositionView:
    """Read-only position view exposed to strategies."""

    symbol: str
    qty: Decimal = _DECIMAL_ZERO

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise StrategyError("position symbol must be non-empty")
        if not isinstance(self.qty, Decimal):
            raise StrategyError("position qty must be decimal.Decimal")


@dataclass(frozen=True)
class AccountView:
    """Read-only account view exposed to strategies."""

    cash: Decimal = _DECIMAL_ZERO
    positions: Mapping[str, PositionView] | None = None
    available_cash: Decimal | None = None  # None for backward compat
    maintenance_margin: Decimal = _DECIMAL_ZERO

    def __post_init__(self) -> None:
        if not isinstance(self.cash, Decimal):
            raise StrategyError("account cash must be decimal.Decimal")
        positions = self.positions or {}
        object.__setattr__(self, "positions", MappingProxyType(dict(positions)))
        if self.available_cash is not None and not isinstance(self.available_cash, Decimal):
            raise StrategyError("account available_cash must be decimal.Decimal or None")
        if not isinstance(self.maintenance_margin, Decimal):
            raise StrategyError("account maintenance_margin must be decimal.Decimal")

    def position(self, symbol: str) -> PositionView:
        """Return an existing position or a zero-quantity view."""
        if not symbol.strip():
            raise StrategyError("symbol must be non-empty")
        positions = self.positions or {}
        return positions.get(symbol, PositionView(symbol=symbol))


@dataclass(frozen=True)
class HistoryView:
    """Read-only historical bar window exposed to strategies."""

    bars: pl.DataFrame = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", validate_bar_schema(self.bars))

    def lookback(
        self,
        symbols: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
        n: int = 1,
    ) -> pl.DataFrame:
        """Return the last ``n`` distinct bar datetimes from the visible history."""
        if n <= 0:
            raise StrategyError("n must be positive")

        result = self.bars
        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(list(symbols)))

        if result.is_empty():
            return result.select(list(columns)) if columns is not None else result

        last_dts = result.select(pl.col("dt").unique().sort().tail(n).alias("dt"))
        result = result.join(last_dts, on="dt", how="semi").sort(["dt", "symbol"])

        if columns is not None:
            missing_columns = set(columns).difference(result.columns)
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise StrategyError(f"requested columns are not available: {missing}")
            result = result.select(list(columns))

        return result

    def resampled(
        self,
        freq: str,
        *,
        source_freq: str = "1m",
        sessions: tuple[Session, ...] | None = None,
    ) -> HistoryView:
        """Return a new ``HistoryView`` of bars resampled to *freq*.

        Results are lazy-cached: repeated calls with the same *freq*,
        *source_freq*, and *sessions* return the same ``HistoryView`` instance.

        Parameters
        ----------
        freq : str
            Target frequency (e.g. ``"1d"``, ``"1h"``, ``"5m"``).
        source_freq : str
            Source frequency for the underlying resampling (default ``"1m"``).
        sessions : tuple[Session, ...] | None
            Optional session definitions for session-aligned resampling.

        Returns
        -------
        HistoryView
            A read-only view of the resampled bars.

        Raises
        ------
        ValueError
            If *freq* is invalid or not coarser than *source_freq*.
        """
        from gr_backtest.data.resample import resample_bars

        cache: dict[tuple[str, str, tuple[Session, ...] | None], HistoryView] = getattr(
            self, "_resampled_cache", {}
        )
        key = (freq, source_freq, sessions)
        if key in cache:
            return cache[key]

        resampled_bars = resample_bars(self.bars, freq, source_freq=source_freq, sessions=sessions)
        view = HistoryView(bars=resampled_bars)
        cache[key] = view
        object.__setattr__(self, "_resampled_cache", cache)
        return view


@dataclass(frozen=True)
class Context:
    """Base strategy callback context."""

    now: datetime
    run_id: str
    account: AccountView

    def __post_init__(self) -> None:
        require_shanghai_aware(self.now)
        if not self.run_id.strip():
            raise StrategyError("run_id must be non-empty")

    @property
    def instruments(self) -> pl.DataFrame | None:
        """Instrument metadata (set during setup by the backtest runner)."""
        return getattr(self, "_instruments", None)

    @property
    def calendar(self) -> Calendar | None:
        """Exchange calendar (set during setup by the backtest runner)."""
        return getattr(self, "_calendar", None)

    @property
    def corp_actions(self) -> pl.DataFrame | None:
        """Corporate actions data (set during setup by the backtest runner)."""
        return getattr(self, "_corp_actions", None)

    @property
    def factors(self) -> dict[str, pl.DataFrame] | None:
        """Factor data dictionary ``{name → pl.DataFrame}``."""
        return getattr(self, "_factors", None)

    def factor(self, name: str) -> pl.DataFrame | None:
        """Return pre-loaded factor values for the given factor name.

        Parameters
        ----------
        name : str
            Factor name (e.g. ``"mom20"``, ``"rs_14"``).

        Returns
        -------
        pl.DataFrame | None
            A DataFrame with columns ``dt``, ``symbol``, ``value`` for the
            requested factor, or ``None`` if the factor is not available.
        """
        factors = getattr(self, "_factors", None)
        if factors is None or name not in factors:
            return None
        return factors[name]


def set_ctx_instruments(ctx: Context, instruments: pl.DataFrame | None) -> None:
    """Set instruments on a frozen Context object (called by the backtest runner)."""
    object.__setattr__(ctx, "_instruments", instruments)


def set_ctx_calendar(ctx: Context, cal: Calendar | None) -> None:
    """Set calendar on a frozen Context object (called by the backtest runner)."""
    object.__setattr__(ctx, "_calendar", cal)


def set_ctx_corp_actions(ctx: Context, corp_actions: pl.DataFrame | None) -> None:
    """Set corporate actions on a frozen Context object."""
    object.__setattr__(ctx, "_corp_actions", corp_actions)


def set_ctx_factors(
    ctx: Context,
    factors: dict[str, pl.DataFrame] | None,
) -> None:
    """Set factor data on a frozen Context object."""
    object.__setattr__(ctx, "_factors", factors)


@dataclass(frozen=True)
class BarContext(Context):
    """Strategy callback context for a visible bar window."""

    bar: pl.DataFrame = field(repr=False)
    history: HistoryView = field(repr=False)
    extra_history: dict[str, HistoryView] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "bar", validate_bar_schema(self.bar))

    def lookback(
        self,
        symbols: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
        n: int = 1,
    ) -> pl.DataFrame:
        """Delegate to the context history view."""
        return self.history.lookback(symbols=symbols, columns=columns, n=n)
