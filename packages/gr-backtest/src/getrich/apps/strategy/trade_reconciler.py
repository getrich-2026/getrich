"""Trade reconciliation — backfill PnL columns in ``strategy_trades``.

When trades are first written (via ``record_execute()`` or
``BacktestTradeWriter``), buy-side trades have ``realized_pnl=0`` and
``avg_cost`` / ``cumulative_pnl`` may be ``NULL``.  This module provides
:func:`reconcile_trades` to recompute those columns using the AVCO
(average cost) method, matching the backtest attribution logic.

Usage::

    await reconcile_trades(strategy_id="...", conn=db)
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from gr_data.db.pool import PgConnectionPool, pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_DECIMAL_ZERO = Decimal("0")
_TWO_PLACES = Decimal("0.01")


def _fmt(d: Decimal) -> str:
    """Format a Decimal to 2 fixed decimal places for DB storage."""
    return str(d.quantize(_TWO_PLACES))


_SELECT_SQL = """
    SELECT id, symbol, action, quantity, price, notional, fee,
           executed_at
    FROM strategy_trades
    WHERE strategy_id = %(sid)s
    ORDER BY symbol, executed_at ASC
"""

_UPDATE_SQL = """
    UPDATE strategy_trades
    SET avg_cost = %(avg_cost)s,
        realized_pnl = %(realized_pnl)s,
        cumulative_pnl = %(cumulative_pnl)s,
        bar_dt = COALESCE(bar_dt, executed_at)
    WHERE id = %(id)s
"""

_AFFECTED_STRATEGIES_SQL = """
    SELECT DISTINCT strategy_id
    FROM strategy_trades
    WHERE cumulative_pnl IS NULL OR bar_dt IS NULL
"""

_BACKFILL_BAR_DT_FROM_SIGNALS_SQL = """
    UPDATE strategy_trades AS st
    SET bar_dt = s.published_at
    FROM signals AS s
    WHERE st.signal_id = s.id
      AND st.bar_dt IS NULL
      AND s.published_at IS NOT NULL
"""

_BACKFILL_BAR_DT_FROM_EXECUTED_AT_SQL = """
    UPDATE strategy_trades
    SET bar_dt = executed_at
    WHERE bar_dt IS NULL
"""


async def reconcile_trades(
    strategy_id: str,
    *,
    conn: AsyncConnection | None = None,
    pool: PgConnectionPool | None = None,
) -> int:
    """Recompute AVCO-based PnL for all trades of a strategy.

    Reads all trades ordered by ``(symbol, executed_at)``, applies the
    average-cost method per symbol, and UPDATEs ``avg_cost``,
    ``realized_pnl``, and ``cumulative_pnl`` on every row.

    Parameters
    ----------
    strategy_id : str
        Internal UUID of the strategy.
    conn : AsyncConnection | None
        Optional existing connection for transaction grouping.
    pool : PgConnectionPool | None
        Connection pool (default: global ``pg_pool``).

    Returns
    -------
    int
        Number of rows updated.
    """
    p = pool or pg_pool

    async def _do(c: AsyncConnection) -> int:
        # 1. Load all trades, ordered for AVCO
        async with c.cursor() as cur:
            await cur.execute(_SELECT_SQL, {"sid": strategy_id})
            rows = await cur.fetchall()

        if not rows:
            return 0

        # 2. AVCO per symbol (signed net_qty — handles long & short)
        updates: list[tuple[dict, str]] = []
        trackers: dict[str, dict[str, Decimal]] = {}

        for row in rows:
            sym = row["symbol"]
            if sym not in trackers:
                trackers[sym] = {
                    "net_qty": _DECIMAL_ZERO,
                    "total_cost": _DECIMAL_ZERO,
                    "cumulative_pnl": _DECIMAL_ZERO,
                }
            t = trackers[sym]

            qty = Decimal(str(row["quantity"]))
            price = Decimal(str(row["price"]))
            notional = Decimal(str(row["notional"]))
            action = row["action"]

            avg_cost_before = (
                t["total_cost"] / abs(t["net_qty"])
                if t["net_qty"] != _DECIMAL_ZERO
                else _DECIMAL_ZERO
            )
            realized_pnl = _DECIMAL_ZERO

            if action == "buy":
                if t["net_qty"] >= _DECIMAL_ZERO:
                    # Adding to long — no PnL.
                    t["net_qty"] += qty
                    t["total_cost"] += notional
                else:
                    # Covering short.
                    cover_qty = min(qty, -t["net_qty"])
                    realized_pnl = (avg_cost_before - price) * cover_qty
                    t["cumulative_pnl"] += realized_pnl
                    t["net_qty"] += cover_qty
                    if t["net_qty"] < _DECIMAL_ZERO:
                        t["total_cost"] = avg_cost_before * (-t["net_qty"])
                    else:
                        t["total_cost"] = _DECIMAL_ZERO
                    excess = qty - cover_qty
                    if excess > _DECIMAL_ZERO:
                        t["net_qty"] += excess
                        t["total_cost"] += price * excess
            elif action == "sell":
                if t["net_qty"] > _DECIMAL_ZERO:
                    # Selling from long.
                    sell_qty = min(qty, t["net_qty"])
                    realized_pnl = (price - avg_cost_before) * sell_qty
                    t["cumulative_pnl"] += realized_pnl
                    t["net_qty"] -= sell_qty
                    if t["net_qty"] > _DECIMAL_ZERO:
                        t["total_cost"] = avg_cost_before * t["net_qty"]
                    else:
                        t["total_cost"] = _DECIMAL_ZERO
                    excess = qty - sell_qty
                    if excess > _DECIMAL_ZERO:
                        t["net_qty"] -= excess
                        t["total_cost"] = price * excess
                else:
                    # Adding to short — no PnL.
                    t["net_qty"] -= qty
                    t["total_cost"] += notional

            updates.append(
                (
                    {
                        "avg_cost": (
                            _fmt(avg_cost_before) if avg_cost_before > _DECIMAL_ZERO else None
                        ),
                        "realized_pnl": _fmt(realized_pnl),
                        "cumulative_pnl": _fmt(t["cumulative_pnl"]),
                        "id": row["id"],
                    },
                    row["id"],
                )
            )

        # 3. UPDATE all rows
        updated = 0
        async with c.cursor() as cur:
            for params, _ in updates:
                await cur.execute(_UPDATE_SQL, params)
                updated += 1

        return updated

    if conn is not None:
        return await _do(conn)

    async with p.connection() as c:
        updated = await _do(c)
        await c.commit()
    return updated


async def backfill_trade_gaps(
    *,
    conn: AsyncConnection | None = None,
    pool: PgConnectionPool | None = None,
) -> int:
    """Backfill live trade gaps and reconcile affected strategies.

    Repairs missing ``bar_dt`` first, then runs AVCO reconciliation for
    strategies whose trades have missing ``cumulative_pnl`` or ``bar_dt``.
    Opening trades may legitimately keep ``avg_cost`` as ``NULL``, so that
    column is not used to detect unreconciled rows.
    """
    p = pool or pg_pool

    async def _do(c: AsyncConnection) -> int:
        async with c.cursor() as cur:
            await cur.execute(_AFFECTED_STRATEGIES_SQL)
            rows = await cur.fetchall()

        strategy_ids = [str(row["strategy_id"]) for row in rows]
        if not strategy_ids:
            return 0

        async with c.cursor() as cur:
            await cur.execute(_BACKFILL_BAR_DT_FROM_SIGNALS_SQL)
            await cur.execute(_BACKFILL_BAR_DT_FROM_EXECUTED_AT_SQL)

        updated = 0
        for strategy_id in strategy_ids:
            updated += await reconcile_trades(strategy_id, conn=c)
        return updated

    if conn is not None:
        return await _do(conn)

    async with p.connection() as c:
        updated = await _do(c)
        await c.commit()
    return updated
