"""Signal producer — converts strategy output to live signal DataFrames."""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from getrich_backtest.live.errors import SignalProductionError
from getrich_backtest.live.signal import Signal
from getrich_backtest.strategy.base import Strategy
from getrich_backtest.strategy.context import BarContext
from getrich_backtest.strategy.order import OrderIntent
from getrich_backtest.strategy.signal import SignalStrategy
from getrich_backtest.types import Side


_SIGNAL_COLUMNS = {
    "symbol": pl.Utf8,
    "action": pl.Utf8,
    "direction": pl.Utf8,
    "confidence": pl.Float64,
    "trigger_price": pl.Float64,
    "trigger_time": pl.Datetime("ms", "Asia/Shanghai"),
    "reason": pl.Utf8,
}


def _side_to_action(side: Side) -> str:
    """Map a Side enum to a signal action string."""
    if side in (Side.BUY, Side.OPEN_LONG):
        return "buy"
    if side in (Side.SELL, Side.CLOSE_LONG):
        return "sell"
    return "hold"


def _side_to_direction(side: Side) -> str | None:
    """Map a Side enum to a signal direction string."""
    if side in (Side.BUY, Side.SELL):
        return None  # direction-neutral for equity-style
    if side == Side.OPEN_LONG:
        return "long"
    if side == Side.CLOSE_LONG:
        return "short"
    return None


def _empty_signal_df() -> pl.DataFrame:
    """Return an empty signal DataFrame with the canonical schema."""
    return pl.DataFrame({col: pl.Series([], dtype=dtype) for col, dtype in _SIGNAL_COLUMNS.items()})


class SignalProducer:
    """Produces live signal DataFrames by wrapping a Strategy.

    Supports both ``SignalStrategy`` (via ``compute_signal()``) and
    plain ``Strategy`` (via ``on_bar()``).

    Parameters
    ----------
    strategy : SignalStrategy | Strategy
        The strategy to produce signals from.
    """

    def __init__(self, strategy: SignalStrategy | Strategy) -> None:
        self.strategy = strategy
        self.last_signal_df: pl.DataFrame | None = None

    def produce(self, ctx: BarContext) -> pl.DataFrame:
        """Run the strategy against *ctx* and return a signal DataFrame.

        The returned DataFrame has columns ``["symbol", "action", "direction",
        "confidence", "trigger_price", "trigger_time", "reason"]``.

        Returns an empty DataFrame (with the canonical schema) when the
        strategy produces no signals.
        """
        bar_close = self._get_bar_close(ctx)

        if isinstance(self.strategy, SignalStrategy):
            return self._produce_from_scores(ctx, bar_close)
        return self._produce_from_intents(ctx, bar_close)

    def to_signals(self, df: pl.DataFrame) -> list[Signal]:
        """Convert a signal DataFrame to a list of ``Signal`` domain objects."""
        if df.is_empty():
            return []

        signals: list[Signal] = []
        for row in df.iter_rows(named=True):
            signals.append(
                Signal(
                    symbol=str(row["symbol"]),
                    action=str(row["action"]),
                    direction=row.get("direction"),
                    confidence=(
                        Decimal(str(row["confidence"]))
                        if row.get("confidence") is not None
                        else None
                    ),
                    trigger_price=(
                        Decimal(str(row["trigger_price"]))
                        if row.get("trigger_price") is not None
                        else None
                    ),
                    trigger_time=row.get("trigger_time"),
                    reason=row.get("reason"),
                )
            )
        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _produce_from_scores(self, ctx: BarContext, bar_close: dict[str, float]) -> pl.DataFrame:
        """Produce signals from a SignalStrategy's compute_signal()."""
        try:
            scores = self.strategy.compute_signal(ctx)
        except NotImplementedError:
            return _empty_signal_df()

        if scores is None or scores.is_empty():
            return _empty_signal_df()

        # Drop null scores
        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _empty_signal_df()

        # Determine max absolute score for confidence normalization
        max_abs = float(scores.select(pl.col("score").abs().max()).item())
        if max_abs <= 0.0:
            return _empty_signal_df()

        # Build the signal DataFrame
        result = scores.with_columns(
            [
                pl.when(pl.col("score") > 0.0)
                .then(pl.lit("buy"))
                .otherwise(pl.lit("sell"))
                .alias("action"),
                pl.when(pl.col("score") > 0.0)
                .then(pl.lit("long"))
                .otherwise(pl.lit("short"))
                .alias("direction"),
                (pl.col("score").abs() / max_abs).alias("confidence"),
                pl.col("symbol").replace_strict(bar_close, default=None).alias("trigger_price"),
                pl.lit(ctx.now).alias("trigger_time"),
                pl.lit(None, dtype=pl.Utf8).alias("reason"),
            ]
        ).select(list(_SIGNAL_COLUMNS.keys()))

        self.last_signal_df = result
        return result

    def _produce_from_intents(self, ctx: BarContext, bar_close: dict[str, float]) -> pl.DataFrame:
        """Produce signals from a plain Strategy's on_bar()."""
        try:
            intents = self.strategy.on_bar(ctx)
        except Exception:
            return _empty_signal_df()

        if not intents:
            return _empty_signal_df()

        rows: list[dict] = []
        for intent in intents:
            if not isinstance(intent, OrderIntent):
                raise SignalProductionError(f"Expected OrderIntent, got {type(intent).__name__}")
            action = _side_to_action(intent.side)
            direction = _side_to_direction(intent.side)
            confidence = None  # plain OrderIntent carries no confidence score
            trigger_price = bar_close.get(intent.symbol)
            rows.append(
                {
                    "symbol": intent.symbol,
                    "action": action,
                    "direction": direction,
                    "confidence": confidence,
                    "trigger_price": trigger_price,
                    "trigger_time": ctx.now,
                    "reason": None,
                }
            )

        result = pl.DataFrame(
            rows,
            schema=_SIGNAL_COLUMNS,
            orient="row",
        )

        self.last_signal_df = result
        return result

    @staticmethod
    def _get_bar_close(ctx: BarContext) -> dict[str, float]:
        """Extract ``{symbol: close}`` from the current bar."""
        bar = ctx.bar
        if bar.is_empty() or "close" not in bar.columns:
            return {}
        close_map: dict[str, float] = {}
        for row in bar.select(["symbol", "close"]).iter_rows(named=True):
            v = row.get("close")
            if v is not None:
                close_map[str(row["symbol"])] = float(v)
        return close_map
