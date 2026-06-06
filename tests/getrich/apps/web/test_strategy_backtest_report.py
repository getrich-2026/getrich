"""Tests for ``get_backtest_report``.

`services.strategy.get_backtest_report` powers
``GET /strategies/{code}/backtest-report``. It runs **3 SQL
queries** in sequence and merges them into a denormalized
response with four top-level sections:

- ``summary`` — strategy metadata + key performance metrics
  (total_return, annualized_return, max_drawdown, sharpe, ...)
- ``risk_analysis`` — VaR / CVaR / beta / alpha / max single-day
  gain & loss
- ``trade_analysis`` — total_trades / win_rate / avg_trade_return
  / avg_holding_days / profit_factor
- ``annual_performance`` — per-year compound return derived from
  monthly returns via ``EXP(SUM(LN(1 + r))) - 1``

The main SELECT uses a ``LEFT JOIN LATERAL (SELECT ... LIMIT 1)``
to fetch the *latest* `strategy_performance_snapshot` for the
strategy. The two follow-up SELECTs are independent:
``strategy_equity_curve`` (for max single-day gain/loss) and
``strategy_monthly_returns`` (aggregated to yearly).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from getrich.apps.web.errors import NotFound
from getrich.apps.web.services.strategy import get_backtest_report


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. The service issues 3 queries, so we use
    a queue of `fetchone`/`fetchall` results that the test can
    pre-load.

    - 1st execute: main SELECT → 1 `fetchone`
    - 2nd execute: ec MIN/MAX → 1 `fetchone`
    - 3rd execute: annual_performance → 1 `fetchall`
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_q:
            return self._fetchone_q.pop(0)
        return None

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    def push_one(self, row: dict[str, Any] | None) -> None:
        """Queue a `fetchone` response for the NEXT call."""
        self._fetchone_q.append(row)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Queue a `fetchall` response for the NEXT call."""
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _main_row(
    *,
    backtest_start: date | None = date(2024, 1, 1),
    backtest_end: date | None = date(2024, 12, 31),
    total_return: float | None = 0.30,
    annualized_return: float | None = 0.30,
    max_drawdown: float | None = 0.10,
    max_drawdown_start: date | None = date(2024, 6, 1),
    max_drawdown_end: date | None = date(2024, 7, 15),
    max_drawdown_recovery: date | None = date(2024, 9, 1),
    sharpe_ratio: float | None = 1.5,
    var_95: float | None = -0.025,
    cvar_95: float | None = -0.035,
    beta: float | None = 0.8,
    alpha: float | None = 0.02,
    total_trades: int | None = 200,
    win_rate: float | None = 0.55,
    profit_factor: float | None = 1.8,
    avg_win: float | None = 0.025,
    avg_loss: float | None = -0.015,
    avg_holding_days: float | None = 5.0,
) -> dict[str, Any]:
    return {
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "max_drawdown_start": max_drawdown_start,
        "max_drawdown_end": max_drawdown_end,
        "max_drawdown_recovery": max_drawdown_recovery,
        "sharpe_ratio": sharpe_ratio,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "beta": beta,
        "alpha": alpha,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_holding_days": avg_holding_days,
    }


def _ec_row(
    *,
    max_loss: float | None = -0.05,
    max_gain: float | None = 0.04,
) -> dict[str, Any] | None:
    if max_loss is None and max_gain is None:
        return None
    return {"max_loss": max_loss, "max_gain": max_gain}


def _annual_row(
    *, year: int, yearly_return: float | None = 0.10, months_present: int = 12
) -> dict[str, Any]:
    return {
        "year": year,
        "yearly_return": yearly_return,
        "months_present": months_present,
    }


# ---------------------------------------------------------------------------
# get_backtest_report
# ---------------------------------------------------------------------------


async def test_get_backtest_report_raises_not_found_when_strategy_missing() -> None:
    """The main SELECT returning no row → NotFound (eventually).
    Note: the service runs all 3 SELECTs in a single cursor block,
    so the ec and annual aggregations ALSO issue against the
    missing strategy_id. The NotFound is raised AFTER consuming
    all rows but BEFORE the output dict is built — so the
    response isn't emitted. (A tighter optimization would short-
    circuit after the main SELECT, but that's a follow-up.)"""
    cursor = _FakeCursor()
    cursor.push_one(None)  # main SELECT → no strategy
    cursor.push_one(None)  # ec → no row (defensive)
    cursor.set_rows([])  # annual → no rows (defensive)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await get_backtest_report(
            conn,  # type: ignore[arg-type]
            strategy_id="strat-uuid-missing",
            strategy_code="STR_MISSING",
        )

    # All 3 SELECTs ran; the NotFound was raised on the row check.
    assert len(cursor.executed) == 3


async def test_get_backtest_report_issues_three_queries() -> None:
    """The service issues 3 SELECTs in a single cursor block:
    1) main + LATERAL snapshot
    2) equity_curve MIN/MAX
    3) monthly returns aggregated to yearly
    """
    cursor = _FakeCursor()
    cursor.push_one(_main_row())  # main
    cursor.push_one(_ec_row())  # ec
    cursor.set_rows([])  # annual
    conn = _FakeConn(cursor)

    await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert len(cursor.executed) == 3
    main_sql, _ = cursor.executed[0]
    assert "LEFT JOIN LATERAL" in main_sql
    assert "strategy_performance_snapshot" in main_sql
    assert "ORDER BY snapshot_date DESC" in main_sql

    ec_sql, _ = cursor.executed[1]
    assert "MIN(daily_return)" in ec_sql
    assert "MAX(daily_return)" in ec_sql
    assert "strategy_equity_curve" in ec_sql

    annual_sql, _ = cursor.executed[2]
    assert "strategy_monthly_returns" in annual_sql
    assert "EXP(SUM(LN(1 + monthly_return))) - 1" in annual_sql
    assert "GROUP BY year" in annual_sql


async def test_get_backtest_report_summary_section() -> None:
    """The `summary` block maps all main-row fields to the public
    schema (ISO dates, float numerics, computed `final_capital`)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    s = result["summary"]
    assert s["backtest_start"] == "2024-01-01"
    assert s["backtest_end"] == "2024-12-31"
    assert s["total_return"] == 0.30
    assert s["annualized_return"] == 0.30
    assert s["max_drawdown"] == 0.10
    assert s["max_drawdown_start"] == "2024-06-01"
    assert s["max_drawdown_end"] == "2024-07-15"
    assert s["max_drawdown_recovery"] == "2024-09-01"
    assert s["sharpe_ratio"] == 1.5


async def test_get_backtest_report_initial_capital_is_1m_constant() -> None:
    """`initial_capital` is hard-coded to 1,000,000.0 (the
    service has a comment about this: `config 字段未拆分`).
    `final_capital` is `initial * (1 + total_return)` — the
    simple end-vs-start comparison, not the compound formula
    (no daily-resampling here)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(total_return=0.30))
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["summary"]["initial_capital"] == 1_000_000.0
    assert result["summary"]["final_capital"] == 1_300_000.0


async def test_get_backtest_report_final_capital_handles_null_total_return() -> None:
    """When `total_return` is NULL (no snapshot yet), the
    service's `_f` helper turns it into 0.0 and the
    `final_capital` falls back to `initial * 1.0 = initial`
    (not 0 or `None`)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(total_return=None))
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["summary"]["total_return"] == 0.0
    assert result["summary"]["final_capital"] == 1_000_000.0


async def test_get_backtest_report_risk_analysis_section() -> None:
    """The `risk_analysis` block surfaces VaR / CVaR / beta /
    alpha from the main row, plus max single-day gain/loss
    from the equity-curve aggregation."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(var_95=-0.025, cvar_95=-0.035, beta=0.8, alpha=0.02))
    cursor.push_one(_ec_row(max_loss=-0.05, max_gain=0.04))
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    r = result["risk_analysis"]
    assert r["var_95"] == -0.025
    assert r["cvar_95"] == -0.035
    assert r["beta"] == 0.8
    assert r["alpha"] == 0.02
    assert r["max_single_day_loss"] == -0.05
    assert r["max_single_day_gain"] == 0.04


async def test_get_backtest_report_risk_analysis_ec_row_null_defaults_to_zero() -> None:
    """When the equity-curve MIN/MAX returns no row (the
    `strategy_equity_curve` table is empty), `max_loss` /
    `max_gain` default to 0.0 rather than crashing. The
    `ec_row["max_loss"]` is the result of `MIN(daily_return)`
    which is NULL when there are no rows; the service's
    `if ec_row else 0.0` guard handles this."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.push_one(None)  # ec → no row
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    r = result["risk_analysis"]
    assert r["max_single_day_loss"] == 0.0
    assert r["max_single_day_gain"] == 0.0


async def test_get_backtest_report_trade_analysis_section() -> None:
    """The `trade_analysis` block surfaces the trade-journal
    fields from the main row, with `total_trades` coerced to
    int and `avg_trade_return` reading from `avg_win` (a known
    service quirk — `avg_trade_return` is actually the
    average winning trade return, not the average of all
    trades; documented in the source)."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            total_trades=200,
            win_rate=0.55,
            avg_win=0.025,
            avg_holding_days=5.0,
            profit_factor=1.8,
        )
    )
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    t = result["trade_analysis"]
    assert t["total_trades"] == 200
    assert t["win_rate"] == 0.55
    assert t["avg_trade_return"] == 0.025
    assert t["avg_holding_days"] == 5.0
    assert t["profit_factor"] == 1.8


async def test_get_backtest_report_trade_analysis_handles_null_total_trades() -> None:
    """`total_trades` NULL → int 0 (the `int(... or 0)` guard)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(total_trades=None))
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["trade_analysis"]["total_trades"] == 0


async def test_get_backtest_report_annual_performance_section() -> None:
    """`annual_performance` is a list of `{year, return,
    max_drawdown, sharpe, trades}`. The `return` field is the
    aggregated yearly_return from the SQL. The other three
    fields are hard-coded to 0 (the service's comment notes
    the schema doesn't track per-year aggregations yet)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.push_one(_ec_row())
    cursor.set_rows(
        [
            _annual_row(year=2023, yearly_return=0.10),
            _annual_row(year=2024, yearly_return=0.20),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    ap = result["annual_performance"]
    assert len(ap) == 2
    assert ap[0] == {
        "year": 2023,
        "return": 0.10,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "trades": 0,
    }
    assert ap[1]["year"] == 2024
    assert ap[1]["return"] == 0.20


async def test_get_backtest_report_annual_performance_empty() -> None:
    """No monthly data → empty annual_performance list. The
    frontend renders the empty-state placeholder."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.push_one(_ec_row())
    cursor.set_rows([])  # no annual rows
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["annual_performance"] == []


async def test_get_backtest_report_strategy_id_is_human_code() -> None:
    """The response's `strategy_id` is the human-facing code,
    not the UUID. Same contract as the other strategy read
    endpoints."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["strategy_id"] == "STR_FUT_001"
    assert "strat-uuid-1" not in result["strategy_id"]


async def test_get_backtest_report_handles_null_dates_as_empty_string() -> None:
    """When `backtest_start` / `backtest_end` are NULL (e.g.
    a brand-new strategy that hasn't been backtested yet),
    the dates serialize to empty strings rather than
    crashing the `date.isoformat()` call. The frontend renders
    "—"."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(backtest_start=None, backtest_end=None))
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["summary"]["backtest_start"] == ""
    assert result["summary"]["backtest_end"] == ""


async def test_get_backtest_report_handles_null_max_drawdown_dates() -> None:
    """`max_drawdown_start` / `max_drawdown_end` /
    `max_drawdown_recovery` are NULL when the strategy never
    had a drawdown (all positive returns). They serialize to
    empty strings — same `date.isoformat()` guard."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            max_drawdown_start=None,
            max_drawdown_end=None,
            max_drawdown_recovery=None,
        )
    )
    cursor.push_one(_ec_row())
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_backtest_report(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        strategy_code="STR_FUT_001",
    )

    assert result["summary"]["max_drawdown_start"] == ""
    assert result["summary"]["max_drawdown_end"] == ""
    assert result["summary"]["max_drawdown_recovery"] == ""
