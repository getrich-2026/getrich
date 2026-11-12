"""055真实隔离库回归；显式GETRICH_DIAG_TEST_DATABASE且名称隔离守卫，永不默认工作库。"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from gr_data.config import load_postgres, make_pg_dsn
from gr_data.db import DictConnection
from gr_data.diagnostic_publication import admit_risk_universe, security_universe_hash
from gr_tools.config import load_environment
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.xdist_group("diag_universe_pg"),
    pytest.mark.skipif(
        not os.environ.get("GETRICH_DIAG_TEST_DATABASE"), reason="requires isolated 055 database"
    ),
]
RUN = UUID("da212baf-9bfc-5014-8bff-0b574e8e7b9b")
DAY = date(2026, 11, 5)


async def _connect() -> DictConnection:
    database = os.environ["GETRICH_DIAG_TEST_DATABASE"]
    if not database.startswith("getrich_diag_") or database == "getrich":
        pytest.fail("Refuse non-isolated database", pytrace=False)
    cfg = replace(load_postgres(load_environment()), database=database)
    try:
        return await DictConnection.connect(make_pg_dsn(cfg), row_factory=dict_row)
    except psycopg.OperationalError:
        pytest.fail("Unable to connect isolated database", pytrace=False)


async def _arguments(conn: DictConnection) -> dict[str, Any]:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT b.receipt_id,m.factor_order_hash FROM factor.model_run m
            JOIN factor.model_run_binding b USING(run_id) WHERE m.run_id=%s""",
            (RUN,),
        )
        run = await cur.fetchone()
        assert run is not None
        await cur.execute("SELECT instrument_id FROM meta.instruments WHERE symbol='600519.SH'")
        security = await cur.fetchone()
        assert security is not None
    return {
        "run_id": RUN,
        "receipt_id": run["receipt_id"],
        "as_of_date": DAY,
        "instrument_ids": [security["instrument_id"]],
        "factor_order_hash": run["factor_order_hash"],
        "units_evidence": {"test": "055-isolated-existing-yearly-percent-variance-contract"},
        "evidence": {"test": "055-transactional-regression-only"},
    }


async def test_universe_members_replay_and_immutability() -> None:
    async with await _connect() as conn, conn.transaction(force_rollback=True):
        args = await _arguments(conn)
        admission_id = await admit_risk_universe(conn, **args)
        assert await admit_risk_universe(conn, **args) == admission_id
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT instrument_id FROM factor.risk_universe_member WHERE admission_id=%s",
                (admission_id,),
            )
            assert [r["instrument_id"] for r in await cur.fetchall()] == args["instrument_ids"]
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await conn.execute(
                    """UPDATE factor.risk_universe_admission SET evidence=evidence
                       WHERE admission_id=%s""",
                    (admission_id,),
                )


async def test_universe_incomplete_members_rejected_at_constraint_check() -> None:
    async with await _connect() as conn, conn.transaction(force_rollback=True):
        args = await _arguments(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO factor.risk_universe_admission
                    (admission_id,run_id,receipt_id,as_of_date,security_ids,security_hash,
                     metrics,factor_order_hash,units_evidence,evidence)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        uuid4(),
                        RUN,
                        args["receipt_id"],
                        DAY,
                        args["instrument_ids"],
                        security_universe_hash(args["instrument_ids"]),
                        ["volatility"],
                        args["factor_order_hash"],
                        Jsonb(args["units_evidence"]),
                        Jsonb(args["evidence"]),
                    ),
                )
                await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


async def test_universe_axis_and_missing_security_rejected() -> None:
    async with await _connect() as conn, conn.transaction(force_rollback=True):
        args = await _arguments(conn)
        for changed in ({"factor_order_hash": "0" * 32}, {"instrument_ids": [9223372036854775807]}):
            with pytest.raises(psycopg.errors.CheckViolation):
                async with conn.transaction():
                    await admit_risk_universe(conn, **{**args, **changed})


async def test_universe_write_rollback_is_complete() -> None:
    async with await _connect() as conn, conn.transaction(force_rollback=True):
        args = await _arguments(conn)
        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS n FROM diag.data_version_invalidation")
            old = await cur.fetchone()
        with pytest.raises(RuntimeError, match="rollback probe"):
            async with conn.transaction():
                await admit_risk_universe(conn, **args)
                raise RuntimeError("rollback probe")
        async with conn.cursor() as cur:
            await cur.execute("SELECT count(*) AS n FROM diag.data_version_invalidation")
            assert await cur.fetchone() == old
            await cur.execute(
                """SELECT count(*) AS n FROM factor.risk_universe_admission
                   WHERE run_id=%s AND security_hash=%s""",
                (RUN, security_universe_hash(args["instrument_ids"])),
            )
            assert (await cur.fetchone()) == {"n": 0}
