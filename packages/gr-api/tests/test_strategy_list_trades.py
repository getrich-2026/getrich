"""Tests for ``list_trades``.

`services.strategy.list_trades` powers
``GET /strategies/{code}/trades``. It pulls from the
``strategy_trades`` table and produces a denormalized list where
each row has ISO-formatted datetimes and nullable ``avg_cost`` /
``cumulative_pnl`` fields preserved as ``None`` (not 0.0 —
0.0 has financial meaning here: "the trade had no cost" vs.
"the cost was missing").

The query has four orthogonal filters:

- ``start_date`` inclusive (``executed_at >= %(start)s``)
- ``end_date`` **exclusive** on the next day (``executed_at <
  (%(end)s::date + INTERVAL '1 day')``) — so ``end_date=2026-06-30``
  includes trades executed on June 30
- ``action`` (``buy`` / ``sell``) with ``"all"`` as a "no filter"
  sentinel
- ``result`` (``win`` → ``realized_pnl > 0``, ``loss`` →
  ``realized_pnl < 0``) with ``"all"`` as a sentinel
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from gr_api.services.strategy import list_trades


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `set_rows` queues a `fetchall` response."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple]] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    async def fetchone(self):  # pragma: no cover
        return None

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _Page:
    def __init__(self, limit: int = 20, offset: int = 0) -> None:
        self.limit = limit
        self.offset = offset


def _trade_row(
    *,
    id: str = "trade-uuid-1",
    strategy_id: str = "strat-uuid-1",
    signal_id: str | None = "sig-uuid-1",
    symbol: str = "rb2410",
    action: str = "buy",
    quantity: float = 1.0,
    price: float = 3500.0,
    notional: float = 3500.0,
    fee: float = 3.5,
    slippage: float = 1.0,
    avg_cost: float | None = 3490.0,
    realized_pnl: float | None = 100.0,
    cumulative_pnl: float | None = 250.0,
    executed_at: datetime | None = None,
    bar_dt: datetime | None = None,
    tag: str | None = "open",
    total_count: int = 1,
) -> dict[str, Any]:
    return {
        "id": id,
        "strategy_id": strategy_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
        "notional": notional,
        "fee": fee,
        "slippage": slippage,
        "avg_cost": avg_cost,
        "realized_pnl": realized_pnl,
        "cumulative_pnl": cumulative_pnl,
        "executed_at": executed_at or datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
        "bar_dt": bar_dt,
        "tag": tag,
        "_total": total_count,
    }


# ---------------------------------------------------------------------------
# list_trades
# ---------------------------------------------------------------------------


async def test_list_trades_strategy_id_always_in_where() -> None:
    """`strategy_id` is the tenant key — it MUST be in the WHERE
    clause unconditionally to prevent cross-strategy data leaks."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "WHERE strategy_id = %(sid)s" in sql
    assert params["sid"] == "strat-uuid-1"


async def test_list_trades_empty_result_returns_empty_tuple() -> None:
    """No rows → ([], 0). Avoids IndexError on the
    `rows[0]["_total"]` access in the service."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    items, total = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items == []
    assert total == 0


async def test_list_trades_pagination_params() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(limit=50, offset=200),
    )

    params = cursor.executed[0][1]
    assert params["limit"] == 50
    assert params["offset"] == 200


async def test_list_trades_start_date_inclusive() -> None:
    """`start_date` uses ``>=`` so the date itself is included."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=date(2026, 6, 1),
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "executed_at >= %(start)s" in sql
    assert params["start"] == date(2026, 6, 1)


async def test_list_trades_end_date_exclusive_next_day() -> None:
    """`end_date` is exclusive of the *next* day, not the date
    itself — so `end_date=2026-06-30` includes trades on
    2026-06-30 23:59:59. The trick is the
    `executed_at < (%(end)s::date + INTERVAL '1 day')` cast which
    shifts the upper bound to 2026-07-01 00:00:00. This avoids
    the off-by-one where the caller passes the last day of the
    month and silently loses it.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=date(2026, 6, 30),
        action=None,
        result=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "< (%(end)s::date + INTERVAL '1 day')" in sql
    assert params["end"] == date(2026, 6, 30)


async def test_list_trades_action_filter_specific_value() -> None:
    """`action='buy'` (or `'sell'`) adds an equality predicate.
    The frontend uses this to split "open positions" from
    "close positions" tabs in the trade journal."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action="buy",
        result=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "action = %(action)s" in sql
    assert params["action"] == "buy"


async def test_list_trades_action_all_sentinel_passes_through() -> None:
    """`action='all'` is the frontend's "no filter" sentinel.
    The service skips the WHERE clause addition via the
    `action != "all"` guard, matching the route's Pydantic
    pattern."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action="all",
        result=None,
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "action = %(action)s" not in sql
    assert "action" not in params


async def test_list_trades_result_win_filter() -> None:
    """`result='win'` translates to ``realized_pnl > 0`` — strictly
    positive (zero-PnL trades are not "wins", they're break-even)."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result="win",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "realized_pnl > 0" in sql


async def test_list_trades_result_loss_filter() -> None:
    """`result='loss'` translates to ``realized_pnl < 0`` —
    strictly negative."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result="loss",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "realized_pnl < 0" in sql


async def test_list_trades_result_all_sentinel_passes_through() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result="all",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    # The SELECT clause lists `realized_pnl` (output field), but no
    # `realized_pnl` PREDICATE is added to the WHERE for the
    # "all" sentinel — i.e. `realized_pnl > 0` / `< 0` are absent.
    assert "realized_pnl > 0" not in sql
    assert "realized_pnl < 0" not in sql


async def test_list_trades_serializes_datetimes_to_iso() -> None:
    """`executed_at` and `bar_dt` are both ISO-stringified when
    present. `bar_dt` is nullable; if NULL, the output field is
    `None` (not an empty string) so the frontend can render a
    "— (intra-bar fill)" placeholder."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(
                executed_at=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
                bar_dt=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["executed_at"] == "2026-06-01T09:30:00+00:00"
    assert items[0]["bar_dt"] == "2026-06-01T09:00:00+00:00"


async def test_list_trades_bar_dt_none_stays_none() -> None:
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(bar_dt=None),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["bar_dt"] is None


async def test_list_trades_avg_cost_none_stays_none() -> None:
    """`avg_cost` is nullable: an opening trade has no
    `avg_cost` (the cost basis is undefined until the position
    is closed). The service uses `_f_nullable` so the field
    stays `None` rather than defaulting to 0.0 — 0.0 here would
    be wrong (a trade with a $0 cost basis is not a real
    thing in the platform's financial model)."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(avg_cost=None),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["avg_cost"] is None


async def test_list_trades_cumulative_pnl_none_stays_none() -> None:
    """Same NULL-preserving contract for `cumulative_pnl` — the
    first trade has no prior PnL to accumulate from."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(cumulative_pnl=None),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["cumulative_pnl"] is None


async def test_list_trades_tag_none_becomes_empty_string() -> None:
    """Unlike `avg_cost` / `cumulative_pnl`, the `tag` field is
    a non-financial note (e.g. "open", "stop_loss") that the
    frontend renders as a chip. NULL tags collapse to "" so
    the frontend doesn't have to handle `null` separately —
    matches the service's `r["tag"] or ""` line."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(tag=None),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["tag"] == ""


async def test_list_trades_signal_id_none_stays_none() -> None:
    """A trade without an originating signal (e.g. a manually-
    submitted order from the admin) has `signal_id=NULL`. The
    service preserves this as `None` in the output."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(signal_id=None),
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert items[0]["signal_id"] is None


async def test_list_trades_serializes_output_schema() -> None:
    """The output dict has the full public schema (snake_case
    keys, ISO datetimes, strategy_id as str, not UUID)."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _trade_row(
                id="trade-uuid-1",
                strategy_id="strat-uuid-1",
                signal_id="sig-uuid-1",
                symbol="rb2410",
                action="buy",
                quantity=1.0,
                price=3500.0,
                notional=3500.0,
                fee=3.5,
                slippage=1.0,
                avg_cost=3490.0,
                realized_pnl=100.0,
                cumulative_pnl=250.0,
                tag="open",
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, total = await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    assert total == 1
    item = items[0]
    assert item["id"] == "trade-uuid-1"
    assert item["strategy_id"] == "strat-uuid-1"
    assert item["signal_id"] == "sig-uuid-1"
    assert item["symbol"] == "rb2410"
    assert item["action"] == "buy"
    assert item["quantity"] == 1.0
    assert item["price"] == 3500.0
    assert item["notional"] == 3500.0
    assert item["fee"] == 3.5
    assert item["slippage"] == 1.0
    assert item["avg_cost"] == 3490.0
    assert item["realized_pnl"] == 100.0
    assert item["cumulative_pnl"] == 250.0
    assert item["tag"] == "open"


async def test_list_trades_combines_all_filters() -> None:
    """All four filter values are passed to params simultaneously.
    Guards against an accidental refactor that drops one of the
    conds entries (e.g. when adding a new filter)."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        action="buy",
        result="win",
        page=_Page(),
    )

    sql, params = cursor.executed[0]
    assert "strategy_id = %(sid)s" in sql
    assert "executed_at >= %(start)s" in sql
    assert "< (%(end)s::date + INTERVAL '1 day')" in sql
    assert "action = %(action)s" in sql
    assert "realized_pnl > 0" in sql
    assert params["start"] == date(2026, 1, 1)
    assert params["end"] == date(2026, 6, 30)
    assert params["action"] == "buy"


async def test_list_trades_ordered_by_executed_at_desc() -> None:
    """Most recent trades first — the standard pattern for
    trade journal / activity feed UIs."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_trades(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
        start_date=None,
        end_date=None,
        action=None,
        result=None,
        page=_Page(),
    )

    sql = cursor.executed[0][0]
    assert "ORDER BY executed_at DESC" in sql
