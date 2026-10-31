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
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GETRICH_TEST_PG") is None,
        reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
    ),
]

_TZ = ZoneInfo("Asia/Shanghai")
_AS_OF = date(2099, 1, 5)
_CALENDAR = [_AS_OF - timedelta(days=i) for i in range(8)]
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
                VALUES ('XSHG', %(day)s, TRUE)
                ON CONFLICT (exchange, trading_day) DO UPDATE SET is_open = TRUE
                """,
                [{"day": d} for d in _CALENDAR],
            )
            await cur.executemany(
                """
                INSERT INTO meta.instruments (symbol, asset, exchange, name, list_date, status)
                VALUES (%(symbol)s, 'stock', %(exchange)s, %(name)s, DATE '2090-01-01', 'active')
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
        await cur.execute("DELETE FROM meta.instruments WHERE name = %s", (_NAME,))
        await cur.execute(
            "DELETE FROM meta.trading_calendar WHERE exchange = 'XSHG' AND trading_day = ANY(%s)",
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
