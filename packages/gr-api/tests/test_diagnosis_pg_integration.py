"""持仓诊断打真实 PostgreSQL 的端到端用例。

默认跳过，需要真库时::

    GETRICH_TEST_PG=1 uv run pytest \
        packages/gr-api/tests/test_diagnosis_pg_integration.py -v

覆盖 ``diag`` 不在 search_path 时的完整 SQL、UUID 参数绑定、请求幂等、跨用户计算
复用、请求级数据隔离、范围校验、历史别名、重算拒绝及 5 方案 × 100 行上限。
测试数据都带 ``diagnosis-pg-test`` 标记，teardown 会清理。
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from gr_api.errors import ApiError, Conflict
from gr_api.schemas.diagnosis import (
    HoldingItem,
    PortfolioPlan,
    RecomputeRequest,
    SnapshotRequest,
)
from gr_api.services import diagnosis as svc
from gr_data.config import load_postgres
from gr_tools.config import load_environment


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from gr_data.db import DictConnection


pytestmark = [
    # 这些用例共用同一个真库并按业务键清理，在 xdist 下必须串行到同一 worker。
    pytest.mark.xdist_group("shared_pg"),
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GETRICH_TEST_PG") is None,
        reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
    ),
]

_TZ = ZoneInfo("Asia/Shanghai")
_AS_OF = date(2099, 1, 5)
# 连续自然日（含周末休市行）：历史收益要求日历完整，否则不判断相邻开市日。
_CALENDAR = [_AS_OF - timedelta(days=i) for i in range(220)]
_OPEN_DAYS = sorted(d for d in _CALENDAR if d.weekday() < 5)
_DATA_VERSION = "diagnosis-pg-test-20990105"
_SYMBOL_A = "888881.SH"
_SYMBOL_B = "888882.SZ"
_SYMBOL_BJ = "888883.BJ"
_ALIAS_OLD = "888884.SZ"  # 历史代码，只在 meta.symbol_map 中
_BULK = [f"8880{i:02d}.SH" for i in range(100)]
_NAME = "diagnosis-pg-test"
_EMAIL_PREFIX = "diagnosis-pg-test-"


def _dsn() -> str:
    cfg = load_postgres(load_environment())
    return f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"


async def _connect(*, autocommit: bool = False) -> DictConnection:
    """连接测试库；失败时不让 pytest traceback 打印含密码的 DSN。"""
    import psycopg
    from psycopg.rows import dict_row

    try:
        return await psycopg.AsyncConnection.connect(
            _dsn(),
            autocommit=autocommit,
            row_factory=dict_row,
            options="-c timezone=Asia/Shanghai -c search_path=app,market,meta,public",
        )
    except psycopg.OperationalError:
        pytest.fail(
            "unable to connect to PostgreSQL for diagnosis integration tests", pytrace=False
        )


@pytest.fixture
async def diagnosis_db(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[DictConnection, UUID, UUID]]:
    """准备两名用户、范围内外标的、历史别名、交易日和独立数据版本。"""
    monkeypatch.setattr(svc, "_today", lambda: date(2099, 1, 6))
    conn = await _connect()
    user_a = uuid4()
    user_b = uuid4()
    try:
        await _cleanup(conn)
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO app.users (id, email, password, name)
                VALUES (%(id)s, %(email)s, 'x', '诊断 PG 测试用户')
                """,
                [
                    {"id": user_a, "email": f"{_EMAIL_PREFIX}{user_a.hex}@example.invalid"},
                    {"id": user_b, "email": f"{_EMAIL_PREFIX}{user_b.hex}@example.invalid"},
                ],
            )
            await cur.executemany(
                """
                INSERT INTO meta.trading_calendar (exchange, trading_day, is_open)
                VALUES (%(exchange)s, %(day)s, %(open)s)
                ON CONFLICT (exchange, trading_day) DO UPDATE SET is_open = EXCLUDED.is_open
                """,
                [
                    {"exchange": exchange, "day": d, "open": d.weekday() < 5}
                    for exchange in ("XSHG", "XSHE")
                    for d in _CALENDAR
                ],
            )
            await cur.executemany(
                """
                INSERT INTO market.stock_suspend_coverage
                    (trading_day, source, raw_sha256, observed_at)
                VALUES (%(day)s, 'tushare', repeat('0', 64), now())
                ON CONFLICT DO NOTHING
                """,
                [{"day": d} for d in _OPEN_DAYS],
            )
            await cur.executemany(
                """
                INSERT INTO meta.instruments (symbol, asset, exchange, name, list_date, status)
                VALUES (%(symbol)s, 'stock', %(exchange)s, %(name)s, DATE '2098-01-02', 'active')
                """,
                [
                    {"symbol": _SYMBOL_A, "exchange": "XSHG", "name": _NAME},
                    {"symbol": _SYMBOL_B, "exchange": "XSHE", "name": _NAME},
                    {"symbol": _SYMBOL_BJ, "exchange": "XBSE", "name": _NAME},
                    *({"symbol": s, "exchange": "XSHG", "name": _NAME} for s in _BULK),
                ],
            )
            await cur.execute(
                """
                INSERT INTO meta.symbol_map (instrument_id, source, source_symbol)
                SELECT instrument_id, 'diagnosis-pg-test', %s
                FROM meta.instruments WHERE symbol = %s
                """,
                (_ALIAS_OLD, _SYMBOL_B),
            )
            await cur.execute(
                """
                INSERT INTO diag.data_version (data_version_id, snapshot_at, schemas_covered)
                VALUES (%s, %s, ARRAY['market', 'meta', 'classify'])
                """,
                (_DATA_VERSION, datetime(2099, 1, 5, 18, 0, tzinfo=_TZ)),
            )
        await conn.commit()
        yield conn, user_a, user_b
    finally:
        await conn.rollback()
        await _cleanup(conn)
        await conn.close()


async def _cleanup(conn: DictConnection) -> None:
    """只删除本文件创建的数据。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM diag.portfolio_snapshot WHERE data_fingerprint = %s", (_DATA_VERSION,)
        )
        await cur.execute(
            "DELETE FROM diag.diagnosis_run WHERE data_fingerprint = %s", (_DATA_VERSION,)
        )
        await cur.execute(
            "DELETE FROM diag.data_version WHERE data_version_id = %s", (_DATA_VERSION,)
        )
        await cur.execute("DELETE FROM meta.symbol_map WHERE source = 'diagnosis-pg-test'")
        await cur.execute(
            """
            DELETE FROM market.stock_bar_1d WHERE instrument_id IN (
                SELECT instrument_id FROM meta.instruments WHERE name = %s
            )
            """,
            (_NAME,),
        )
        await cur.execute("DELETE FROM meta.instruments WHERE name = %s", (_NAME,))
        await cur.execute(
            "DELETE FROM meta.trading_calendar WHERE exchange IN ('XSHG', 'XSHE') "
            "AND trading_day = ANY(%s)",
            (_CALENDAR,),
        )
        await cur.execute(
            "DELETE FROM market.stock_suspend_coverage WHERE source = 'tushare' "
            "AND trading_day = ANY(%s)",
            (_CALENDAR,),
        )
        await cur.execute("DELETE FROM app.users WHERE email LIKE %s", (f"{_EMAIL_PREFIX}%",))
    await conn.commit()


def _request(
    plan_id: str,
    holdings: list[HoldingItem],
    *,
    label: str | None = None,
) -> SnapshotRequest:
    return SnapshotRequest(
        plans=[PortfolioPlan(plan_id=plan_id, label=label, holdings=holdings)],
        as_of_date=_AS_OF,
    )


async def test_sql_end_to_end_cache_reuse_and_request_isolation(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    db, user_a, user_b = diagnosis_db
    request_a = _request(
        "before",
        [
            HoldingItem(symbol=_SYMBOL_A, weight=Decimal(50)),
            HoldingItem(symbol="GARBAGE", weight=Decimal(50)),
        ],
        label="before",
    )
    request_b = _request(
        "my-portfolio", [HoldingItem(symbol=_SYMBOL_A, weight=Decimal(100))], label="mine"
    )

    accepted_a, status_a = await svc.create_snapshot(db, request_a, user_id=str(user_a))
    key = str(uuid4())
    accepted_b, status_b = await svc.create_snapshot(
        db, request_b, user_id=str(user_b), idempotency_key=key
    )
    repeated_b, repeated_status = await svc.create_snapshot(
        db, request_b, user_id=str(user_b), idempotency_key=key
    )

    assert (status_a, status_b, repeated_status) == (201, 201, 200)
    assert repeated_b["snapshot_id"] == accepted_b["snapshot_id"]

    result_a = await svc.get_result(db, UUID(accepted_a["snapshot_id"]), user_id=str(user_a))
    result_b = await svc.get_result(db, UUID(accepted_b["snapshot_id"]), user_id=str(user_b))
    report_b = await svc.get_report(db, UUID(accepted_b["snapshot_id"]), user_id=str(user_b))

    plan_a = result_a["plans"][0]
    plan_b = result_b["plans"][0]
    assert plan_a["plan_id"] == "before"
    assert any(i["code"] == "unresolved" for i in result_a["data_quality"]["plans"][0]["issues"])
    assert plan_a["input"]["calculation_coverage_ratio"] == 0.5
    # 同一共享载体，状态按各自覆盖率判定（§7.8 缓存纯度验收例）
    assert plan_a["section_a"]["value"]["topn"]["status"] == "unavailable"
    assert plan_b["section_a"]["value"]["topn"]["value"][0]["weight"] == 1.0
    assert plan_b["plan_id"] == "my-portfolio"
    assert plan_b["label"] == "mine"
    assert plan_b["input"]["calculation_coverage_ratio"] == 1.0
    assert result_b["data_fingerprint"] == _DATA_VERSION
    assert result_b["options"]["correlation_window"]["end"] == _AS_OF.isoformat()
    assert report_b["snapshot_id"] == accepted_b["snapshot_id"]

    async with db.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*)::int AS runs FROM diag.diagnosis_run WHERE data_fingerprint = %s",
            (_DATA_VERSION,),
        )
        row = await cur.fetchone()
    assert row is not None and row["runs"] == 1


async def test_equal_weight_baseline_metrics_on_real_sql(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    db, user_a, _user_b = diagnosis_db
    request = _request("pair", [HoldingItem(symbol=_SYMBOL_A), HoldingItem(symbol=_SYMBOL_B)])

    accepted, status = await svc.create_snapshot(db, request, user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    section_a = result["plans"][0]["section_a"]["value"]

    assert status == 201
    assert section_a["l1_count"]["value"] == 2
    assert section_a["hhi"]["value"] == pytest.approx(0.5)
    assert section_a["l2_effective_count"]["value"] == pytest.approx(2.0)
    assert [t["weight"] for t in section_a["topn"]["value"]] == [0.5, 1.0, 1.0]
    # 无估值数据：分布全落缺失档并降级，不判不可用
    assert section_a["mktcap_distribution"]["value"]["missing_or_invalid"] == 1.0
    assert section_a["mktcap_distribution"]["status"] == "degraded"
    assert section_a["industry_distribution"]["reason_code"] == "data_not_validated"


async def test_historical_alias_and_out_of_scope_assets(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    db, user_a, _ = diagnosis_db
    alias = _request("alias", [HoldingItem(symbol=_ALIAS_OLD), HoldingItem(symbol=_SYMBOL_B)])
    accepted, _ = await svc.create_snapshot(db, alias, user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    holdings = result["plans"][0]["input"]["holdings"]
    assert [h["status"] for h in holdings] == ["resolved", "duplicate"]
    assert result["resolved_intent"] == "single_instrument"

    beijing = _request("bj", [HoldingItem(symbol=_SYMBOL_A), HoldingItem(symbol=_SYMBOL_BJ)])
    with pytest.raises(ApiError) as exc_info:
        await svc.create_snapshot(db, beijing, user_id=str(user_a))
    assert exc_info.value.http_status == 422
    assert exc_info.value.issues[0]["path"] == "/plans/0/holdings/1/symbol"


async def test_history_date_is_rejected_and_recompute_is_refused(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    db, user_a, user_b = diagnosis_db
    early = SnapshotRequest(
        plans=[PortfolioPlan(plan_id="p", holdings=[HoldingItem(symbol=_SYMBOL_A)])],
        as_of_date=_AS_OF - timedelta(days=1),
    )
    with pytest.raises(ApiError) as exc_info:
        await svc.create_snapshot(db, early, user_id=str(user_a))
    assert exc_info.value.issues[0]["code"] == "feature_not_available"

    accepted, _ = await svc.create_snapshot(
        db, _request("p", [HoldingItem(symbol=_SYMBOL_A)]), user_id=str(user_a)
    )
    snapshot_id = UUID(accepted["snapshot_id"])
    with pytest.raises(svc.BaseDataVersionUnavailableError):
        await svc.recompute_snapshot(db, snapshot_id, RecomputeRequest(), user_id=str(user_a))
    from gr_api.errors import Forbidden

    with pytest.raises(Forbidden):
        await svc.recompute_snapshot(db, snapshot_id, RecomputeRequest(), user_id=str(user_b))


async def test_recompute_path_creates_linked_snapshot_when_base_is_available(
    diagnosis_db: tuple[DictConnection, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-022 2b 落地后的成功路径：沿用原方案、日期与数据版本，只覆盖给出的选项。"""
    db, user_a, _ = diagnosis_db
    accepted, _ = await svc.create_snapshot(
        db,
        _request("p", [HoldingItem(symbol=_SYMBOL_A, weight=Decimal(1))], label="mine"),
        user_id=str(user_a),
    )
    base_id = UUID(accepted["snapshot_id"])

    async def available(*_args: object) -> bool:
        return True

    monkeypatch.setattr(svc, "_base_data_version_available", available)
    body = RecomputeRequest.model_validate(
        {"options": {"correlation_window": {"start": "2099-01-01", "end": "2099-01-05"}}}
    )
    key = str(uuid4())
    recomputed, status = await svc.recompute_snapshot(
        db, base_id, body, user_id=str(user_a), idempotency_key=key
    )
    replay, replay_status = await svc.recompute_snapshot(
        db, base_id, body, user_id=str(user_a), idempotency_key=key
    )
    with pytest.raises(Conflict):
        await svc.recompute_snapshot(
            db, base_id, RecomputeRequest(), user_id=str(user_a), idempotency_key=key
        )

    assert (status, replay_status) == (201, 200)
    assert replay["snapshot_id"] == recomputed["snapshot_id"] != str(base_id)
    result = await svc.get_result(db, UUID(recomputed["snapshot_id"]), user_id=str(user_a))
    base = await svc.get_result(db, base_id, user_id=str(user_a))
    assert result["base_snapshot_id"] == str(base_id)
    assert result["options"]["correlation_window"] == {"start": "2099-01-01", "end": "2099-01-05"}
    assert result["options"]["beta_window"] == base["options"]["beta_window"]
    assert result["plans"][0]["label"] == "mine"
    assert result["data_fingerprint"] == base["data_fingerprint"]


async def test_five_plans_with_one_hundred_rows_each(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    """PA-02/PA-03 输入上限的边界验收；不作为性能达标证据。"""
    db, user_a, _ = diagnosis_db
    plans = [
        PortfolioPlan(
            plan_id=f"p{p}",
            holdings=[
                HoldingItem(symbol=s, weight=Decimal(1 + (i + p) % 7)) for i, s in enumerate(_BULK)
            ],
        )
        for p in range(5)
    ]
    request = SnapshotRequest(plans=plans, as_of_date=_AS_OF)
    accepted, status = await svc.create_snapshot(db, request, user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))

    assert status == 201
    assert result["resolved_intent"] == "multi_portfolio"
    assert [p["section_a"]["value"]["l1_count"]["value"] for p in result["plans"]] == [100] * 5
    assert result["comparison"]["reason_code"] == "feature_not_available"


async def test_concurrent_authenticated_requests_are_idempotent(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    _db, user_a, _user_b = diagnosis_db
    request = _request("concurrent", [HoldingItem(symbol=_SYMBOL_A)])
    key = str(uuid4())

    async def submit() -> tuple[dict, int]:
        conn = await _connect(autocommit=True)
        try:
            return await svc.create_snapshot(
                conn, request, user_id=str(user_a), idempotency_key=key
            )
        finally:
            await conn.close()

    left, right = await asyncio.gather(submit(), submit())

    assert left[0]["snapshot_id"] == right[0]["snapshot_id"]
    assert sorted((left[1], right[1])) == [200, 201]


async def test_new_resources_key_conflict_and_failed_plan_isolation(diagnosis_db, monkeypatch):
    db, user_a, _ = diagnosis_db
    req = _request("p", [HoldingItem(symbol=_SYMBOL_A)])
    first, _ = await svc.create_snapshot(db, req, user_id=str(user_a))
    second, _ = await svc.create_snapshot(db, req, user_id=str(user_a))
    assert first["snapshot_id"] != second["snapshot_id"]
    key = str(uuid4())
    await svc.create_snapshot(db, req, user_id=str(user_a), idempotency_key=key)
    different = _request("renamed", [HoldingItem(symbol=_SYMBOL_A)])
    with pytest.raises(Conflict):
        await svc.create_snapshot(db, different, user_id=str(user_a), idempotency_key=key)

    original = svc._compute_plan

    async def faulty(*args, **kwargs):
        if kwargs["item"].plan_id == "broken":
            raise RuntimeError("private diagnostic detail must not appear in response")
        return await original(*args, **kwargs)

    monkeypatch.setattr(svc, "_compute_plan", faulty)
    pair = SnapshotRequest(
        plans=[
            req.plans[0],
            PortfolioPlan(plan_id="broken", holdings=[HoldingItem(symbol=_SYMBOL_B)]),
        ],
        as_of_date=_AS_OF,
    )
    submitted, _ = await svc.create_snapshot(db, pair, user_id=str(user_a))
    result = await svc.get_result(db, UUID(submitted["snapshot_id"]), user_id=str(user_a))
    assert result["run_status"] == "partially_succeeded"
    assert result["plans"][1]["run_status"] == "failed"
    assert "private diagnostic detail" not in str(result)
    assert result["comparison"]["reason_code"] == "feature_not_available"
    monkeypatch.setattr(svc, "_compute_plan", original)
    retry, _ = await svc.create_snapshot(db, pair, user_id=str(user_a))
    retried = await svc.get_result(db, UUID(retry["snapshot_id"]), user_id=str(user_a))
    assert retried["plans"][1]["section_a"]["status"] == "ready"
    original_result = await svc.get_result(db, UUID(submitted["snapshot_id"]), user_id=str(user_a))
    assert original_result == result


async def test_key_replay_uses_original_snapshot_before_resolving_latest_data(
    diagnosis_db, monkeypatch
):
    db, user_a, _ = diagnosis_db
    key = str(uuid4())
    req = _request("frozen", [HoldingItem(symbol=_SYMBOL_A)])
    first, _ = await svc.create_snapshot(db, req, user_id=str(user_a), idempotency_key=key)

    async def no_latest_data(*args, **kwargs):
        raise AssertionError("replay must not resolve the current data version")

    monkeypatch.setattr(svc, "get_data_version", no_latest_data)
    replay, code = await svc.create_snapshot(db, req, user_id=str(user_a), idempotency_key=key)
    assert code == 200
    assert replay == first


async def test_historical_correlation_and_volatility_on_real_sql(
    diagnosis_db: tuple[DictConnection, UUID, UUID],
) -> None:
    """日线 + 复权因子 + 停复牌覆盖的真实 SQL 路径：B 波动率与 D 历史相关性出数。"""
    db, user_a, _ = diagnosis_db
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT symbol, instrument_id FROM meta.instruments WHERE symbol = ANY(%s)",
            ([_SYMBOL_A, _SYMBOL_B],),
        )
        ids = {r["symbol"]: r["instrument_id"] for r in await cur.fetchall()}
        rows = []
        price_a, price_b = Decimal(10), Decimal(20)
        for i, day in enumerate(_OPEN_DAYS):
            step = Decimal("1.01") if i % 2 else Decimal("0.995")
            price_a *= step
            price_b *= step * step  # 与 A 同向，日收益不同但高度相关
            for symbol, price in ((_SYMBOL_A, price_a), (_SYMBOL_B, price_b)):
                rows.append(
                    {
                        "id": ids[symbol],
                        "dt": day,
                        "close": price.quantize(Decimal("0.000001")),
                        # 复权因子在中途翻倍、价格减半：复权收盘价连续，不能当成 -50% 收益
                        "factor": Decimal(2) if i >= 60 else Decimal(1),
                    }
                )
        for row in rows:
            if row["factor"] == 2:
                row["close"] = (row["close"] / 2).quantize(Decimal("0.000001"))
        await cur.executemany(
            """
            INSERT INTO market.stock_bar_1d (
                instrument_id, dt, trading_day, close, adj_factor, trading_status, source
            ) VALUES (%(id)s, %(dt)s, %(dt)s, %(close)s, %(factor)s, 'NORMAL', 'tushare')
            """,
            rows,
        )
    await db.commit()

    request = _request("hist", [HoldingItem(symbol=_SYMBOL_A), HoldingItem(symbol=_SYMBOL_B)])
    accepted, _ = await svc.create_snapshot(db, request, user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    plan = result["plans"][0]

    betas = plan["section_b"]["value"]["instrument_betas"]["value"]
    vol = betas[0]["historical_volatility"]
    assert vol["status"] == "ok"
    assert vol["sample_count"] == len(_OPEN_DAYS) - 1
    assert vol["value"] < 0.5  # 复权衔接正确时不会出现 -50% 的单日收益
    correlation = plan["section_d"]["value"]["correlation"]["by_method"]["historical"]
    assert correlation["status"] == "ok"
    assert correlation["value"]["matrix"][0][1] > 0.99
    assert plan["cov"]["computed"] == ["historical"]
    assert plan["cov"]["primary"] is None
    pairs = plan["section_d"]["value"]["high_correlation_pairs"]["by_method"]["historical"]
    assert len(pairs["value"]) == 1
    report = await svc.get_report(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    kinds = {s["section_id"]: s["content"]["status"] for s in report["sections"]}
    assert kinds["hist:risk"] == kinds["hist:diversification"] == "ready"


async def test_model_risk_path_with_injected_risk_model(
    diagnosis_db: tuple[DictConnection, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """注入风险截面走完整服务路径：模型身份回显、B／D 模型口径出数、未识别份额时整体阻断。"""
    import numpy as np
    from gr_api.diagnosis_calc.model_risk import RiskModelInputs

    db, user_a, _ = diagnosis_db
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT symbol, instrument_id FROM meta.instruments WHERE symbol = ANY(%s)",
            ([_SYMBOL_A, _SYMBOL_B],),
        )
        ids = {r["symbol"]: r["instrument_id"] for r in await cur.fetchall()}

    async def loaded(*_args: object, **_kwargs: object) -> svc.LoadedRiskModel:
        return svc.LoadedRiskModel(
            inputs=RiskModelInputs(
                factor_codes=("comovement", "size"),
                factor_covariance=np.array([[0.04, 0.002], [0.002, 0.01]]),
                exposures={
                    ids[_SYMBOL_A]: np.array([1.0, 0.5]),
                    ids[_SYMBOL_B]: np.array([0.9, -0.3]),
                },
                specific_variance={ids[_SYMBOL_A]: 0.02, ids[_SYMBOL_B]: 0.03},
                market_factor="comovement",
                style_factors=frozenset({"size"}),
            ),
            model_id="rq_test_model",
            model_version="v2",
            model_date=_AS_OF,
        )

    monkeypatch.setattr(svc, "_load_risk_model", loaded)
    pair = [
        HoldingItem(symbol=_SYMBOL_A, weight=Decimal(60)),
        HoldingItem(symbol=_SYMBOL_B, weight=Decimal(40)),
    ]
    accepted, _ = await svc.create_snapshot(db, _request("model", pair), user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    plan = result["plans"][0]
    assert plan["cov"]["forward_model"] == {
        "model_id": "rq_test_model",
        "model_version": "v2",
        "model_date": _AS_OF.isoformat(),
    }
    assert plan["cov"]["primary"] == "forward"
    assert "forward" in plan["cov"]["computed"]
    risk = plan["section_b"]["value"]
    vol = risk["volatility"]["by_method"]["forward"]["value"]
    w = np.array([0.6, 0.4])
    b = np.array([[1.0, 0.5], [0.9, -0.3]])
    sigma = b @ np.array([[0.04, 0.002], [0.002, 0.01]]) @ b.T + np.diag([0.02, 0.03])
    assert vol == pytest.approx(float(np.sqrt(w @ sigma @ w)))
    assert risk["l4_effective_count"]["status"] == "ok"
    assert plan["section_d"]["value"]["style_exposure"]["value"] == pytest.approx(
        {"size": 0.6 * 0.5 + 0.4 * -0.3}
    )
    assert any("rq_test_model" in text for text in result["disclosures"])
    report = await svc.get_report(
        db, UUID(accepted["snapshot_id"]), user_id=str(user_a), user_level="pro"
    )
    risk_blocks = {s["section_id"]: s for s in report["sections"]}["model:risk"]["content"]
    assert risk_blocks["status"] == "ready"

    partial = [*pair, HoldingItem(symbol="GARBAGE", weight=Decimal(10))]
    accepted, _ = await svc.create_snapshot(db, _request("partial", partial), user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    risk = result["plans"][0]["section_b"]["value"]
    assert risk["volatility"]["by_method"]["forward"]["reason_code"] == "coverage_below_threshold"
    assert risk["l3_effective_count"]["reason_code"] == "coverage_below_threshold"
