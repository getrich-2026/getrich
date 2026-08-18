"""Tests for ``get_strategy_detail``.

`services.strategy.get_strategy_detail` powers
``GET /strategies/{code}`. It's the highest-traffic read
endpoint and the most complex: 4 SELECTs in two cursor blocks:

1. **Block 1** (always runs):
   - main SELECT with `LEFT JOIN strategy_categories` + `LEFT JOIN
     latest_snapshot ps` (the CTE that picks the latest row per
     strategy)
   - tags SELECT (sorted by name)
   - creator SELECT (`id` + `name` from `users`)

2. **Block 2** (only when `user_id` is given):
   - subscription SELECT (active + expire_date >= today)

The `run_status` → frontend `status` mapping is also notable:
- `'paper'` / `'live'` / `NULL` → `'active'`
- `'paused'` / `'retired'` → `'inactive'`

The detail page is where the XSS defense layers from round
#1006-#1011 are most visible (the `detail_html` field goes
through `services.sanitize.normalize_detail_html` and the
frontend's `sanitizeHtml()` helper).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from gr_api.errors import NotFound
from gr_api.services.strategy import get_strategy_detail


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor.

    The service issues 3 SELECTs in block 1 (main, tags, creator)
    and optionally 1 SELECT in block 2 (subscription). We use a
    `push_one` / `set_rows` queue for each call.
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
        self._fetchone_q.append(row)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _main_row(
    *,
    strategy_code: str = "STR_FUT_001",
    name: str = "Fut 001",
    description: str = "desc",
    detail_html: str = "<h2>Hello</h2>",
    category_id: str | None = "cat-1",
    category_name: str | None = "Futures",
    asset_class: str = "futures",
    market: str = "CN",
    risk_level: str = "medium",
    run_status: str | None = "paper",
    subscriber_count: int = 100,
    backtest_start: date | None = date(2024, 1, 1),
    backtest_end: date | None = date(2024, 12, 31),
    subscription_monthly: float | None = 99.0,
    subscription_yearly: float | None = 999.0,
    published_at: datetime | None = None,
    updated_at: datetime | None = None,
    author_id: str = "u-author-1",
    total_return: float | None = 0.30,
    annualized_return: float | None = 0.30,
    max_drawdown: float | None = 0.10,
    sharpe_ratio: float | None = 1.5,
    sortino_ratio: float | None = 1.8,
    win_rate: float | None = 0.55,
    total_trades: int | None = 200,
) -> dict[str, Any]:
    return {
        "strategy_code": strategy_code,
        "name": name,
        "description": description,
        "detail_html": detail_html,
        "category_id": category_id,
        "category_name": category_name,
        "asset_class": asset_class,
        "market": market,
        "risk_level": risk_level,
        "run_status": run_status,
        "subscriber_count": subscriber_count,
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "subscription_monthly": subscription_monthly,
        "subscription_yearly": subscription_yearly,
        "published_at": published_at or datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        "updated_at": updated_at or datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
        "author_id": author_id,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "win_rate": win_rate,
        "total_trades": total_trades,
    }


def _creator_row(*, user_id: str = "u-author-1", name: str = "模拟作者") -> dict[str, Any]:
    return {"id": user_id, "name": name}


def _subscription_row(
    *,
    id: str = "sub-uuid-1",
    plan_type: str = "monthly",
    start_date: date = date(2026, 5, 1),
    expire_date: date = date(2027, 6, 1),
    auto_renew: bool = True,
) -> dict[str, Any]:
    return {
        "id": id,
        "plan_type": plan_type,
        "start_date": start_date,
        "expire_date": expire_date,
        "auto_renew": auto_renew,
    }


# ---------------------------------------------------------------------------
# get_strategy_detail
# ---------------------------------------------------------------------------


async def test_get_strategy_detail_raises_not_found_for_missing_strategy() -> None:
    """Main SELECT returns no row → NotFound before the tags /
    creator / subscription lookups are evaluated. The service
    also wraps `row["author_id"]` in a tuple so the creator
    SELECT doesn't crash with `None` when the main row is
    absent — this guards against an accidental refactor that
    re-introduces the None deref."""
    cursor = _FakeCursor()
    cursor.push_one(None)  # main → no strategy
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        await get_strategy_detail(
            conn,  # type: ignore[arg-type]
            strategy_id="strat-uuid-missing",
            user_id=None,
        )


async def test_get_strategy_detail_issues_main_tags_creator_queries() -> None:
    """Block 1 always issues 3 SELECTs:
    1) main + categories LEFT JOIN + latest_snapshot CTE
    2) tags (sorted by `t.name`)
    3) creator (id from `users`)
    """
    cursor = _FakeCursor()
    cursor.push_one(_main_row())  # main
    cursor.set_rows([{"name": "alpha"}, {"name": "beta"}])  # tags
    cursor.push_one(_creator_row())  # creator
    conn = _FakeConn(cursor)

    await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert len(cursor.executed) == 3
    main_sql, _ = cursor.executed[0]
    assert "strategy_performance_snapshot" in main_sql
    assert "LEFT JOIN strategy_categories" in main_sql
    assert "WHERE s.id = %(sid)s" in main_sql

    tags_sql, tags_params = cursor.executed[1]
    assert "strategy_tags st" in tags_sql
    assert "JOIN tags t ON t.id = st.tag_id" in tags_sql
    assert "ORDER BY t.name" in tags_sql
    assert tags_params == ("strat-uuid-1",)

    creator_sql, creator_params = cursor.executed[2]
    assert "SELECT id, name FROM users" in creator_sql
    assert "WHERE id = %s" in creator_sql
    assert creator_params == ("u-author-1",)


async def test_get_strategy_detail_no_subscription_query_when_user_id_none() -> None:
    """Block 2 (subscription SELECT) only runs when `user_id` is
    given. Anonymous viewers (e.g. the public strategy page) skip
    the subscription lookup — saves a roundtrip and avoids
    leaking the `user_id` SQL parameter."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    # Only 3 queries; no subscription lookup.
    assert len(cursor.executed) == 3
    # And the response has no subscription_info / is_subscribed=False.
    # (verified in a separate test below)


async def test_get_strategy_detail_emits_subscription_query_when_user_id_given() -> None:
    """With `user_id`, the service issues a 4th SELECT in a NEW
    cursor block (the service uses `async with db.cursor()` twice
    to scope the subscription lookup separately)."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    # Block 2: subscription → None (no active sub)
    cursor.push_one(None)
    conn = _FakeConn(cursor)

    await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id="u-viewer-1",
    )

    assert len(cursor.executed) == 4
    sub_sql, sub_params = cursor.executed[3]
    assert "user_strategy_subscriptions" in sub_sql
    assert "WHERE user_id = %s AND strategy_id = %s" in sub_sql
    assert "status = 'active'" in sub_sql
    assert "expire_date >= CURRENT_DATE" in sub_sql
    assert "ORDER BY expire_date DESC" in sub_sql
    assert "LIMIT 1" in sub_sql
    assert sub_params == ("u-viewer-1", "strat-uuid-1")


async def test_get_strategy_detail_run_status_paper_maps_to_active() -> None:
    cursor = _FakeCursor()
    cursor.push_one(_main_row(run_status="paper"))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["status"] == "active"


async def test_get_strategy_detail_run_status_live_maps_to_active() -> None:
    cursor = _FakeCursor()
    cursor.push_one(_main_row(run_status="live"))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["status"] == "active"


async def test_get_strategy_detail_run_status_null_defaults_to_paper_then_active() -> None:
    """`run_status IS NULL` (a brand-new strategy that hasn't
    been promoted yet) defaults to `paper` in the service's
    mapping, which then maps to `active` for the frontend."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(run_status=None))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["status"] == "active"


async def test_get_strategy_detail_run_status_paused_maps_to_inactive() -> None:
    cursor = _FakeCursor()
    cursor.push_one(_main_row(run_status="paused"))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["status"] == "inactive"


async def test_get_strategy_detail_run_status_retired_maps_to_inactive() -> None:
    cursor = _FakeCursor()
    cursor.push_one(_main_row(run_status="retired"))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["status"] == "inactive"


async def test_get_strategy_detail_tags_sorted_alphabetically() -> None:
    """The tags array preserves the SQL `ORDER BY t.name` order.
    The service returns rows verbatim so the sort happens in
    Postgres. This test pins the contract."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows(
        [
            {"name": "alpha"},
            {"name": "beta"},
            {"name": "gamma"},
        ]
    )
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["tags"] == ["alpha", "beta", "gamma"]


async def test_get_strategy_detail_tags_empty_when_no_rows() -> None:
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["tags"] == []


async def test_get_strategy_detail_creator_id_set_when_user_found() -> None:
    """The `creator` sub-dict surfaces the user's id when found
    in the `users` table. The other fields (name / avatar / bio)
    are hard-coded empty strings — the schema only carries
    `id` for now; the rest will be filled in via a future
    `users` profile migration."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(author_id="u-author-42"))
    cursor.set_rows([])
    cursor.push_one({"id": "u-author-42", "name": "模拟作者"})
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["creator"]["id"] == "u-author-42"
    assert result["creator"]["name"] == "模拟作者"
    assert result["creator"]["avatar"] == ""
    assert result["creator"]["bio"] == ""


async def test_get_strategy_detail_creator_empty_when_user_not_found() -> None:
    """If the author_id has no matching `users` row (e.g. the
    user was deleted but the strategy lives on as orphan
    content), the `creator` sub-dict has `id=""` and the
    other fields stay empty. The frontend renders a
    "deleted user" placeholder."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(author_id="u-deleted"))
    cursor.set_rows([])
    cursor.push_one(None)  # users SELECT → no match
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["creator"]["id"] == ""
    assert result["creator"]["name"] == ""


async def test_get_strategy_detail_subscription_info_when_active() -> None:
    """When the subscription SELECT returns a row (active +
    not expired), the response's `subscription_info` is a
    fully-populated dict with ISO dates and the
    `is_subscribed` flag is True."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    cursor.push_one(
        _subscription_row(
            id="sub-uuid-1",
            plan_type="monthly",
            start_date=date(2026, 5, 1),
            expire_date=date(2027, 6, 1),
            auto_renew=True,
        )
    )
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id="u-viewer-1",
    )

    assert result["is_subscribed"] is True
    assert result["subscription_info"] == {
        "subscription_id": "sub-uuid-1",
        "plan_type": "monthly",
        "start_date": "2026-05-01",
        "expire_date": "2027-06-01",
        "auto_renew": True,
    }


async def test_get_strategy_detail_no_subscription_info_when_inactive() -> None:
    """The subscription SELECT filters to `status='active' AND
    expire_date >= CURRENT_DATE` — an expired sub never
    surfaces. `is_subscribed=False` and `subscription_info=None`
    in that case."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    cursor.push_one(None)  # expired → no row
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id="u-viewer-1",
    )

    assert result["is_subscribed"] is False
    assert result["subscription_info"] is None


async def test_get_strategy_detail_anonymous_no_subscription_block() -> None:
    """Without `user_id`, the `is_subscribed` flag is hard-coded
    False and `subscription_info` is None. The 4th SELECT is
    skipped entirely."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["is_subscribed"] is False
    assert result["subscription_info"] is None
    # Only 3 queries ran.
    assert len(cursor.executed) == 3


async def test_get_strategy_detail_category_handles_nulls() -> None:
    """When the strategy has no category (a draft / uncategorized),
    both `category.id` and `category.name` are empty strings."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            category_id=None,
            category_name=None,
        )
    )
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["category"] == {"id": "", "name": ""}


async def test_get_strategy_detail_subscription_price_default_to_zero() -> None:
    """`subscription_monthly` / `subscription_yearly` are
    nullable in the schema (free strategies have no price).
    The service uses `float(... or 0)` so the public dict
    always has both keys with non-None values."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            subscription_monthly=None,
            subscription_yearly=None,
        )
    )
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["subscription_price"] == {"monthly": 0.0, "yearly": 0.0}


async def test_get_strategy_detail_performance_handles_null_metrics() -> None:
    """When the latest_snapshot LEFT JOIN has no row, all
    performance metrics are NULL → 0.0 (the `_f` helper)."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            total_return=None,
            annualized_return=None,
            max_drawdown=None,
            sharpe_ratio=None,
            sortino_ratio=None,
            win_rate=None,
            total_trades=None,
        )
    )
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    p = result["performance"]
    assert p["total_return"] == 0.0
    assert p["annualized_return"] == 0.0
    assert p["max_drawdown"] == 0.0
    assert p["sharpe_ratio"] == 0.0
    assert p["sortino_ratio"] == 0.0
    assert p["win_rate"] == 0.0
    assert p["total_trades"] == 0


async def test_get_strategy_detail_serializes_backtest_period() -> None:
    """`backtest_period.start` / `.end` are ISO dates or empty
    strings when NULL."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            backtest_start=None,
            backtest_end=None,
        )
    )
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["backtest_period"] == {"start": "", "end": ""}


async def test_get_strategy_detail_serializes_published_and_updated_at() -> None:
    """`published_at` / `updated_at` are datetime → ISO string."""
    cursor = _FakeCursor()
    cursor.push_one(
        _main_row(
            published_at=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
        )
    )
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["published_at"] == "2026-05-01T09:00:00+00:00"
    assert result["updated_at"] == "2026-05-02T09:00:00+00:00"


async def test_get_strategy_detail_id_is_human_code_not_uuid() -> None:
    """The response's top-level `id` is the strategy_code (the
    URL path value), not the UUID. Same contract as the
    other read endpoints."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row(strategy_code="STR_FUT_001"))
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    assert result["id"] == "STR_FUT_001"
    assert "strat-uuid-1" not in result["id"]


async def test_get_strategy_detail_output_schema_keys() -> None:
    """The full public schema. Pinned so a future refactor that
    drops a field is caught."""
    cursor = _FakeCursor()
    cursor.push_one(_main_row())
    cursor.set_rows([])
    cursor.push_one(_creator_row())
    conn = _FakeConn(cursor)

    result = await get_strategy_detail(
        conn,  # type: ignore[arg-type]
        strategy_id="strat-uuid-1",
        user_id=None,
    )

    expected_keys = {
        "id",
        "name",
        "description",
        "detail_html",
        "category",
        "asset_class",
        "market",
        "risk_level",
        "status",
        "tags",
        "creator",
        "performance",
        "backtest_period",
        "subscriber_count",
        "is_subscribed",
        "subscription_info",
        "subscription_price",
        "published_at",
        "updated_at",
    }
    assert set(result.keys()) == expected_keys
    # performance sub-keys
    assert set(result["performance"].keys()) == {
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_ratio",
        "sortino_ratio",
        "win_rate",
        "total_trades",
    }
    # creator sub-keys
    assert set(result["creator"].keys()) == {"id", "name", "avatar", "bio"}
    # category sub-keys
    assert set(result["category"].keys()) == {"id", "name"}
    # subscription_price sub-keys
    assert set(result["subscription_price"].keys()) == {"monthly", "yearly"}
