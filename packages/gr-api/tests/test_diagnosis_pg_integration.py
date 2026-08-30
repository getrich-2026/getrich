"""持仓诊断打真实 PostgreSQL 的端到端用例。

默认跳过，需要真库时::

    GETRICH_TEST_PG=1 uv run pytest \
        packages/gr-api/tests/test_diagnosis_pg_integration.py -v

覆盖 ``diag`` 不在 search_path 时的完整 SQL、UUID 参数绑定、请求幂等、跨用户计算
复用及请求级数据隔离。测试数据都带 ``diagnosis-pg-test`` 标记，teardown 会清理。
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from gr_api.schemas.diagnosis import HoldingItem, PortfolioPlan, SnapshotRequest
from gr_api.services import diagnosis as svc
from gr_data.config import settings


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GETRICH_TEST_PG") is None,
        reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
    ),
]

_AS_OF = date(2099, 1, 5)
_DATA_VERSION = "diagnosis-pg-test-20990105"
_SYMBOL_A = "888881.SH"
_SYMBOL_B = "888882.SZ"
_EMAIL_PREFIX = "diagnosis-pg-test-"


def _dsn() -> str:
    cfg = settings.postgres
    return f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"


async def _connect(*, autocommit: bool = False) -> AsyncConnection:
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
async def diagnosis_db() -> AsyncIterator[tuple[AsyncConnection, UUID, UUID]]:
    """准备两名用户、两只标的、交易日和独立数据版本。"""
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
            await cur.execute(
                """
                INSERT INTO meta.trading_calendar (exchange, trading_day, is_open)
                VALUES ('XSHG', %s, TRUE)
                ON CONFLICT (exchange, trading_day) DO UPDATE SET is_open = TRUE
                """,
                (_AS_OF,),
            )
            await cur.executemany(
                """
                INSERT INTO meta.instruments (
                    symbol, asset, exchange, name, list_date, status
                ) VALUES (
                    %(symbol)s, 'stock', %(exchange)s,
                    'diagnosis-pg-test', DATE '2090-01-01', 'active'
                )
                """,
                [
                    {"symbol": _SYMBOL_A, "exchange": "XSHG"},
                    {"symbol": _SYMBOL_B, "exchange": "XSHE"},
                ],
            )
            await cur.execute(
                """
                INSERT INTO diag.data_version (
                    data_version_id, snapshot_at, schemas_covered
                ) VALUES (%s, %s, ARRAY['market', 'meta', 'classify'])
                """,
                (_DATA_VERSION, datetime(2099, 1, 5, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
            )
        await conn.commit()
        yield conn, user_a, user_b
    finally:
        await _cleanup(conn)
        await conn.close()


async def _cleanup(conn: AsyncConnection) -> None:
    """只删除本文件创建的数据。"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM diag.portfolio_snapshot
            WHERE user_id IN (
                SELECT id FROM app.users WHERE email LIKE %s
            )
            """,
            (f"{_EMAIL_PREFIX}%",),
        )
        await cur.execute(
            "DELETE FROM diag.diagnosis_run WHERE data_fingerprint = %s",
            (_DATA_VERSION,),
        )
        await cur.execute(
            "DELETE FROM diag.data_version WHERE data_version_id = %s",
            (_DATA_VERSION,),
        )
        await cur.execute(
            "DELETE FROM meta.instruments WHERE name = 'diagnosis-pg-test'",
        )
        await cur.execute(
            "DELETE FROM meta.trading_calendar WHERE exchange = 'XSHG' AND trading_day = %s",
            (_AS_OF,),
        )
        await cur.execute(
            "DELETE FROM app.users WHERE email LIKE %s",
            (f"{_EMAIL_PREFIX}%",),
        )
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
    diagnosis_db: tuple[AsyncConnection, UUID, UUID],
) -> None:
    db, user_a, user_b = diagnosis_db
    request_a = _request(
        "before",
        [
            HoldingItem(symbol=_SYMBOL_A, weight=50),
            HoldingItem(symbol="GARBAGE", weight=50),
        ],
        label="before",
    )
    request_b = _request(
        "my-portfolio",
        [HoldingItem(symbol=_SYMBOL_A, weight=100)],
        label="mine",
    )

    accepted_a, status_a = await svc.create_snapshot(db, request_a, user_id=str(user_a))
    accepted_b, status_b = await svc.create_snapshot(db, request_b, user_id=str(user_b))
    repeated_b, repeated_status = await svc.create_snapshot(db, request_b, user_id=str(user_b))

    assert (status_a, status_b, repeated_status) == (201, 201, 200)
    assert repeated_b["snapshot_id"] == accepted_b["snapshot_id"]

    result_a = await svc.get_result(db, UUID(accepted_a["snapshot_id"]), user_id=str(user_a))
    result_b = await svc.get_result(db, UUID(accepted_b["snapshot_id"]), user_id=str(user_b))
    report_b = await svc.get_report(db, UUID(accepted_b["snapshot_id"]), user_id=str(user_b))

    assert result_a["plans"][0]["plan_id"] == "before"
    assert result_a["data_quality"]["unresolved_symbols"] == ["GARBAGE"]
    assert result_a["plans"][0]["section_a"]["calculation_coverage_ratio"] == 0.5
    assert result_b["plans"][0]["plan_id"] == "my-portfolio"
    assert result_b["plans"][0]["label"] == "mine"
    assert result_b["data_quality"]["unresolved_symbols"] == []
    assert result_b["plans"][0]["section_a"]["calculation_coverage_ratio"] == 1.0
    assert report_b["snapshot_id"] == accepted_b["snapshot_id"]

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT COUNT(*)::int AS runs
            FROM diag.diagnosis_run
            WHERE data_fingerprint = %s
            """,
            (_DATA_VERSION,),
        )
        row = await cur.fetchone()
    assert row["runs"] == 1


async def test_equal_weight_baseline_metrics_on_real_sql(
    diagnosis_db: tuple[AsyncConnection, UUID, UUID],
) -> None:
    db, user_a, _user_b = diagnosis_db
    request = _request(
        "pair",
        [HoldingItem(symbol=_SYMBOL_A), HoldingItem(symbol=_SYMBOL_B)],
    )

    accepted, status = await svc.create_snapshot(db, request, user_id=str(user_a))
    result = await svc.get_result(db, UUID(accepted["snapshot_id"]), user_id=str(user_a))
    section_a = result["plans"][0]["section_a"]

    assert status == 201
    assert section_a["l1_count"]["value"] == 2
    assert section_a["hhi"]["value"] == pytest.approx(0.5)
    assert section_a["l2_effective_count"]["value"] == pytest.approx(2.0)
    assert section_a["topn"]["value"] == pytest.approx(1.0)


async def test_concurrent_authenticated_requests_are_idempotent(
    diagnosis_db: tuple[AsyncConnection, UUID, UUID],
) -> None:
    _db, user_a, _user_b = diagnosis_db
    request = _request("concurrent", [HoldingItem(symbol=_SYMBOL_A)])

    async def submit() -> tuple[dict, int]:
        conn = await _connect(autocommit=True)
        try:
            return await svc.create_snapshot(conn, request, user_id=str(user_a))
        finally:
            await conn.close()

    left, right = await asyncio.gather(submit(), submit())

    assert left[0]["snapshot_id"] == right[0]["snapshot_id"]
    assert sorted((left[1], right[1])) == [200, 201]
