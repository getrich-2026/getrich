"""Tests for ``get_equity_curve``.

`services.strategy.get_equity_curve` powers
``GET /strategies/{code}/equity-curve``. The function builds a
``WHERE strategy_id = %(sid)s`` filter, optionally derives a
``start_date`` from a named ``period`` (``1m`` → 30 days back, etc.),
and produces a denormalized response with three parallel arrays:

- ``equity_curve`` — every row's `nav`/`cumulative_return`/...
- ``benchmark_curve`` — only rows where `benchmark_nav` is non-null
  (the benchmark series is sparsely populated, often NaN at the start
  of a backtest before the index data is available)
- ``drawdown_curve`` — only rows where `drawdown` is non-null

The benchmark and drawdown arrays are also opt-out via
``include_benchmark=False`` / ``include_drawdown=False`` to keep the
payload small for the dashboard view.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from getrich.apps.web.errors import BadRequest
from getrich.apps.web.services.strategy import get_equity_curve


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


def _ec_row(
    *,
    trade_date: date,
    nav: float = 1.0,
    cumulative_return: float = 0.0,
    daily_return: float | None = 0.0,
    drawdown: float | None = 0.0,
    benchmark_nav: float | None = 1.0,
    position_ratio: float | None = 1.0,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "nav": nav,
        "cumulative_return": cumulative_return,
        "daily_return": daily_return,
        "drawdown": drawdown,
        "benchmark_nav": benchmark_nav,
        "position_ratio": position_ratio,
    }


# ---------------------------------------------------------------------------
# get_equity_curve
# ---------------------------------------------------------------------------


async def test_get_equity_curve_rejects_invalid_period() -> None:
    """A `period` outside the whitelist → BadRequest before any SQL.
    This guards against a future refactor that interpolates `period`
    into a date arithmetic expression (SQLi)."""
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)

    with pytest.raises(BadRequest):
        await get_equity_curve(
            conn,  # type: ignore[arg-type]
            strategy_id="strat-uuid",
            strategy_code="STR_FUT_001",
            period="bogus",
            start_date=None,
            end_date=None,
            include_benchmark=True,
            include_drawdown=True,
        )

    assert cursor.executed == []


async def test_get_equity_curve_no_period_no_dates_uses_no_window() -> None:
    """Without `period` AND without explicit `start_date`/`end_date`,
    the WHERE clause is just `strategy_id = %(sid)s` — no extra
    date filter is added."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    sql, params = cursor.executed[0]
    assert "strategy_id = %(sid)s" in sql
    assert "start" not in params
    assert "end" not in params


async def test_get_equity_curve_period_all_does_not_add_window() -> None:
    """`period="all"` is the "give me everything" sentinel. The
    service contract: `_PERIOD_DAYS["all"] = None` so the
    start_date derivation short-circuits and the WHERE stays
    unfiltered by date."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period="all",
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    _, params = cursor.executed[0]
    assert "start" not in params
    assert "end" not in params


@pytest.mark.parametrize(
    ("period", "expected_days"),
    [("1m", 30), ("3m", 90), ("6m", 180), ("1y", 365), ("3y", 365 * 3)],
)
async def test_get_equity_curve_period_maps_to_lookback_days(
    period: str, expected_days: int
) -> None:
    """Each named period translates to the documented lookback
    window. Guards against a refactor that re-points "1m" to 60
    days or "3y" to 2 years."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=period,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    _, params = cursor.executed[0]
    expected_start = date.today().toordinal() - expected_days
    assert date.fromordinal(expected_start) == params["start"]


async def test_get_equity_curve_explicit_start_date_overrides_period() -> None:
    """If the caller passes both `period` AND `start_date`, the
    explicit `start_date` wins. The `period` is silently ignored
    (still a no-arg BadRequest check, but no window derivation)."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    explicit = date(2026, 1, 1)
    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period="1y",
        start_date=explicit,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    _, params = cursor.executed[0]
    assert params["start"] == explicit


async def test_get_equity_curve_end_date_passthrough() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=date(2026, 6, 30),
        include_benchmark=True,
        include_drawdown=True,
    )

    sql, params = cursor.executed[0]
    assert "trade_date <= %(end)s" in sql
    assert params["end"] == date(2026, 6, 30)


async def test_get_equity_curve_both_dates() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        include_benchmark=True,
        include_drawdown=True,
    )

    sql, params = cursor.executed[0]
    assert "trade_date >= %(start)s" in sql
    assert "trade_date <= %(end)s" in sql
    assert params["start"] == date(2026, 1, 1)
    assert params["end"] == date(2026, 6, 30)


async def test_get_equity_curve_serializes_main_curve() -> None:
    """The `equity_curve` array maps every row to the public schema
    (date as ISO string, all numerics as float)."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(
                trade_date=date(2026, 6, 1),
                nav=1.05,
                cumulative_return=0.05,
                daily_return=0.01,
                position_ratio=0.8,
            ),
            _ec_row(
                trade_date=date(2026, 6, 2),
                nav=1.07,
                cumulative_return=0.07,
                daily_return=0.019,
                position_ratio=0.85,
            ),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    assert result["strategy_id"] == "STR_FUT_001"
    assert result["total_points"] == 2
    assert result["equity_curve"] == [
        {
            "date": "2026-06-01",
            "nav": 1.05,
            "cumulative_return": 0.05,
            "daily_return": 0.01,
            "position_ratio": 0.8,
        },
        {
            "date": "2026-06-02",
            "nav": 1.07,
            "cumulative_return": 0.07,
            "daily_return": 0.019,
            "position_ratio": 0.85,
        },
    ]


async def test_get_equity_curve_benchmark_skips_null_rows() -> None:
    """`benchmark_curve` is the sparse subset of rows where
    `benchmark_nav` is non-null. Rows with NULL benchmark data
    (typically the first few days of a backtest before the index
    is available) MUST be skipped — the chart would render
    false zeros otherwise."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2026, 6, 1), benchmark_nav=None),
            _ec_row(trade_date=date(2026, 6, 2), benchmark_nav=1.02),
            _ec_row(trade_date=date(2026, 6, 3), benchmark_nav=1.03),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    # Total points = all 3 rows, but benchmark only has 2.
    assert result["total_points"] == 3
    assert len(result["benchmark_curve"]) == 2
    assert result["benchmark_curve"][0]["date"] == "2026-06-02"
    assert result["benchmark_curve"][0]["nav"] == 1.02
    assert result["benchmark_curve"][1]["date"] == "2026-06-03"


async def test_get_equity_curve_drawdown_skips_null_rows() -> None:
    """Same skip rule for `drawdown_curve` — only rows where
    `drawdown` is non-null."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2026, 6, 1), drawdown=0.0),
            _ec_row(trade_date=date(2026, 6, 2), drawdown=None),
            _ec_row(trade_date=date(2026, 6, 3), drawdown=-0.05),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    assert len(result["drawdown_curve"]) == 2
    assert result["drawdown_curve"][0]["date"] == "2026-06-01"
    assert result["drawdown_curve"][0]["drawdown"] == 0.0
    assert result["drawdown_curve"][1]["drawdown"] == -0.05


async def test_get_equity_curve_include_benchmark_false_returns_empty() -> None:
    """`include_benchmark=False` short-circuits the entire
    benchmark output regardless of row data — useful for the
    dashboard view that just needs the strategy's own curve."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2026, 6, 1), benchmark_nav=1.02),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=False,
        include_drawdown=True,
    )

    assert result["benchmark_curve"] == []
    # Main curve still populated.
    assert len(result["equity_curve"]) == 1


async def test_get_equity_curve_include_drawdown_false_returns_empty() -> None:
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2026, 6, 1), drawdown=0.0),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=False,
    )

    assert result["drawdown_curve"] == []
    assert len(result["equity_curve"]) == 1


async def test_get_equity_curve_both_flags_off_main_curve_still_returned() -> None:
    """Both flags off → only the main equity curve. A common
    pattern for the small dashboard widget."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2026, 6, 1)),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=False,
        include_drawdown=False,
    )

    assert len(result["equity_curve"]) == 1
    assert result["benchmark_curve"] == []
    assert result["drawdown_curve"] == []


async def test_get_equity_curve_period_window_uses_first_row_window() -> None:
    """The response's `period.start` and `period.end` are derived
    from the first/last row in the result set, NOT from the
    requested window. If the user asked for "1y" but the table
    only has 6 months of data, `period.end` is the latest row's
    date, not today's date."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _ec_row(trade_date=date(2025, 1, 1)),
            _ec_row(trade_date=date(2025, 12, 31)),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period="1y",
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    assert result["period"] == {
        "start": "2025-01-01",
        "end": "2025-12-31",
    }


async def test_get_equity_curve_empty_result_period_is_empty_string() -> None:
    """When the SELECT returns no rows, `period.start` and
    `period.end` are both empty strings (the service uses
    `rows[0]` / `rows[-1]` which don't exist). The frontend
    renders an empty-state placeholder."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_equity_curve(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
        period=None,
        start_date=None,
        end_date=None,
        include_benchmark=True,
        include_drawdown=True,
    )

    assert result["equity_curve"] == []
    assert result["total_points"] == 0
    assert result["period"] == {"start": "", "end": ""}
