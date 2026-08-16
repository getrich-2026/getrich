"""Tests for the strategy read service.

`services.strategy` is the largest service module (879 lines). The
read path used by the strategy list / detail / categories endpoints
is currently uncovered. This file covers:

- `list_strategies` — sort whitelist, status filter mapping
  (active/inactive → SQL fragments), keyword ILIKE, conditional
  subscription join for authenticated users, output schema
- `list_categories` — LEFT JOIN with `COUNT(s.id)` aggregates over
  `pub_status='published'` strategies only

The other read functions (`get_strategy_detail`, `get_equity_curve`,
`get_monthly_returns`, `get_backtest_report`, `list_trades`,
`list_signals_of_strategy`) are tested by their own files in
follow-up rounds; the focus here is on `list_strategies` which has
the most SQL and the most non-trivial control flow.
"""

from __future__ import annotations

from typing import Any

import pytest
from gr_api.errors import BadRequest
from gr_api.services.strategy import list_categories, list_strategies


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor. `set_rows` queues a `fetchall` response."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple]] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []

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

    async def fetchone(self):  # pragma: no cover — not used by these
        if self._fetchone_q:
            return self._fetchone_q.pop(0)
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


def _strategy_row(
    *,
    id: str = "STR_FUT_001",
    name: str = "Fut 001",
    description: str = "desc",
    asset_class: str = "futures",
    market: str = "CN",
    risk_level: str = "medium",
    cover_image: str = "https://cdn.example.com/c.png",
    subscriber_count: int = 100,
    subscription_monthly: float = 99.0,
    subscription_yearly: float = 999.0,
    annualized_return: float | None = 0.15,
    max_drawdown: float | None = 0.10,
    sharpe_ratio: float | None = 1.2,
    win_rate: float | None = 0.55,
    total_return: float | None = 0.30,
    is_subscribed: bool = False,
    total_count: int = 1,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "description": description,
        "asset_class": asset_class,
        "market": market,
        "risk_level": risk_level,
        "cover_image": cover_image,
        "subscriber_count": subscriber_count,
        "subscription_monthly": subscription_monthly,
        "subscription_yearly": subscription_yearly,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "win_rate": win_rate,
        "total_return": total_return,
        "is_subscribed": is_subscribed,
        "_total": total_count,
    }


# ---------------------------------------------------------------------------
# list_strategies
# ---------------------------------------------------------------------------


async def test_list_strategies_rejects_invalid_sort() -> None:
    """Sort must be in the whitelist; an unknown value → BadRequest
    before any SQL is issued. This guards against a future refactor
    that interpolates the sort string into the ORDER BY (SQLi)."""
    cursor = _FakeCursor()
    conn = _FakeConn(cursor)

    with pytest.raises(BadRequest):
        await list_strategies(
            conn,  # type: ignore[arg-type]
            user_id=None,
            category_id=None,
            asset_class=None,
            risk_level=None,
            market=None,
            keyword=None,
            status=None,
            sort="DROP TABLE strategies",
            page=_Page(),
        )

    assert cursor.executed == []


async def test_list_strategies_always_filters_to_published() -> None:
    """The `pub_status = 'published'` filter is unconditional — the
    endpoint is publicly visible to anonymous users and must never
    leak drafts. This guards against a tenant-bleed refactor that
    accidentally drops the conds list seed.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    main_sql = cursor.executed[0][0]
    assert "s.pub_status = 'published'" in main_sql


async def test_list_strategies_anonymous_skips_subscription_join() -> None:
    """Without `user_id`, the service MUST NOT add a LEFT JOIN on
    `user_strategy_subscriptions` and `is_subscribed` MUST default
    to FALSE in SQL. The user-side join would just be wasted
    work, and the subquery's `is_subscribed=FALSE` is what the
    service contract promises to anonymous viewers.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    main_sql = cursor.executed[0][0]
    assert "user_strategy_subscriptions" not in main_sql
    assert "FALSE" in main_sql  # the {sub_select} interpolation
    # No uid param either.
    assert "uid" not in cursor.executed[0][1]


async def test_list_strategies_authenticated_emits_subscription_join() -> None:
    """With `user_id`, the SQL must join the subscriptions table
    with the right filters (active + expire_date >= CURRENT_DATE)
    and the `is_subscribed` flag switches to `uss.id IS NOT NULL`.
    """
    cursor = _FakeCursor()
    cursor.set_rows([_strategy_row(is_subscribed=True)])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id="u-1",
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "LEFT JOIN user_strategy_subscriptions uss" in main_sql
    assert "uss.user_id = %(uid)s" in main_sql
    assert "uss.status = 'active'" in main_sql
    assert "uss.expire_date >= CURRENT_DATE" in main_sql
    assert "uss.id IS NOT NULL" in main_sql
    assert main_params["uid"] == "u-1"


async def test_list_strategies_status_active_maps_to_paper_or_live() -> None:
    """The frontend's `status='active'` filter expands to either
    `run_status IN ('paper', 'live')` OR `run_status IS NULL` —
    NULL is a real DB state for strategies that haven't been
    promoted yet, and the frontend treats them as "active".
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status="active",
        sort="newest",
        page=_Page(),
    )

    main_sql = cursor.executed[0][0]
    assert "s.run_status IN ('paper', 'live')" in main_sql
    assert "s.run_status IS NULL" in main_sql


async def test_list_strategies_status_inactive_maps_to_paused_or_retired() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status="inactive",
        sort="newest",
        page=_Page(),
    )

    main_sql = cursor.executed[0][0]
    assert "s.run_status IN ('paused', 'retired')" in main_sql


async def test_list_strategies_keyword_uses_ilike_with_wildcards() -> None:
    """A `keyword` filter wraps the value in `%...%` and uses
    `ILIKE` (case-insensitive) so the frontend's search box works
    with mixed-case input. Search hits BOTH `name` and `summary`.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword="rBo",
        status=None,
        sort="newest",
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "ILIKE %(kw)s" in main_sql
    assert "s.name" in main_sql
    assert "s.summary" in main_sql
    # The kw param is wrapped in % wildcards server-side.
    assert main_params["kw"] == "%rBo%"


async def test_list_strategies_passes_filters_to_params() -> None:
    """All filter values (category / asset_class / risk_level /
    market) land as named params so the route's user input is
    always parameterized."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id="cat-1",
        asset_class="futures",
        risk_level="high",
        market="CN",
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    main_sql, main_params = cursor.executed[0]
    assert "s.category_id = %(category_id)s" in main_sql
    assert "s.asset_class = %(asset_class)s" in main_sql
    assert "s.risk_level = %(risk_level)s" in main_sql
    assert "s.market = %(market)s" in main_sql
    assert main_params["category_id"] == "cat-1"
    assert main_params["asset_class"] == "futures"
    assert main_params["risk_level"] == "high"
    assert main_params["market"] == "CN"


async def test_list_strategies_pagination_params() -> None:
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(limit=50, offset=200),
    )

    main_params = cursor.executed[0][1]
    assert main_params["limit"] == 50
    assert main_params["offset"] == 200


async def test_list_strategies_sorts_translate_to_correct_columns() -> None:
    """Each sort whitelist key maps to a specific column +
    direction. Guards against a refactor that re-points
    'annualized_return' to the wrong column or flips the
    'max_drawdown' direction (smaller-is-better)."""
    expected = {
        "sharpe": ("ps.sharpe_ratio", "DESC"),
        "annualized_return": ("ps.annualized_return", "DESC"),
        "max_drawdown": ("ps.max_drawdown", "ASC"),  # smaller = better
        "subscribers": ("s.subscriber_count", "DESC"),
        "newest": ("s.published_at", "DESC"),
    }
    for sort_key, (col, direction) in expected.items():
        cursor = _FakeCursor()
        cursor.set_rows([])
        conn = _FakeConn(cursor)

        await list_strategies(
            conn,  # type: ignore[arg-type]
            user_id=None,
            category_id=None,
            asset_class=None,
            risk_level=None,
            market=None,
            keyword=None,
            status=None,
            sort=sort_key,
            page=_Page(),
        )

        main_sql = cursor.executed[0][0]
        assert f"ORDER BY {col} {direction}" in main_sql, (
            f"sort={sort_key!r} did not map to {col} {direction}"
        )


async def test_list_strategies_serializes_output_schema() -> None:
    """The output dict has the public schema (snake_case keys,
    nested `subscription_price` and `performance` sub-dicts,
    `is_subscribed` as bool)."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _strategy_row(
                id="STR_FUT_001",
                name="Fut 001",
                description="desc",
                asset_class="futures",
                risk_level="medium",
                subscriber_count=42,
                subscription_monthly=99.0,
                subscription_yearly=999.0,
                annualized_return=0.15,
                max_drawdown=0.10,
                sharpe_ratio=1.2,
                win_rate=0.55,
                is_subscribed=False,
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, total = await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    assert total == 1
    assert len(items) == 1
    item = items[0]
    assert item["id"] == "STR_FUT_001"
    assert item["name"] == "Fut 001"
    assert item["asset_class"] == "futures"
    assert item["subscriber_count"] == 42
    assert item["is_subscribed"] is False
    assert item["subscription_price"] == {"monthly": 99.0, "yearly": 999.0}
    assert item["performance"] == {
        "annualized_return": 0.15,
        "max_drawdown": 0.10,
        "sharpe_ratio": 1.2,
        "win_rate": 0.55,
    }


async def test_list_strategies_handles_null_performance_metrics() -> None:
    """When the `latest_snapshot` LEFT JOIN has no row, the
    performance metrics are NULL → must surface as 0.0 (the
    service's `_f` helper) not as Python `None` — the frontend
    can't render `None` in a chart."""
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            _strategy_row(
                annualized_return=None,
                max_drawdown=None,
                sharpe_ratio=None,
                win_rate=None,
            )
        ]
    )
    conn = _FakeConn(cursor)

    items, _ = await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    assert items[0]["performance"] == {
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
    }


async def test_list_strategies_empty_result_returns_empty_list() -> None:
    """No rows → empty list, total=0. Avoids IndexError on the
    `rows[0]["_total"]` access."""
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    items, total = await list_strategies(
        conn,  # type: ignore[arg-type]
        user_id=None,
        category_id=None,
        asset_class=None,
        risk_level=None,
        market=None,
        keyword=None,
        status=None,
        sort="newest",
        page=_Page(),
    )

    assert items == []
    assert total == 0


# ---------------------------------------------------------------------------
# list_categories
# ---------------------------------------------------------------------------


async def test_list_categories_returns_rows_verbatim() -> None:
    """`list_categories` is a single SELECT with a LEFT JOIN +
    GROUP BY. The service returns the rows verbatim — the
    frontend's `CategoryList` component reads them as-is. So
    no row-level transformation is expected.
    """
    cursor = _FakeCursor()
    cursor.set_rows(
        [
            {
                "id": "cat-1",
                "name": "Futures",
                "description": "期货策略",
                "icon_url": "https://cdn.example.com/fut.png",
                "strategy_count": 12,
            },
            {
                "id": "cat-2",
                "name": "Stocks",
                "description": "股票策略",
                "icon_url": "",
                "strategy_count": 3,
            },
        ]
    )
    conn = _FakeConn(cursor)

    rows = await list_categories(conn)  # type: ignore[arg-type]

    assert len(rows) == 2
    assert rows[0]["id"] == "cat-1"
    assert rows[0]["name"] == "Futures"
    assert rows[0]["strategy_count"] == 12
    assert rows[1]["id"] == "cat-2"
    assert rows[1]["icon_url"] == ""


async def test_list_categories_joins_only_published_strategies() -> None:
    """The category-count subquery must scope to `pub_status='published'`
    so draft strategies don't inflate the public count.
    """
    cursor = _FakeCursor()
    cursor.set_rows([])
    conn = _FakeConn(cursor)

    await list_categories(conn)  # type: ignore[arg-type]

    sql = cursor.executed[0][0]
    assert "LEFT JOIN strategies s" in sql
    assert "s.pub_status = 'published'" in sql
    assert "COUNT(s.id)::int" in sql
