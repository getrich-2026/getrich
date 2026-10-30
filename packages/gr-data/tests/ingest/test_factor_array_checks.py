"""047 风险模型数组约束与跨表 factor_count 入库门禁。"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest


RUN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _seed(pg_conn, *, factor_count: int = 2) -> int:
    """写入一个两因子的 model_run 与一只标的，返回 instrument_id。"""
    pg_conn.execute(
        "INSERT INTO meta.instruments (symbol,asset,exchange,list_date) "
        "VALUES ('600000.SH','stock','XSHG','2000-01-01')"
    )
    pg_conn.execute("INSERT INTO factor.model VALUES ('test_model','test','test')")
    pg_conn.execute(
        "INSERT INTO factor.model_run (run_id,model_id,model_version,factor_order,factor_count,"
        "factor_order_hash,annualization_basis,observed_at,source) "
        "VALUES (%s,'test_model','v1',%s,%s,'h','annual_252',now(),'test')",
        (RUN_ID, ["size", "beta"][:factor_count], factor_count),
    )
    iid = pg_conn.execute("SELECT instrument_id FROM meta.instruments").fetchone()[0]
    pg_conn.commit()
    return iid


def _assert_insert(pg_conn, sql: str, params: tuple, ok: bool, constraint: str) -> None:
    """非法时必须由 ``constraint`` 这条约束拒绝，不能因为别的约束误通过。"""
    import psycopg

    if ok:
        pg_conn.execute(sql, params)
        pg_conn.commit()
    else:
        with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
            pg_conn.execute(sql, params)
        pg_conn.rollback()
        assert excinfo.value.diag.constraint_name == constraint


# 数组以 PG 文本字面量给出，才能构造二维、自定义下标等 Python list 表达不了的形状。
ARRAY_CASES = [
    ("{0.1,0.2}", 2, True),
    ("{}", 2, False),  # 空数组：旧约束 array_length 为 NULL 时放行
    ("{}", 0, False),
    ("{0.1}", 2, False),
    ("{{0.1},{0.2}}", 2, False),  # 二维：旧约束只比第一维，放行
    ("[0:1]={0.1,0.2}", 2, False),  # 下标不从 1 起
    ("{0.1,NULL}", 2, False),
    ("{0.1,NaN}", 2, False),
    ("{0.1,Infinity}", 2, False),
    ("{-Infinity,0.2}", 2, False),
]


@pytest.mark.integration
@pytest.mark.parametrize("literal,factor_count,ok", ARRAY_CASES)
def test_047_exposure_array(pg_conn, literal, factor_count, ok):
    iid = _seed(pg_conn)
    sql = (
        "INSERT INTO factor.exposure (run_id,instrument_id,trading_day,exposure,factor_count) "
        "VALUES (%s,%s,'2024-01-02',%s::real[],%s)"
    )
    _assert_insert(pg_conn, sql, (RUN_ID, iid, literal, factor_count), ok, "chk_exposure_array")


@pytest.mark.integration
@pytest.mark.parametrize("literal,factor_count,ok", ARRAY_CASES)
def test_047_factor_return_array(pg_conn, literal, factor_count, ok):
    _seed(pg_conn)
    sql = (
        "INSERT INTO factor.factor_return (run_id,trading_day,ret_vector,factor_count) "
        "VALUES (%s,'2024-01-02',%s::real[],%s)"
    )
    _assert_insert(pg_conn, sql, (RUN_ID, literal, factor_count), ok, "chk_ret_array")


@pytest.mark.integration
@pytest.mark.parametrize(
    "literal,ok",
    [
        ("{1.5,0.1,2.5}", True),  # K=2 的上三角：K(K+1)/2 = 3 个元素
        ("{1.5,0.1}", False),
        ("{}", False),
        ("{{1.5,0.1,2.5}}", False),
        ("{1.5,NULL,2.5}", False),
        ("{1.5,NaN,2.5}", False),
        ("{1.5,0.1,Infinity}", False),
    ],
)
def test_047_covariance_array(pg_conn, literal, ok):
    _seed(pg_conn)
    sql = (
        "INSERT INTO factor.covariance (run_id,trading_day,cov_flat,factor_count) "
        "VALUES (%s,'2024-01-02',%s::double precision[],2)"
    )
    _assert_insert(pg_conn, sql, (RUN_ID, literal), ok, "chk_cov_array")


@pytest.mark.integration
@pytest.mark.parametrize(
    "literal,factor_count,ok",
    [
        ("{size,beta}", 2, True),
        ("{}", 1, False),  # 旧约束：factor_count > 0 AND 1 = NULL 得 NULL，放行
        ("{size}", 2, False),
        ("{{size},{beta}}", 2, False),
        ("{size,NULL}", 2, False),
    ],
)
def test_047_model_run_factor_order(pg_conn, literal, factor_count, ok):
    pg_conn.execute("INSERT INTO factor.model VALUES ('test_model','test','test')")
    pg_conn.commit()
    sql = (
        "INSERT INTO factor.model_run (run_id,model_id,model_version,factor_order,factor_count,"
        "factor_order_hash,annualization_basis,observed_at,source) "
        "VALUES (%s,'test_model','v1',%s::text[],%s,'h','annual_252',now(),'test')"
    )
    _assert_insert(pg_conn, sql, (RUN_ID, literal, factor_count), ok, "chk_model_run_factor_order")


@pytest.mark.integration
def test_factor_create_uses_final_constraints_and_is_idempotent(pg_conn):
    from gr_db import POSTGRES_DDL_DIR

    sql = (POSTGRES_DDL_DIR / "037_factor.sql").read_text()
    pg_conn.execute(sql)
    pg_conn.execute(sql)
    names = {
        row[0]
        for row in pg_conn.execute(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'factor'::regnamespace "
            "AND contype = 'c'"
        ).fetchall()
    }
    pg_conn.commit()
    assert {
        "chk_model_run_factor_order",
        "chk_exposure_array",
        "chk_cov_array",
        "chk_ret_array",
    } <= names
    assert {
        "chk_model_run_factor_count",
        "chk_exposure_len",
        "chk_cov_len",
        "chk_ret_len",
    }.isdisjoint(names)


# --------------------------------------------------------------------------- #
# 跨表门禁：明细行 factor_count 必须等于所属 model_run
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.parametrize("run_id", [RUN_ID, str(RUN_ID), RUN_ID.hex])
def test_gate_accepts_matching_counts(pg_conn, run_id):
    from gr_data.ingest.factor_gate import check_factor_counts

    _seed(pg_conn)
    check_factor_counts(pg_conn, "factor.exposure", [(run_id, 2), (run_id, 2)])


@pytest.mark.integration
def test_gate_rejects_count_differing_from_run(pg_conn):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.factor_gate import check_factor_counts

    _seed(pg_conn)
    with pytest.raises(IngestGateError, match="differs from model_run"):
        check_factor_counts(pg_conn, "factor.exposure", [(RUN_ID, 2), (RUN_ID, 3)])


@pytest.mark.integration
def test_gate_rejects_missing_run(pg_conn):
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.factor_gate import check_factor_counts

    with pytest.raises(IngestGateError, match="model_run not found"):
        check_factor_counts(pg_conn, "factor.covariance", [(uuid.uuid4(), 2)])


def test_gate_with_no_rows_skips_database():
    from gr_data.ingest.factor_gate import check_factor_counts

    check_factor_counts(None, "factor.exposure", [])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "importer,gated",
    [
        ("ExposureImporter", True),
        ("FactorReturnImporter", True),
        ("CovarianceImporter", True),
        ("SpecificRiskImporter", False),
    ],
)
def test_datayes_array_importers_run_gate(tmp_raw_root, monkeypatch, importer, gated):
    """通联的数组表在 run() 的质量检查阶段走门禁；标量表没有 factor_count，不走。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.datayes.importers import riskmodel

    calls = []
    monkeypatch.setattr(riskmodel, "check_factor_counts", lambda *args: calls.append(args))
    imp = getattr(riskmodel, importer)(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    df = pd.DataFrame({"run_id": [RUN_ID], "factor_count": [2]})
    imp._check_quality(df)

    assert bool(calls) is gated
    if gated:
        _, target, rows = calls[0]
        assert target == imp.contract.qualified
        assert list(rows) == [(RUN_ID, 2)]


def test_datayes_gate_receives_deduplicated_pairs(tmp_raw_root, monkeypatch):
    """千万行载荷只需核对不同的 (run_id, factor_count) 组合。"""
    from gr_data.ingest.base import IngestContext
    from gr_data.ingest.datayes.importers import riskmodel

    calls = []
    monkeypatch.setattr(riskmodel, "check_factor_counts", lambda *args: calls.append(args))
    imp = riskmodel.ExposureImporter(conn=None, ctx=IngestContext(paths=tmp_raw_root))
    imp._check_quality(pd.DataFrame({"run_id": [RUN_ID] * 3, "factor_count": [2, 2, 3]}))

    assert sorted(calls[0][2]) == [(RUN_ID, 2), (RUN_ID, 3)]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_datayes_nonfinite_rows_rejected_with_samples(bad):
    """通联载荷／因子收益含非有限元素时，写库前带日期与样例硬失败，不等 COPY 报 CheckViolation。"""
    import numpy as np
    from gr_data.ingest.base import IngestGateError
    from gr_data.ingest.datayes.importers.riskmodel import _reject_nonfinite

    values = np.array([[0.1, 0.2], [0.3, bad]])
    days = pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"]).date)
    with pytest.raises(IngestGateError, match=r"1 rows.*2024-01-03.*\['22'\]"):
        _reject_nonfinite(values, days, pd.Series([11, 22]), "factor.exposure")
    _reject_nonfinite(values[:1], days[:1], None, "factor.factor_return")  # 全部有限时放行
