"""048 在一次性 PG 中的请求前状态约束和 DDL 幂等验证。"""

from __future__ import annotations

from itertools import product
from uuid import uuid4

import psycopg
import pytest
from gr_db import POSTGRES_DDL_DIR, migrate_postgres
from psycopg.types.json import Jsonb


def test_048_unrequested_status_constraints_and_replay(pg_conn):
    """真库拒绝伪造请求／返回状态，不靠其他外键或唯一键错误冒充通过。"""
    ddl = POSTGRES_DDL_DIR / "048_factor_model_run_coverage.sql"
    pg_conn.execute(ddl.read_text())
    pg_conn.execute(ddl.read_text())
    pg_conn.commit()
    migrate_postgres(pg_conn)
    assert (
        pg_conn.execute(
            "SELECT count(*) FROM ops.schema_migrations WHERE file_name=%s", (ddl.name,)
        ).fetchone()[0]
        == 1
    )
    instrument_id = pg_conn.execute(
        "INSERT INTO meta.instruments(symbol,asset,exchange) "
        "VALUES ('600000.SH','stock','XSHG') RETURNING instrument_id"
    ).fetchone()[0]
    pg_conn.execute(
        "INSERT INTO factor.model(model_id,model_name,source) "
        "VALUES ('coverage-test','coverage-test','ricequant')"
    )
    run_id = uuid4()
    pg_conn.execute(
        "INSERT INTO factor.model_run(run_id,model_id,model_version,factor_order,"
        "factor_count,factor_order_hash,annualization_basis,estimated_at,source) "
        "VALUES (%s,'coverage-test','test',ARRAY['market'],1,'test',"
        "'annual_252',now(),'ricequant')",
        (run_id,),
    )
    pg_conn.commit()
    insert = (
        "INSERT INTO factor.model_run_coverage(run_id,instrument_id,trading_day,input_codes,"
        "request_code,status,pieces,evidence,available_at) "
        "VALUES (%s,%s,'2026-10-21',ARRAY['600000.XSHG'],%s,%s,%s,'{}',now())"
    )
    names = ("exposure", "specific_return", "specific_risk")
    false_pieces = dict.fromkeys(names, False)

    def attempt(status, request, pieces, valid):
        parameters = (run_id, instrument_id, request, status, Jsonb(pieces))
        if valid:
            with pg_conn.transaction():
                pg_conn.execute(insert, parameters)
                pg_conn.execute("DELETE FROM factor.model_run_coverage WHERE run_id=%s", (run_id,))
        else:
            with pytest.raises(psycopg.errors.CheckViolation), pg_conn.transaction():
                pg_conn.execute(insert, parameters)

    for status in ("unmapped_symbol", "sdk_filtered", "universe_boundary_unknown"):
        attempt(status, None, false_pieces, True)
        attempt(status, "600000.XSHG", false_pieces, False)
        for values in product((False, True), repeat=3):
            if any(values):
                attempt(status, None, dict(zip(names, values, strict=True)), False)
        for malformed in (
            {},
            false_pieces | {"exposure": None},
            false_pieces | {"exposure": "false"},
        ):
            attempt(status, None, malformed, False)
    for status in ("invalid_value", "unsupported_exchange", "unresolved_identity"):
        attempt(status, None, false_pieces, False)
    attempt("included", "600000.XSHG", dict.fromkeys(names, True), True)
    attempt("provider_not_returned", "600000.XSHG", false_pieces, True)
    attempt("partial_bundle", "600000.XSHG", false_pieces | {"exposure": True}, True)
