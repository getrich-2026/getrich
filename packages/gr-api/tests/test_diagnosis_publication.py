"""发布读取的清理与单日范围回归；实际并发PG/HTTP由隔离验收执行。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from gr_api.diagnosis_calc.exposure import CalcHolding
from gr_api.diagnosis_calc.model_risk import RiskModelInputs
from gr_api.schemas.diagnosis_response import MetricValue
from gr_api.services import diagnosis as svc, diagnosis_publication as pub
from psycopg.pq import TransactionStatus


class Connection:
    def __init__(self, *, unlock_ok: bool = True) -> None:
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.autocommit = False
        self.isolation_level = None
        self.timeout = "1729ms"
        self.closed = False
        self.locked = False
        self.unlock_ok = unlock_ok
        self.last = ""

    async def set_autocommit(self, value):
        self.autocommit = value

    async def set_isolation_level(self, value):
        self.isolation_level = value

    async def execute(self, query, params=None):
        self.last = query
        if "pg_try_advisory_lock_shared" in query:
            self.locked = True
        if "pg_advisory_unlock_shared" in query:
            self.locked = False
        if "set_config" in query:
            assert params is not None
            self.timeout = params[0]
        if query.startswith("SET"):
            self.timeout = "30s"

    async def fetchone(self):
        return (
            {"statement_timeout": "1729ms"}
            if self.last.startswith("SHOW")
            else (
                {"acquired": True}
                if "pg_try_advisory_lock" in self.last
                else {"unlocked": self.unlock_ok}
            )
        )

    async def rollback(self):
        pass

    async def close(self):
        self.closed = True
        self.locked = False

    @asynccontextmanager
    async def transaction(self):
        yield

    @asynccontextmanager
    async def cursor(self):
        yield self


@pytest.mark.anyio
async def test_cancel_releases_lock_restores_connection_and_context():
    conn: Any = Connection()
    started = asyncio.Event()

    async def request():
        async with pub.consistent_read(conn):
            assert pub.enabled.get()
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(request())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not conn.locked
    assert not conn.closed
    assert conn.autocommit is False
    assert conn.isolation_level is None
    assert conn.timeout == "1729ms"
    assert not pub.enabled.get()
    assert pub.current.get() is None


@pytest.mark.anyio
async def test_unconfirmed_unlock_discards_connection():
    conn: Any = Connection(unlock_ok=False)
    with pytest.raises(RuntimeError, match="release was not confirmed"):
        async with pub.consistent_read(conn):
            pass
    assert conn.closed


@pytest.mark.anyio
async def test_existing_transaction_is_never_committed_or_reused():
    conn: Any = Connection()
    conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(RuntimeError, match="idle dedicated"):
        async with pub.consistent_read(conn):
            pass
    assert conn.last == ""


def test_scoped_variance_keeps_annual_volatility_and_blocks_unverified_metrics():
    inputs = RiskModelInputs(
        ("f",), np.array([[0.04]]), {1: np.array([1.0]), 2: np.array([2.0])}, {1: 0.01, 2: 0.02}
    )
    loaded = svc.LoadedRiskModel(
        inputs,
        "m",
        "v",
        date(2026, 11, 5),
        {
            "metrics": ["volatility", "annual_variance", "daily_prediction_volatility"],
            "calibrated": False,
            "run_id": "run",
            "receipt_id": "receipt",
            "units_evidence": {"F": "annual"},
        },
    )
    model = svc._scoped_risk([CalcHolding(1, Decimal(".4")), CalcHolding(2, Decimal(".6"))], loaded)
    annual = 1.6**2 * 0.04 + 0.4**2 * 0.01 + 0.6**2 * 0.02
    assert model.volatility["value"] == pytest.approx(annual**0.5)
    assert model.facts["annual_variance"] == pytest.approx(annual)
    assert model.facts["daily_prediction_volatility"] == pytest.approx((annual / 252) ** 0.5)
    MetricValue[float].model_validate(model.volatility)
    assert model.volatility["status"] == "degraded"
    assert model.l4_effective_count["status"] == "unavailable"
    assert model.correlation["status"] == "unavailable"


def test_scoped_result_serializes_complete_calculation_payload():
    """使用落库载体校验单日degraded原因码，防止纯计算成功而整个方案失败。"""
    from gr_api.diagnosis_calc.metrics import degraded, unavailable
    from gr_api.diagnosis_calc.sections import risk_section
    from gr_api.schemas.diagnosis_response import CalculationPayload

    inputs = RiskModelInputs(("f",), np.array([[0.04]]), {1: np.array([1.0])}, {1: 0.01})
    loaded = svc.LoadedRiskModel(
        inputs,
        "m",
        "v",
        date(2026, 11, 5),
        {
            "metrics": ["volatility", "annual_variance", "daily_prediction_volatility"],
            "calibrated": False,
            "run_id": "run",
            "receipt_id": "receipt",
            "units_evidence": {"F": "annual"},
        },
    )
    model = svc._scoped_risk([CalcHolding(1, Decimal(1))], loaded)
    na = unavailable(reason_code="data_not_validated", reason="not admitted")
    risk = risk_section([1], {1: na}, model)
    for name in ("annual_variance", "daily_prediction_volatility"):
        risk[name] = degraded(
            model.facts[name], method="forward", reason_code="not_calibrated", reason="全区间未校准"
        )
    risk.update(annualization_days=252, model_run_id="run", calibrated=False)
    section = {
        "status": "unavailable",
        "reason_code": "data_not_validated",
        "reason": "not admitted",
    }
    payload = CalculationPayload.model_validate(
        {
            "cov": {
                "requested": ["forward"],
                "computed": ["forward"],
                "primary": "forward",
                "forward_model": {
                    "model_id": "m",
                    "model_version": "v",
                    "model_date": "2026-11-05",
                },
            },
            "section_a": section,
            "section_b": {"status": "ready", "value": risk},
            "section_c": section,
            "section_d": section,
            "stress_scenarios": section,
        }
    )
    restored = CalculationPayload.model_validate_json(payload.model_dump_json())
    data = restored.model_dump(mode="json")["section_b"]["value"]
    assert data["annual_variance"]["value"] == pytest.approx(0.05)
    assert data["volatility"]["by_method"]["forward"]["value"] == pytest.approx(0.05**0.5)
    assert data["daily_prediction_volatility"]["value"] == pytest.approx((0.05 / 252) ** 0.5)
    assert data["calibrated"] is False
    from gr_api.services.diagnosis_presentation import _model_blocks

    cards = _model_blocks(data, {"1": "证券"}, "retail")[0]["items"]
    by_id = {card["metric_id"]: card for card in cards}
    assert by_id["volatility.forward"]["value"]["value"] == pytest.approx(0.05**0.5)
    assert by_id["daily_prediction_volatility"]["value"]["value"] == pytest.approx(
        (0.05 / 252) ** 0.5
    )
    assert by_id["daily_prediction_volatility"]["decimals"] == 6


@pytest.mark.anyio
async def test_real_binary_protocol_preserves_stored_variance_precision():
    """真实隔离PG核对REAL提升值；默认不连接工作库或自动建立测试库。"""
    import os
    from dataclasses import replace

    import psycopg
    from gr_data.config import load_postgres, make_pg_dsn
    from gr_data.db import DictConnection
    from gr_tools.config import load_environment
    from psycopg.rows import dict_row

    database = os.environ.get("GETRICH_DIAG_ISOLATED_DB")
    if not database:
        pytest.skip("requires explicit isolated diagnostic PostgreSQL database")
    if not database.startswith("getrich_diag_"):
        pytest.fail("test refuses non-isolated database", pytrace=False)
    cfg = replace(load_postgres(load_environment()), database=database)
    try:
        conn = await DictConnection.connect(make_pg_dsn(cfg), autocommit=True, row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.fail("isolated PostgreSQL connection unavailable", pytrace=False)
    async with conn:
        await conn.execute("SET default_transaction_read_only=on")
        query = "SELECT '4.2974834'::real AS stored,'4.2974834'::real::double precision AS promoted"
        async with conn.cursor(binary=True) as cursor:
            await cursor.execute(query)
            binary = await cursor.fetchone()
        async with conn.cursor() as cursor:
            await cursor.execute(query)
            text = await cursor.fetchone()
        assert binary is not None and text is not None
        assert binary["stored"] == binary["promoted"]
        assert text["stored"] != text["promoted"]
        assert abs(binary["stored"] - text["stored"]) > 1e-12


@pytest.mark.anyio
async def test_anyio_cancel_scope_runs_bounded_cleanup_before_pool_reuse():
    """Starlette级别取消会重复注入；清理完成后才允许连接被池复用。"""
    import anyio

    class SlowConnection(Connection):
        async def rollback(self):
            await anyio.sleep(0.01)

    conn: Any = SlowConnection()
    with anyio.CancelScope() as scope:
        async with pub.consistent_read(conn, mutation=True):
            scope.cancel()
            await anyio.sleep(0)
    assert conn.timeout == "1729ms"
    assert conn.autocommit is False
    assert not conn.locked
    assert not conn.closed
    assert pub.current.get() is None
    assert not pub.enabled.get()


@pytest.mark.anyio
async def test_cancel_while_waiting_for_writer_does_not_leave_mutation_lock():
    """等输入writer时只执行非阻塞探测，取消后释放已取得的mutation锁。"""
    attempted = asyncio.Event()

    class WaitingConnection(Connection):
        async def fetchone(self):
            if "pg_try_advisory_lock_shared" in self.last:
                attempted.set()
                return {"acquired": False}
            return await super().fetchone()

    conn: Any = WaitingConnection()

    async def request():
        async with pub.consistent_read(conn, mutation=True):
            pytest.fail("must not enter transaction while writer holds barrier")

    task = asyncio.create_task(request())
    await attempted.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not conn.closed
    assert not conn.locked
    assert conn.autocommit is False
    assert conn.timeout == "1729ms"


@pytest.mark.anyio
@pytest.mark.parametrize("count,lag,accepted", [(7, 1, True), (7, 2, False), (6, 1, False)])
async def test_new_diagnosis_freshness_uses_completed_trading_days(
    monkeypatch, count, lag, accepted
):
    from gr_api.errors import BadRequest

    class CalendarDb:
        @asynccontextmanager
        async def cursor(self):
            yield self

        async def execute(self, query, params):
            assert params == (date(2026, 11, 5), date(2026, 11, 12))

        async def fetchone(self):
            return {"calendar_days": count, "lag": lag}

    monkeypatch.setattr(pub, "_latest_completed_date", lambda: date(2026, 11, 12))
    db: Any = CalendarDb()
    if accepted:
        await pub.require_freshness(db, date(2026, 11, 5))
    else:
        with pytest.raises(BadRequest) as exc:
            await pub.require_freshness(db, date(2026, 11, 5))
        assert exc.value.http_status == 503
