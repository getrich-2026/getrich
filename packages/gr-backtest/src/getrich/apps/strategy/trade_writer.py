"""Async writer that persists backtest ``Fill`` objects to ``strategy_trades``."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from getrich.apps.strategy.errors import SignalWriteError
from getrich.libs.postgres.pool import PgConnectionPool, pg_pool
from getrich_backtest.execution import Fill
from getrich_backtest.types import Side


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_TABLE = "strategy_trades"

_INSERT_SQL = f"""
    INSERT INTO {_TABLE} (
        id, strategy_id, signal_id, symbol, action,
        quantity, price, notional, fee, slippage,
        avg_cost, realized_pnl, cumulative_pnl,
        executed_at, bar_dt, tag
    ) VALUES (
        %(id)s, %(strategy_id)s, %(signal_id)s, %(symbol)s, %(action)s,
        %(quantity)s, %(price)s, %(notional)s, %(fee)s, %(slippage)s,
        %(avg_cost)s, %(realized_pnl)s, %(cumulative_pnl)s,
        %(executed_at)s, %(bar_dt)s, %(tag)s
    )
    ON CONFLICT (id) DO NOTHING
"""

_DECIMAL_ZERO = Decimal("0")

_BUY_SIDES = {Side.BUY, Side.OPEN_LONG, Side.CLOSE_SHORT}
_SELL_SIDES = {Side.SELL, Side.CLOSE_LONG, Side.OPEN_SHORT}


def _side_to_action(side: Side) -> str:
    if side in _BUY_SIDES:
        return "buy"
    return "sell"


def _handle_buy(t: dict[str, Decimal], fill: Fill, avg_cost_before: Decimal) -> None:
    """Apply a buy-side fill to the per-symbol AVCO tracker.

    - Long or flat (``net_qty >= 0``): adds to the long position.
    - Short (``net_qty < 0``): covers/repurchases the short position;
      any excess above the short size opens a new long.
    """
    if t["net_qty"] >= _DECIMAL_ZERO:
        # Adding to (or opening) a long position — no PnL yet.
        t["net_qty"] += fill.qty
        t["total_cost"] += fill.notional
        t["_last_realized_pnl"] = _DECIMAL_ZERO
    else:
        # Covering a short position.
        cover_qty = min(fill.qty, -t["net_qty"])
        t["_last_realized_pnl"] = (avg_cost_before - fill.price) * cover_qty
        t["cumulative_pnl"] += t["_last_realized_pnl"]
        t["net_qty"] += cover_qty  # net_qty is negative → moves *toward* zero
        if t["net_qty"] < _DECIMAL_ZERO:
            t["total_cost"] = avg_cost_before * (-t["net_qty"])
        else:
            t["total_cost"] = _DECIMAL_ZERO

        # Any excess buy opens a fresh long position.
        excess = fill.qty - cover_qty
        if excess > _DECIMAL_ZERO:
            t["net_qty"] += excess
            t["total_cost"] += fill.price * excess


def _handle_sell(t: dict[str, Decimal], fill: Fill, avg_cost_before: Decimal) -> None:
    """Apply a sell-side fill to the per-symbol AVCO tracker.

    - Long (``net_qty > 0``): sells from the long position;
      any excess above the position size opens a new short.
    - Flat or short (``net_qty <= 0``): adds to the short position.
    """
    if t["net_qty"] > _DECIMAL_ZERO:
        # Selling from a long position.
        sell_qty = min(fill.qty, t["net_qty"])
        t["_last_realized_pnl"] = (fill.price - avg_cost_before) * sell_qty
        t["cumulative_pnl"] += t["_last_realized_pnl"]
        t["net_qty"] -= sell_qty
        if t["net_qty"] > _DECIMAL_ZERO:
            t["total_cost"] = avg_cost_before * t["net_qty"]
        else:
            t["total_cost"] = _DECIMAL_ZERO

        # Any excess sell opens a fresh short position.
        excess = fill.qty - sell_qty
        if excess > _DECIMAL_ZERO:
            t["net_qty"] -= excess
            t["total_cost"] = fill.price * excess
    else:
        # Adding to (or opening) a short position — no PnL yet.
        t["net_qty"] -= fill.qty
        t["total_cost"] += fill.notional
        t["_last_realized_pnl"] = _DECIMAL_ZERO


class BacktestTradeWriter:
    """Write backtest fills into the ``strategy_trades`` PostgreSQL table.

    Replicates the average-cost (AVCO) PnL tracking logic from
    :func:`getrich_backtest.attribution.compute_trade_journal` so that
    ``avg_cost``, ``realized_pnl``, and ``cumulative_pnl`` are populated
    correctly on every row.

    Uses the global ``pg_pool`` singleton by default.

    Parameters
    ----------
    pool : PgConnectionPool | None
        Connection pool instance (default: ``pg_pool``).
    """

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write_fills(
        self,
        fills: tuple[Fill, ...],
        strategy_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> int:
        """Persist backtest fills to ``strategy_trades`` in a single transaction.

        Computes per-symbol average cost, realized PnL, and cumulative PnL
        before inserting.  ``ON CONFLICT (id) DO NOTHING`` ensures the
        operation is idempotent — re-running the same backtest import
        will not create duplicates.

        Parameters
        ----------
        fills : tuple[Fill, ...]
            Chronologically ordered fills from a backtest run.
        strategy_id : str
            Internal UUID of the strategy (from ``strategies.id``).
        conn : AsyncConnection | None
            Optional existing connection for transaction grouping.

        Returns
        -------
        int
            Number of rows inserted (may be 0 if all fills already exist).
        """
        if not fills:
            return 0

        params_list = self._build_params(fills, strategy_id)

        async def _do(c: AsyncConnection) -> int:
            try:
                count = 0
                async with c.cursor() as cur:
                    for params in params_list:
                        await cur.execute(_INSERT_SQL, params)
                        if cur.rowcount is not None and cur.rowcount > 0:
                            count += 1
                return count
            except Exception as exc:
                raise SignalWriteError(f"failed to write backtest fills: {exc}") from exc

        if conn is not None:
            return await _do(conn)

        async with self._pool.connection() as c:
            count = await _do(c)
            await c.commit()
        return count

    # ------------------------------------------------------------------
    # Private: AVCO + param building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_params(
        fills: tuple[Fill, ...],
        strategy_id: str,
    ) -> list[dict]:
        """Compute AVCO PnL and build INSERT parameter dicts for every fill.

        Sorts fills by ``(symbol, fill_time)`` to ensure correct per-symbol
        cost tracking order, replicating the logic in
        :func:`getrich_backtest.attribution.compute_trade_journal`.

        Uses *signed* net-quantity tracking so that both long-only and
        long/short strategies produce correct ``realized_pnl`` values.
        ``net_qty`` is positive for net-long positions and negative for
        net-short positions; ``total_cost`` is always non-negative
        (cost basis for longs, total short-sale proceeds for shorts).
        """
        sorted_fills = sorted(fills, key=lambda f: (f.symbol, f.fill_time))

        # Per-symbol AVCO tracker: {symbol: {net_qty, total_cost, cumulative_pnl}}
        trackers: dict[str, dict[str, Decimal]] = {}
        params_list: list[dict] = []

        for fill in sorted_fills:
            sym = fill.symbol
            if sym not in trackers:
                trackers[sym] = {
                    "net_qty": _DECIMAL_ZERO,
                    "total_cost": _DECIMAL_ZERO,
                    "cumulative_pnl": _DECIMAL_ZERO,
                }
            t = trackers[sym]

            avg_cost_before = (
                t["total_cost"] / abs(t["net_qty"])
                if t["net_qty"] != _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            realized_pnl = _DECIMAL_ZERO

            if fill.side in _BUY_SIDES:
                _handle_buy(t, fill, avg_cost_before)
                # realized_pnl is set inside _handle_buy via the tracker
                realized_pnl = t.pop("_last_realized_pnl", _DECIMAL_ZERO)
            elif fill.side in _SELL_SIDES:
                _handle_sell(t, fill, avg_cost_before)
                realized_pnl = t.pop("_last_realized_pnl", _DECIMAL_ZERO)

            params_list.append(
                {
                    "id": str(uuid4()),
                    "strategy_id": strategy_id,
                    "signal_id": None,
                    "symbol": fill.symbol,
                    "action": _side_to_action(fill.side),
                    "quantity": str(fill.qty),
                    "price": str(fill.price),
                    "notional": str(fill.notional),
                    "fee": str(fill.fee),
                    "slippage": str(fill.slippage),
                    "avg_cost": (str(avg_cost_before) if avg_cost_before > _DECIMAL_ZERO else None),
                    "realized_pnl": str(realized_pnl),
                    "cumulative_pnl": str(t["cumulative_pnl"]),
                    "executed_at": fill.fill_time,
                    "bar_dt": fill.bar_dt,
                    "tag": fill.tag,
                }
            )

        return params_list
