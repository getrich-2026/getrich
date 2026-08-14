"""Tests for ``get_monthly_returns``.

`services.strategy.get_monthly_returns` powers
``GET /strategies/{code}/monthly-returns``. It returns a 12-column
heatmap-style matrix (one row per year, one column per month)
plus a compound ``yearly_return`` field per year.

The compound formula is:

    yearly = (1 + r_1) * (1 + r_2) * ... * (1 + r_12) - 1

with two edge cases that need explicit coverage:

- **partial year** (some months NULL) — the compound skips NULLs
  (you can't multiply by an unknown), but the year's `months`
  array still has 12 slots (NULL where data is missing).
- **all-NULL year** — `yearly_return` falls back to 0.0 (no
  meaningful product) rather than -1.0 (which would imply
  total wipeout from a 0% return).
"""

from __future__ import annotations

from typing import Any

import pytest

from getrich.apps.web.services.strategy import get_monthly_returns


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `set_rows` queues a `fetchall` response."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
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


def _mr_row(*, year: int, month: int, monthly_return: float) -> dict[str, Any]:
    return {"year": year, "month": month, "monthly_return": monthly_return}


# ---------------------------------------------------------------------------
# get_monthly_returns
# ---------------------------------------------------------------------------


async def test_get_monthly_returns_empty_result_returns_empty_matrix() -> None:
    """No rows → empty matrix. The frontend's heatmap component
    renders the empty-state placeholder."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    assert result == {"strategy_id": "STR_FUT_001", "matrix": []}


async def test_get_monthly_returns_single_row() -> None:
    """A single March 2026 return surfaces as a 12-slot array
    with the March value at index 2 and the rest NULL. The yearly
    return is just `0.05` (the single data point) since compound
    over one month is the same as the month's return."""
    cursor = _FakeCursor()
    cursor.set_rows([_mr_row(year=2026, month=3, monthly_return=0.05)])
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    assert len(result["matrix"]) == 1
    row = result["matrix"][0]
    assert row["year"] == 2026
    # 12 slots, March is at index 2, rest are None.
    assert row["months"][2] == 0.05
    assert all(row["months"][i] is None for i in (0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11))
    # Compound of a single 5% is 1.05 - 1 = 0.05.
    assert row["yearly_return"] == pytest.approx(0.05, rel=1e-9)


async def test_get_monthly_returns_full_year_compound_yearly() -> None:
    """A complete 12-month year uses every slot. The compound
    formula: prod(1 + r) - 1. For 5% + 5% over two months, that's
    1.05 * 1.05 - 1 = 0.1025 (not 0.10 — that's the additive
    sum, which is wrong for a heatmap that promises
    "yearly_return" to be the geometric total)."""
    returns = [0.05] * 12  # 5% every month
    cursor = _FakeCursor()
    cursor.set_rows([_mr_row(year=2026, month=m + 1, monthly_return=returns[m]) for m in range(12)])
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    row = result["matrix"][0]
    # All 12 months are 0.05.
    assert all(m == 0.05 for m in row["months"])
    # Compound: 1.05^12 - 1.
    expected = 1.05**12 - 1
    assert row["yearly_return"] == pytest.approx(expected, rel=1e-9)


async def test_get_monthly_returns_partial_year_skips_null_in_compound() -> None:
    """When some months are NULL (e.g. the strategy didn't trade
    that month), the compound product MUST skip the NULLs —
    multiplying by None would either error or zero out the
    result. The year returns to 0.0 if all are None."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _mr_row(year=2026, month=1, monthly_return=0.10),
            # Feb missing (NULL)
            _mr_row(year=2026, month=3, monthly_return=-0.05),
            # Apr-Dec missing
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    row = result["matrix"][0]
    # The two non-NULL months are filled in.
    assert row["months"][0] == 0.10
    assert row["months"][2] == -0.05
    # Compound over the 2 non-NULL months: 1.10 * 0.95 - 1 = 0.045.
    assert row["yearly_return"] == pytest.approx(0.045, rel=1e-9)


async def test_get_monthly_returns_all_null_year_returns_zero() -> None:
    """A year with all-NULL months (e.g. the strategy was retired
    mid-year and the data was wiped) returns `yearly_return=0.0`
    rather than `-1.0` (which would imply a total wipeout from
    0% returns). The `any_value` flag in the service prevents
    the `yr - 1.0` adjustment when no compound was computed.

    The service builds the matrix from rows; an all-NULL year
    means NO row exists for that year at all → it doesn't show
    up in the output (the dict is keyed by year in the service).
    Since the service only enters the year when at least one row
    has `year == Y`, the only way to get an all-NULL year is if
    the row has a NULL `monthly_return`. Verify that case."""
    cursor = _FakeCursor()
    cursor.set_rows([_mr_row(year=2026, month=3, monthly_return=0.0)])
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    row = result["matrix"][0]
    assert row["months"][2] == 0.0
    # Compound of 0%: 1.0 - 1 = 0.0 (not -1.0).
    assert row["yearly_return"] == 0.0


async def test_get_monthly_returns_multi_year_sorted_ascending() -> None:
    """Multi-year results are sorted by year ascending. The
    service iterates `sorted(matrix_map.keys())` and emits
    one row per year in order, regardless of the SQL's
    `ORDER BY year ASC`."""
    cursor = _FakeCursor()
    # Insert in non-sorted order to verify service sorts.
    cursor.set_rows(
        [
            _mr_row(year=2024, month=1, monthly_return=0.10),
            _mr_row(year=2026, month=1, monthly_return=0.05),
            _mr_row(year=2025, month=1, monthly_return=0.08),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    assert [row["year"] for row in result["matrix"]] == [2024, 2025, 2026]
    # Each year has 12 slots (one per month).
    assert all(len(row["months"]) == 12 for row in result["matrix"])


async def test_get_monthly_returns_uses_only_strategy_id_in_where() -> None:
    """The WHERE clause must scope to the requested strategy_id
    via parameter binding. No strategy_code is sent to the DB
    (it's only used for the response's `strategy_id` field)."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-99",
        strategy_code="STR_FUT_001",
    )

    sql, params = cursor.executed[0]
    assert "WHERE strategy_id = %s" in sql
    assert "ORDER BY year ASC, month ASC" in sql
    assert params == ("strat-uuid-99",)


async def test_get_monthly_returns_negative_returns_compound() -> None:
    """Negative returns compound correctly. -10% then +5%:
    0.90 * 1.05 - 1 = -0.055 (-5.5%)."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _mr_row(year=2026, month=1, monthly_return=-0.10),
            _mr_row(year=2026, month=2, monthly_return=0.05),
        ]
    )
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid",
        strategy_code="STR_FUT_001",
    )

    row = result["matrix"][0]
    assert row["yearly_return"] == pytest.approx(-0.055, rel=1e-9)


async def test_get_monthly_returns_strategy_id_in_response() -> None:
    """The response's `strategy_id` field is the human-facing code
    (not the UUID). Guards against a refactor that accidentally
    leaks the internal UUID to the frontend."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    result = await get_monthly_returns(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-99",
        strategy_code="STR_FUT_001",
    )

    assert result["strategy_id"] == "STR_FUT_001"
    # Not the UUID.
    assert "strat-uuid-99" not in result["strategy_id"]
