"""持仓诊断服务层与路由的单元测试。

覆盖设计 §7.2 的业务校验顺序（PA-01、PA-02、PA-14、PA-15）、§7.8 计算缓存键与
重算拒绝。数据库用按 SQL 片段分派的假连接；真实 SQL 由 test_diagnosis_pg_integration 覆盖。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from gr_api.errors import ApiError
from gr_api.schemas.diagnosis import (
    CalculationOptions,
    HoldingItem,
    OptionWindow,
    PortfolioPlan,
    RecomputeRequest,
)
from gr_api.services import diagnosis as svc


TZ = ZoneInfo("Asia/Shanghai")
AS_OF = date(2026, 10, 29)
_CALENDAR_END = date(2026, 11, 6)
CALENDAR = [
    _CALENDAR_END - timedelta(days=i)
    for i in range(420)
    if (_CALENDAR_END - timedelta(days=i)).weekday() < 5
]


Handler = Callable[[tuple[Any, ...]], list[dict[str, Any]]]


class FakeCursor:
    def __init__(self, db: FakeDb) -> None:
        self.db = db
        self.rows: list[dict[str, Any]] = []

    async def __aenter__(self) -> FakeCursor:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.db.sql.append(sql)
        for fragment, handler in self.db.handlers:
            if fragment in sql:
                self.rows = handler(params)
                return
        raise AssertionError(f"unexpected SQL: {sql[:120]}")

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeDb:
    def __init__(self, handlers: list[tuple[str, Handler]]) -> None:
        self.handlers = handlers
        self.sql: list[str] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @asynccontextmanager
    async def transaction(self):
        yield


def fake_db(handlers: list[tuple[str, Handler]]) -> Any:
    """服务函数标注为 DictConnection；假连接只实现被调用的子集，按 Any 传入。"""
    return FakeDb(handlers)


def _calendar_handlers() -> list[tuple[str, Handler]]:
    """meta.trading_calendar 的三种查询：on/before、on/after、向前第 N 日。"""

    def on_or_before(params: tuple[Any, ...]) -> list[dict[str, Any]]:
        days = [d for d in CALENDAR if d <= params[1]]
        if len(params) == 3:  # LIMIT n
            return [{"trading_day": d} for d in days[: params[2]]]
        return [{"trading_day": days[0]}] if days else []

    def on_or_after(params: tuple[Any, ...]) -> list[dict[str, Any]]:
        days = sorted(d for d in CALENDAR if d >= params[1])
        return [{"trading_day": days[0]}] if days else []

    return [
        ("trading_day >= %s", on_or_after),
        ("trading_day <= %s", on_or_before),
    ]


def _data_version(snapshot_day: date = AS_OF, **available: Any) -> dict[str, Any]:
    return {
        "data_version_id": "dv-1",
        "snapshot_at": datetime.combine(snapshot_day, datetime.min.time(), TZ).replace(hour=18),
        "available_options": available,
    }


def _instrument(iid: int, symbol: str, **kw: Any) -> dict[str, Any]:
    exchange = "XSHG" if symbol.endswith(".SH") else "XSHE" if symbol.endswith(".SZ") else "XBSE"
    return {
        "instrument_id": iid,
        "symbol": symbol,
        "asset": "stock",
        "exchange": exchange,
        "name": f"股票{iid}",
        "list_date": date(2010, 1, 4),
        "delist_date": None,
        "status": "active",
        **kw,
    }


def _symbol_db(instruments: list[dict[str, Any]], aliases: dict[str, int] | None = None) -> Any:
    by_symbol = {i["symbol"]: i for i in instruments}
    by_id = {i["instrument_id"]: i for i in instruments}
    alias_map = aliases or {}

    def current(params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [{**by_symbol[s], "lookup": s} for s in params[0] if s in by_symbol]

    def historical(params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [{**by_id[alias_map[s]], "lookup": s} for s in params[0] if s in alias_map]

    return fake_db([("FROM meta.symbol_map", historical), ("FROM meta.instruments", current)])


@pytest.fixture
def frozen_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_today", lambda: AS_OF)


# ===========================================================================
# §7.8 计算缓存键
# ===========================================================================


def _hash(**overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "weight_mode": "user",
        "quantized": {1: 60_000_000, 2: 40_000_000},
        "resolved_as_of_date": AS_OF,
        "spec_version": "v1",
        "data_fingerprint": "dv-1",
        "resolved_options": {"industry_scheme": None},
    }
    kwargs.update(overrides)
    return svc._calculation_hash(**kwargs)


def test_calculation_hash_ignores_holding_order() -> None:
    assert _hash() == _hash(quantized={2: 40_000_000, 1: 60_000_000})


@pytest.mark.parametrize(
    "override",
    [
        {"data_fingerprint": "dv-2"},
        {"spec_version": "v2"},
        {"resolved_as_of_date": date(2026, 10, 28)},
        {"weight_mode": "equal"},
        {"quantized": {1: 60_000_001, 2: 39_999_999}},
        # PA-05/PA-09～PA-12：用户可选参数必须隔离结果与缓存
        {"resolved_options": {"industry_scheme": "sw2021"}},
    ],
)
def test_calculation_hash_changes_with_every_numeric_input(override: dict[str, Any]) -> None:
    assert _hash() != _hash(**override)


def test_canonical_json_is_key_order_independent() -> None:
    assert svc._canonical_json({"b": 1, "a": [1, 2]}) == svc._canonical_json({"a": [1, 2], "b": 1})


# ===========================================================================
# PA-14 诊断日期
# ===========================================================================


@pytest.mark.anyio
async def test_default_date_is_latest_published_trading_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "_today", lambda: date(2026, 10, 31))
    db = fake_db(_calendar_handlers())
    # 发布日是周六时向前取最近交易日
    resolved = await svc._resolve_as_of_date(db, None, _data_version(date(2026, 10, 31)))
    assert resolved == date(2026, 10, 30)


@pytest.mark.anyio
async def test_default_date_never_exceeds_today(frozen_today: None) -> None:
    db = fake_db(_calendar_handlers())
    resolved = await svc._resolve_as_of_date(db, None, _data_version(date(2026, 10, 31)))
    assert resolved == AS_OF


@pytest.mark.anyio
async def test_explicit_date_after_publication_rolls_back_to_published(frozen_today: None) -> None:
    db = fake_db(_calendar_handlers())
    resolved = await svc._resolve_as_of_date(db, AS_OF, _data_version(date(2026, 10, 28)))
    assert resolved == date(2026, 10, 28)


@pytest.mark.anyio
async def test_earlier_date_is_rejected_as_unavailable_history(frozen_today: None) -> None:
    db = fake_db(_calendar_handlers())
    with pytest.raises(ApiError) as exc_info:
        await svc._resolve_as_of_date(db, date(2026, 10, 27), _data_version())
    assert exc_info.value.http_status == 422
    assert exc_info.value.issues[0] == {
        "path": "/as_of_date",
        "code": "feature_not_available",
        "message": exc_info.value.message,
    }


@pytest.mark.anyio
async def test_future_date_is_rejected(frozen_today: None) -> None:
    with pytest.raises(ApiError) as exc_info:
        await svc._resolve_as_of_date(fake_db([]), AS_OF + timedelta(days=1), _data_version())
    assert exc_info.value.http_status == 422


def test_today_uses_platform_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FakeDateTime:
            assert str(tz) == "Asia/Shanghai"
            return cls(2026, 8, 31, 0, 30, tzinfo=tz)

    monkeypatch.setattr(svc, "datetime", FakeDateTime)
    assert svc._today() == date(2026, 8, 31)


# ===========================================================================
# §7.2 第 8 步 options 解析
# ===========================================================================


PARAMS = {
    "industry_scheme": "sw2021",
    "benchmark_instrument_id": 300,
    "cov_method_params": {"historical": {"lookback_days": 252}},
    "beta_lookback_days": 252,
}


async def _options(requested: CalculationOptions | None = None, **kw: Any) -> dict[str, Any]:
    return await svc._resolve_options(
        fake_db(_calendar_handlers()),
        requested=requested or CalculationOptions(),
        params=kw.pop("params", PARAMS),
        available=kw.pop("available", {}),
        as_of=AS_OF,
        **kw,
    )


@pytest.mark.anyio
async def test_defaults_are_written_as_concrete_values() -> None:
    resolved = await _options()
    start = date.fromisoformat(resolved["correlation_window"]["start"])
    assert resolved["correlation_window"]["end"] == AS_OF.isoformat()
    assert len([d for d in CALENDAR if start <= d <= AS_OF]) == 252
    assert resolved["beta_window"] == resolved["correlation_window"]
    # 默认项未验证：写 None，相关指标不可用，不回退其他体系或价格指数
    assert resolved["industry_scheme"] is None
    assert resolved["benchmark_instrument_id"] is None
    assert resolved["replay_start"] is None
    assert resolved["stats_window"] is None


@pytest.mark.anyio
async def test_validated_defaults_are_resolved_with_versions() -> None:
    resolved = await _options(
        available={
            "industry_schemes": [{"code": "sw2021", "version": "2021-07"}],
            "benchmarks": [{"instrument_id": 300, "symbol": "H00300.CSI", "version": "tr-1"}],
        }
    )
    assert (resolved["industry_scheme"], resolved["industry_scheme_version"]) == (
        "sw2021",
        "2021-07",
    )
    assert (resolved["benchmark_instrument_id"], resolved["benchmark_version"]) == (300, "tr-1")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("requested", "path"),
    [
        (CalculationOptions(industry_scheme="citic"), "/options/industry_scheme"),
        (CalculationOptions(benchmark="000300.SH"), "/options/benchmark"),
        (CalculationOptions(replay_start=date(2025, 1, 2)), "/options/replay_start"),
        (
            CalculationOptions(
                correlation_window=OptionWindow(start=date(2026, 1, 5), end=date(2026, 11, 2))
            ),
            "/options/correlation_window/end",
        ),
        (
            # 两端解析到同一个交易日
            CalculationOptions(
                beta_window=OptionWindow(start=date(2026, 10, 24), end=date(2026, 10, 26))
            ),
            "/options/beta_window",
        ),
    ],
)
async def test_explicit_unavailable_or_invalid_options_are_rejected(
    requested: CalculationOptions, path: str
) -> None:
    with pytest.raises(ApiError) as exc_info:
        await _options(requested)
    assert exc_info.value.http_status == 422
    assert exc_info.value.issues[0]["path"] == path


@pytest.mark.anyio
async def test_explicit_window_is_snapped_to_trading_days() -> None:
    resolved = await _options(
        CalculationOptions(
            correlation_window=OptionWindow(start=date(2026, 1, 3), end=date(2026, 6, 28))
        )
    )
    assert resolved["correlation_window"] == {"start": "2026-01-05", "end": "2026-06-26"}


@pytest.mark.anyio
async def test_recompute_keeps_base_values_and_resets_only_named_fields() -> None:
    base = await _options()
    base["beta_window"] = {"start": "2026-03-02", "end": "2026-09-30"}
    base["correlation_window"] = {"start": "2026-03-02", "end": "2026-09-30"}
    resolved = await _options(
        CalculationOptions(
            correlation_window=OptionWindow(start=date(2026, 5, 4), end=date(2026, 8, 31))
        ),
        base=base,
        reset=frozenset({"beta_window"}),
    )
    assert resolved["correlation_window"] == {"start": "2026-05-04", "end": "2026-08-31"}
    assert resolved["beta_window"]["end"] == AS_OF.isoformat()  # 恢复为口径默认值


# ===========================================================================
# PA-01、PA-02 代码解析与范围校验
# ===========================================================================


@pytest.mark.anyio
async def test_historical_alias_resolves_through_symbol_map() -> None:
    db = _symbol_db([_instrument(9, "001872.SZ")], aliases={"000022.SZ": 9})
    resolved = await svc._resolve_symbols(db, {"000022.SZ", "001872.SZ", "BAD"}, as_of=AS_OF)
    old, new = resolved["000022.SZ"].instrument, resolved["001872.SZ"].instrument
    assert old is not None and new is not None
    assert old["instrument_id"] == new["instrument_id"] == 9
    assert resolved["BAD"].instrument is None and resolved["BAD"].out_of_scope is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        (_instrument(1, "920001.BJ"), "北交所"),
        (_instrument(2, "600002.SH", status="delisted"), "已退市"),
        (_instrument(3, "600003.SH", delist_date=AS_OF), "已退市"),
        (_instrument(4, "510300.SH", asset="etf"), "etf"),
    ],
)
async def test_recognized_out_of_scope_assets_are_flagged(
    row: dict[str, Any], fragment: str
) -> None:
    resolved = await svc._resolve_symbols(_symbol_db([row]), {row["symbol"]}, as_of=AS_OF)
    assert fragment in (resolved[row["symbol"]].out_of_scope or "")


@pytest.mark.anyio
async def test_symbol_matching_two_stocks_is_ambiguous() -> None:
    db = _symbol_db([_instrument(1, "001872.SZ"), _instrument(2, "001914.SZ")])
    db.handlers.insert(
        0,
        (
            "FROM meta.instruments",
            lambda params: [
                {**_instrument(1, "001872.SZ"), "lookup": "001872.SZ"},
                {**_instrument(2, "001872.SZ"), "lookup": "001872.SZ"},
            ],
        ),
    )
    with pytest.raises(ApiError, match="ambiguous") as exc_info:
        await svc._resolve_symbols(db, {"001872.SZ"}, as_of=AS_OF)
    assert exc_info.value.http_status == 422


@pytest.mark.anyio
async def test_out_of_scope_assets_reject_the_whole_request_with_input_paths() -> None:
    db = _symbol_db([_instrument(1, "600001.SH"), _instrument(2, "920002.BJ")])
    plans = [
        PortfolioPlan(plan_id="a", holdings=[HoldingItem(symbol="600001.SH")]),
        PortfolioPlan(
            plan_id="b",
            holdings=[HoldingItem(symbol="600001.SH"), HoldingItem(symbol="920002.bj")],
        ),
    ]
    with pytest.raises(ApiError) as exc_info:
        await svc._normalize_request_plans(db, plans, as_of=AS_OF)
    assert exc_info.value.http_status == 422
    assert [i["path"] for i in exc_info.value.issues] == ["/plans/1/holdings/1/symbol"]
    assert exc_info.value.issues[0]["code"] == "unsupported_asset"


@pytest.mark.anyio
async def test_plan_without_resolvable_holdings_points_at_that_plan() -> None:
    db = _symbol_db([_instrument(1, "600001.SH")])
    plans = [
        PortfolioPlan(plan_id="ok", holdings=[HoldingItem(symbol="600001.SH")]),
        PortfolioPlan(plan_id="bad", holdings=[HoldingItem(symbol="GARBAGE")]),
    ]
    with pytest.raises(ApiError) as exc_info:
        await svc._normalize_request_plans(db, plans, as_of=AS_OF)
    assert exc_info.value.issues[0]["path"] == "/plans/1/holdings"


@pytest.mark.anyio
async def test_plan_inputs_keep_raw_rows_and_quantized_weights() -> None:
    db = _symbol_db([_instrument(1, "600001.SH"), _instrument(2, "000002.SZ")])
    plan = PortfolioPlan(
        plan_id="p",
        holdings=[
            HoldingItem(symbol="600001.sh", weight=Decimal(3)),
            HoldingItem(symbol="000002.SZ", weight=Decimal(1)),
        ],
    )
    (item,) = await svc._normalize_request_plans(db, [plan], as_of=AS_OF)
    assert item.requested_holdings[0] == {"symbol": "600001.sh", "weight": "3"}
    assert item.quantized == {1: 75_000_000, 2: 25_000_000}
    assert item.summary["holdings"][0]["normalized_symbol"] == "600001.SH"


# ===========================================================================
# PA-03 意图
# ===========================================================================


def _plan_input(n_holdings: int, *, unresolved: float = 0.0) -> svc.PlanInput:
    return svc.PlanInput(
        plan_index=0,
        plan_id="p",
        label=None,
        requested_holdings=[],
        weight_mode="user",
        summary={
            "calculation_holdings": [{"instrument_id": i} for i in range(n_holdings)],
            "unresolved_weight": unresolved,
        },
        quantized={},
    )


@pytest.mark.parametrize(
    ("requested", "plans", "expected"),
    [
        (None, [_plan_input(1)], "single_instrument"),
        (None, [_plan_input(1, unresolved=0.2)], "single_portfolio"),
        (None, [_plan_input(3)], "single_portfolio"),
        ("single_portfolio", [_plan_input(1)], "single_portfolio"),
        (None, [_plan_input(1), _plan_input(2)], "multi_portfolio"),
    ],
)
def test_intent_resolution(
    requested: str | None, plans: list[svc.PlanInput], expected: str
) -> None:
    assert svc._resolve_intent(requested, plans) == expected


@pytest.mark.parametrize("intent", ["rebalance_amount", "rebalance_holding"])
def test_rebalance_intents_are_explicitly_not_available(intent: str) -> None:
    with pytest.raises(ApiError) as exc_info:
        svc._resolve_intent(intent, [_plan_input(1), _plan_input(1)])
    assert exc_info.value.issues[0]["code"] == "feature_not_available"


def test_single_instrument_with_unresolved_share_is_rejected() -> None:
    with pytest.raises(ApiError) as exc_info:
        svc._resolve_intent("single_instrument", [_plan_input(1, unresolved=0.5)])
    assert exc_info.value.issues[0]["path"] == "/intent"


@pytest.mark.parametrize(
    ("intent", "mode"),
    [
        ("single_portfolio", "standard"),
        ("single_instrument", "single_instrument"),
        ("multi_portfolio", "compare"),
    ],
)
def test_report_mode_mapping(intent: str, mode: str) -> None:
    assert svc._report_mode(intent) == mode


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["partially_succeeded", "failed"], "partially_succeeded"),
        (["failed", "failed"], "failed"),
        (["succeeded"], "succeeded"),
        ([None], "pending"),
        (["running", "failed"], "running"),
    ],
)
def test_run_status_uses_explicit_latest_run_statuses(
    statuses: list[str | None], expected: str
) -> None:
    assert svc._aggregate_run_status([{"status": status} for status in statuses]) == expected


# ===========================================================================
# PA-14、PA-15 I7 重算
# ===========================================================================


def _snapshot_row(owner: str | None) -> dict[str, Any]:
    return {
        "snapshot_id": uuid4(),
        "user_id": owner,
        "data_fingerprint": "dv-1",
        "data_snapshot_at": datetime(2026, 10, 29, 18, tzinfo=TZ),
        "resolved_spec_version": "v1",
        "resolved_as_of_date": AS_OF,
        "resolved_intent": "single_portfolio",
        "resolved_options": {},
    }


def _recompute_db(snapshot: dict[str, Any]) -> Any:
    return fake_db(
        [
            ("pg_advisory_xact_lock", lambda params: []),
            ("WHERE request_hash = %s", lambda params: []),
            ("FROM diag.portfolio_snapshot s", lambda params: [snapshot]),
        ]
    )


@pytest.mark.anyio
async def test_recompute_is_refused_until_the_base_data_version_is_reproducible() -> None:
    snapshot = _snapshot_row(owner=None)
    db = _recompute_db(snapshot)
    with pytest.raises(svc.BaseDataVersionUnavailableError) as exc_info:
        await svc.recompute_snapshot(
            db,
            snapshot["snapshot_id"],
            RecomputeRequest(),
            user_id=None,
            idempotency_key=str(uuid4()),
        )
    assert exc_info.value.http_status == 409
    assert exc_info.value.error_code == "BASE_DATA_VERSION_UNAVAILABLE"


@pytest.mark.anyio
async def test_recompute_checks_access_before_data_version() -> None:
    from gr_api.errors import Forbidden

    snapshot = _snapshot_row(owner=str(uuid4()))
    with pytest.raises(Forbidden):
        await svc.recompute_snapshot(
            _recompute_db(snapshot),
            snapshot["snapshot_id"],
            RecomputeRequest(),
            user_id=str(uuid4()),
        )


# ===========================================================================
# 路由
# ===========================================================================


def test_json_diagnosis_routes_declare_response_models() -> None:
    from fastapi.routing import APIRoute
    from gr_api.routers.diagnosis import router

    json_routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and not route.path.endswith("/stream")
    ]
    assert len(json_routes) == 9
    assert all(route.response_model is not None for route in json_routes)


def test_diagnosis_routes_keep_security_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """新增 diagnosis 路由后，SecurityHeadersMiddleware 仍覆盖它。

    DB 依赖被 override 掉，走正常 200 响应这条路径；未捕获异常由中间件之外的
    ServerErrorMiddleware 处理，本来就拿不到这几个头。
    """
    from fastapi import FastAPI
    from gr_api.deps import get_db
    from gr_api.middleware import SecurityHeadersMiddleware
    from gr_api.routers.diagnosis import router

    async def _fake_list(db: Any) -> list[dict[str, Any]]:
        return [
            {
                "spec_version": "v1-model-20261031",
                "factor_model": None,
                "factor_model_version": None,
                "params": {},
                "effective_from": date(2026, 10, 31),
                "effective_to": None,
                "is_active": True,
                # response_model 必须过滤内部列。
                "created_at": datetime(2026, 10, 31),
            }
        ]

    monkeypatch.setattr(svc, "list_spec_versions", _fake_list)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, csp_policy="default-src 'none'")
    app.include_router(router, prefix="/v1")

    async def _fake_db() -> Any:
        yield None

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/v1/diagnosis/spec-versions")

    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert "created_at" not in r.json()["data"]["items"][0]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in r.headers
