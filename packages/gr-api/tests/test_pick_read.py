"""``services/pick`` 的读逻辑与 ``routers/picks`` 的挂载。

三条必须守住的契约（见 services/pick.py 的模块 docstring）：
不返业绩数字、不返 score / suggest_weight、三种空态可区分。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from gr_api.errors import BadRequest
from gr_api.pagination import make_page_params
from gr_api.services import pick as pick_svc


pytestmark = pytest.mark.anyio

_TZ_SH = timezone(timedelta(hours=8))
_STRATEGY_UUID = str(uuid4())
_AUTHOR_UUID = str(uuid4())


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeDb:
    def __init__(self) -> None:
        self.strategy: dict[str, Any] = {
            "id": _STRATEGY_UUID,
            "strategy_code": "STR_STK_001",
            "name": "预增精选",
            "strategy_kind": "pick",
        }
        self.responses: dict[str, list[dict[str, Any]]] = {}
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def route(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.statements.append(sql)
        self.params.append(params)
        if "FROM strategies WHERE" in sql and "strategy_kind FROM strategies" in sql:
            return [self.strategy]
        for marker, rows in self.responses.items():
            if marker in sql:
                return rows
        return []


class _FakeCursor:
    def __init__(self, db: _FakeDb) -> None:
        self._db = db
        self._rows: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self._rows = self._db.route(sql, dict(params) if isinstance(params, dict) else {})

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _strategy_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "STR_STK_001",
        "name": "预增精选",
        "description": "筛选业绩预告大幅预增且估值未充分反映的个股",
        "category_id": "CAT_STOCK_PICK",
        "category_name": "选股策略",
        "asset_class": "stock",
        "market": "cn",
        "risk_level": "high",
        "run_status": "live",
        "cover_image": "",
        "author_id": _AUTHOR_UUID,
        "author_name": "张三",
        "subscription_monthly": 99.0,
        "subscription_yearly": 899.0,
        "tags": ["选股", "业绩预增"],
        "batch_trading_day": date(2026, 8, 12),
        "batch_item_count": 4,
        "batch_created_at": datetime(2026, 8, 12, 17, 20, tzinfo=_TZ_SH),
        "batch_note": None,
        "is_subscribed": False,
        "_total": 1,
    }
    row.update(overrides)
    return row


def _item_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "symbol": "600000",
        "exchange": "SSE",
        "symbol_name": "示例股A",
        "asset_class": "stock",
        "direction": "long",
        "option_type": None,
        "rank": 1,
        "entry_date": date(2026, 8, 11),
        "entry_date_source": "derived",
        "reason_text": "预告净利同比下限+82%",
        "trading_day": date(2026, 8, 12),
        "calendar_days": 2,
        "_total": 1,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 策略列表
# ---------------------------------------------------------------------------


async def test_list_pick_strategies_formats_brief() -> None:
    db = _FakeDb()
    db.responses["COUNT(*) OVER()"] = [_strategy_row()]

    items, total = await pick_svc.list_pick_strategies(
        db,
        user_id=None,
        category_id=None,
        keyword=None,
        data_state="all",
        status="active",
        sort="latest_trading_day",
        sort_order="desc",
        page=make_page_params(),
    )

    assert total == 1
    brief = items[0]
    assert brief["id"] == "STR_STK_001"
    assert brief["category"] == {"id": "CAT_STOCK_PICK", "name": "选股策略"}
    assert brief["creator"] == {"id": _AUTHOR_UUID, "name": "张三"}
    assert brief["tags"] == ["选股", "业绩预增"]
    assert brief["latest_batch"]["data_state"] == "updated"
    assert brief["subscription_price"] == {"monthly": 99.0, "yearly": 899.0}
    # P0 选股策略没有业绩数字，返 null 会误导前端。
    assert "performance" not in brief


async def test_list_pick_strategies_only_returns_pick_kind() -> None:
    db = _FakeDb()
    db.responses["COUNT(*) OVER()"] = [_strategy_row()]

    await pick_svc.list_pick_strategies(
        db,
        user_id="user-1",
        category_id="CAT_STOCK_PICK",
        keyword="预增",
        data_state="updated",
        status="active",
        sort="subscribers",
        sort_order="asc",
        page=make_page_params(),
    )

    sql = db.statements[0]
    assert "s.strategy_kind = 'pick'" in sql
    assert "s.pub_status = 'published'" in sql
    assert "lb.item_count > 0" in sql
    assert "user_strategy_subscriptions" in sql
    assert "ORDER BY s.subscriber_count ASC NULLS LAST" in sql


@pytest.mark.parametrize(
    ("field", "value"),
    [("sort", "sharpe"), ("sort_order", "sideways"), ("status", "deleted"), ("data_state", "x")],
)
async def test_list_pick_strategies_rejects_bad_params(field: str, value: str) -> None:
    kwargs: dict[str, Any] = {
        "user_id": None,
        "category_id": None,
        "keyword": None,
        "data_state": "all",
        "status": "active",
        "sort": "newest",
        "sort_order": "desc",
        "page": make_page_params(),
    }
    kwargs[field] = value

    with pytest.raises(BadRequest):
        await pick_svc.list_pick_strategies(_FakeDb(), **kwargs)


async def test_get_pick_strategy_adds_detail_and_range() -> None:
    db = _FakeDb()
    db.responses["dr.first_trading_day"] = [
        _strategy_row(
            detail_html="<h2>策略逻辑</h2>",
            created_at=datetime(2026, 8, 11, 10, 0, tzinfo=_TZ_SH),
            updated_at=datetime(2026, 8, 12, 17, 20, tzinfo=_TZ_SH),
            first_trading_day=date(2026, 8, 11),
            last_trading_day=date(2026, 8, 12),
            total_days=2,
        )
    ]

    data = await pick_svc.get_pick_strategy(db, strategy_ref="STR_STK_001", user_id=None)

    assert data["detail_html"] == "<h2>策略逻辑</h2>"
    assert data["data_range"] == {
        "first_trading_day": "2026-08-11",
        "last_trading_day": "2026-08-12",
        "total_days": 2,
    }
    assert data["created_at"].startswith("2026-08-11T10:00:00")


# ---------------------------------------------------------------------------
# 标的池与三种空态
# ---------------------------------------------------------------------------


async def test_list_strategy_picks_returns_items() -> None:
    db = _FakeDb()
    db.responses["SELECT b.batch_id, b.trading_day"] = [
        {
            "batch_id": 2,
            "trading_day": date(2026, 8, 12),
            "item_count": 1,
            "created_at": datetime(2026, 8, 12, 17, 20, tzinfo=_TZ_SH),
            "note": None,
        }
    ]
    db.responses["FROM pick.item i"] = [_item_row()]

    data = await pick_svc.list_strategy_picks(
        db,
        strategy_ref="STR_STK_001",
        trading_day=None,
        sort="rank",
        page=make_page_params(),
    )

    assert data["strategy"] == {"id": "STR_STK_001", "name": "预增精选"}
    assert data["batch"]["data_state"] == "updated"
    item = data["list"][0]
    assert item["symbol_full"] == "600000.SH"
    assert item["holding_trading_days"] == 2
    # 契约明确不返回评分与权重：量纲自定、跨策略不可比。
    assert "score" not in item
    assert "suggest_weight" not in item


async def test_empty_and_not_updated_are_distinguishable() -> None:
    """``empty``（确认空仓）与 ``not_updated``（还没传）语义完全不同。"""
    empty_db = _FakeDb()
    empty_db.responses["SELECT b.batch_id, b.trading_day"] = [
        {
            "batch_id": 3,
            "trading_day": date(2026, 8, 11),
            "item_count": 0,
            "created_at": datetime(2026, 8, 11, 17, 5, tzinfo=_TZ_SH),
            "note": "本期无符合条件标的",
        }
    ]

    empty = await pick_svc.list_strategy_picks(
        empty_db,
        strategy_ref="STR_STK_001",
        trading_day=date(2026, 8, 11),
        sort="rank",
        page=make_page_params(),
    )
    missing = await pick_svc.list_strategy_picks(
        _FakeDb(),
        strategy_ref="STR_STK_001",
        trading_day=date(2026, 8, 13),
        sort="rank",
        page=make_page_params(),
    )

    assert empty["batch"]["data_state"] == "empty"
    assert empty["batch"]["note"] == "本期无符合条件标的"
    assert missing["batch"]["data_state"] == "not_updated"
    assert missing["batch"]["trading_day"] is None
    assert missing["batch"]["updated_at"] is None
    assert missing["list"] == []


async def test_null_rank_sorts_last() -> None:
    db = _FakeDb()
    db.responses["SELECT b.batch_id, b.trading_day"] = [
        {
            "batch_id": 2,
            "trading_day": date(2026, 8, 12),
            "item_count": 2,
            "created_at": None,
            "note": None,
        }
    ]
    db.responses["FROM pick.item i"] = [_item_row(rank=None)]

    data = await pick_svc.list_strategy_picks(
        db,
        strategy_ref="STR_STK_001",
        trading_day=None,
        sort="rank",
        page=make_page_params(),
    )

    assert data["list"][0]["rank"] is None
    assert "i.rank ASC NULLS LAST" in db.statements[-1]


async def test_holding_days_falls_back_to_calendar_days_without_trading_calendar(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """交易日历没 ingest 时退化成自然日，并留下 WARN 提示口径变了。"""
    db = _FakeDb()
    db.responses["SELECT b.batch_id, b.trading_day"] = [
        {
            "batch_id": 2,
            "trading_day": date(2026, 8, 12),
            "item_count": 1,
            "created_at": None,
            "note": None,
        }
    ]
    db.responses["FROM pick.item i"] = [_item_row(calendar_days=0, entry_date=date(2026, 8, 10))]

    with caplog.at_level("WARNING"):
        data = await pick_svc.list_strategy_picks(
            db,
            strategy_ref="STR_STK_001",
            trading_day=None,
            sort="rank",
            page=make_page_params(),
        )

    assert data["list"][0]["holding_trading_days"] == 3
    assert "trading_calendar" in caplog.text


async def test_list_strategy_picks_rejects_bad_sort() -> None:
    with pytest.raises(BadRequest, match="invalid sort"):
        await pick_svc.list_strategy_picks(
            _FakeDb(),
            strategy_ref="STR_STK_001",
            trading_day=None,
            sort="score",
            page=make_page_params(),
        )


async def test_trading_days_marks_empty_batches() -> None:
    db = _FakeDb()
    db.responses["FROM pick.batch b"] = [
        {"trading_day": date(2026, 8, 12), "item_count": 4, "_total": 2},
        {"trading_day": date(2026, 8, 11), "item_count": 0, "_total": 2},
    ]

    data = await pick_svc.list_pick_trading_days(
        db,
        strategy_ref="STR_STK_001",
        start_date=None,
        end_date=None,
        limit=90,
    )

    assert [row["data_state"] for row in data["list"]] == ["updated", "empty"]
    assert data["total"] == 2


# ---------------------------------------------------------------------------
# 跨策略汇总与个股反查
# ---------------------------------------------------------------------------


async def test_latest_picks_attaches_per_strategy_batch_and_preview() -> None:
    db = _FakeDb()
    db.responses["JOIN LATERAL"] = [
        {
            "id": "STR_STK_001",
            "name": "预增精选",
            "category_id": "CAT_STOCK_PICK",
            "category_name": "选股策略",
            "batch_id": 2,
            "batch_trading_day": date(2026, 8, 12),
            "batch_item_count": 4,
            "batch_created_at": datetime(2026, 8, 12, 17, 20, tzinfo=_TZ_SH),
            "batch_note": None,
            "is_subscribed": False,
            "_total": 1,
        }
    ]
    db.responses["ROW_NUMBER() OVER ("] = [{**_item_row(), "batch_id": 2, "rn": 1}]

    items, total = await pick_svc.list_latest_picks(
        db,
        user_id=None,
        category_id=None,
        subscribed_only=False,
        preview_size=5,
        page=make_page_params(),
    )

    assert total == 1
    entry = items[0]
    # 各策略日期可能不同，所以 trading_day 挂在每个 batch 上而不是响应顶层。
    assert entry["batch"]["trading_day"] == "2026-08-12"
    assert entry["items"][0]["symbol_full"] == "600000.SH"


async def test_latest_picks_subscribed_only_without_login_returns_empty() -> None:
    items, total = await pick_svc.list_latest_picks(
        _FakeDb(),
        user_id=None,
        category_id=None,
        subscribed_only=True,
        preview_size=5,
        page=make_page_params(),
    )

    assert (items, total) == ([], 0)


async def test_by_symbol_aggregates_runs() -> None:
    db = _FakeDb()
    db.responses["WITH runs AS"] = [
        {
            "strategy_id": "STR_STK_001",
            "strategy_name": "预增精选",
            "entry_date": date(2026, 8, 11),
            "last_seen": date(2026, 8, 12),
            "still_in_pool": True,
            "latest_rank": 1,
            "latest_reason_text": "预告净利同比下限+82%",
            "symbol_name": "示例股A",
            "calendar_days": 2,
            "_total": 1,
        }
    ]

    data = await pick_svc.list_picks_by_symbol(
        db,
        symbol_full="600000.SH",
        start_date=None,
        end_date=None,
        in_pool_only=False,
        page=make_page_params(),
    )

    assert data["symbol"] == "600000.SH"
    assert data["symbol_name"] == "示例股A"
    entry = data["list"][0]
    # 连续持有 N 天归并成一条区间，不是 N 条。
    assert entry["entry_date"] == "2026-08-11"
    assert entry["last_seen_trading_day"] == "2026-08-12"
    assert entry["still_in_pool"] is True
    assert entry["holding_trading_days"] == 2


async def test_by_symbol_requires_suffixed_code() -> None:
    with pytest.raises(BadRequest, match="invalid symbol"):
        await pick_svc.list_picks_by_symbol(
            _FakeDb(),
            symbol_full="600000",
            start_date=None,
            end_date=None,
            in_pool_only=False,
            page=make_page_params(),
        )


async def test_by_symbol_in_pool_only_filters_on_latest_batch() -> None:
    db = _FakeDb()
    db.responses["WITH runs AS"] = []

    await pick_svc.list_picks_by_symbol(
        db,
        symbol_full="600000.SH",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 12),
        in_pool_only=True,
        page=make_page_params(),
    )

    sql = db.statements[-1]
    assert "r.last_seen = lb.latest_day" in sql
    assert "i.trading_day >= %(start)s" in sql


# ---------------------------------------------------------------------------
# 管理端
# ---------------------------------------------------------------------------


async def test_list_pick_batches_defaults_to_active() -> None:
    db = _FakeDb()
    db.responses["FROM pick.batch b"] = [
        {
            "batch_id": 2,
            "trading_day": date(2026, 8, 12),
            "source": "upload",
            "item_count": 4,
            "status": "active",
            "note": None,
            "created_at": datetime(2026, 8, 12, 17, 20, tzinfo=_TZ_SH),
            "import_job_id": None,
            "uploaded_by": None,
            "strategy_code": "STR_STK_001",
            "strategy_name": "预增精选",
            "uploaded_by_name": None,
            "_total": 1,
        }
    ]

    items, total = await pick_svc.list_pick_batches(
        db,
        strategy_ref=None,
        start_date=None,
        end_date=None,
        status="active",
        page=make_page_params(),
    )

    assert total == 1
    assert items[0]["batch_id"] == 2
    assert items[0]["strategy"] == {"id": "STR_STK_001", "name": "预增精选"}
    # 本仓还没有 import_jobs 表，这两个字段保留但恒为 null。
    assert items[0]["import_job_id"] is None
    assert items[0]["file_name"] is None
    assert "b.status = %(status)s" in db.statements[-1]


async def test_list_pick_batches_rejects_bad_status() -> None:
    with pytest.raises(BadRequest, match="invalid status"):
        await pick_svc.list_pick_batches(
            _FakeDb(),
            strategy_ref=None,
            start_date=None,
            end_date=None,
            status="draft",
            page=make_page_params(),
        )


# ---------------------------------------------------------------------------
# 路由挂载与安全头（AGENTS.md §8 硬要求）
# ---------------------------------------------------------------------------


def test_pick_routes_still_carry_security_headers() -> None:
    """新增路由后，4 个安全头必须照常出现在响应里。"""
    from fastapi.testclient import TestClient
    from gr_api.deps import get_db
    from gr_api.main import create_app

    db = _FakeDb()
    db.responses["COUNT(*) OVER()"] = [_strategy_row()]

    app = create_app()

    async def _fake_db() -> Any:
        yield db

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app)

    response = client.get("/v1/pick-strategies")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["list"][0]["id"] == "STR_STK_001"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response.headers


def test_pick_admin_route_requires_admin() -> None:
    """/v1/admin/pick-batches 走 require_admin，未登录必须 401。"""
    from fastapi.testclient import TestClient
    from gr_api.deps import get_db
    from gr_api.main import create_app

    app = create_app()

    async def _fake_db() -> Any:
        yield _FakeDb()

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app)

    response = client.get("/v1/admin/pick-batches")

    assert response.status_code == 401
