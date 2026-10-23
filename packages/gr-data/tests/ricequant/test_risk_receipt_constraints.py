"""049 的数据库约束回归；只使用 pg_conn 提供的一次性 PostgreSQL。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb


@pytest.fixture
def receipt_case(pg_conn):
    """只准备 capture 和未绑定 run，receipt/绑定由各测试独立写入。"""
    case = SimpleNamespace(
        conn=pg_conn,
        variant_id="a" * 64,
        manifest_hash="b" * 64,
        observation_id="c" * 32,
        day=date(2026, 10, 21),
        captured_at=datetime(2026, 10, 23, 8, tzinfo=timezone.utc),
        committed_at=datetime(2026, 10, 23, 9, tzinfo=timezone.utc),
        run_id=uuid.uuid4(),
        receipt_id=uuid.uuid4(),
        importer_version="risk-receipt-constraint-test-v1",
        identity={"purpose": "validation", "model": "v1", "industry_mapping": "sws_2021"},
    )
    case.partition_key = f"{case.variant_id}/{case.day}/{case.observation_id}"
    case.units = {
        "variant_id": case.variant_id,
        "observation_id": case.observation_id,
        "trading_day": str(case.day),
        "purpose": "validation",
        "model": "v1",
        "industry_mapping": "sws_2021",
    }
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.dataset_variant "
            "(variant_id,provider,dataset_name,purpose,identity) "
            "VALUES (%s,'ricequant','rq_risk_model','validation',%s)",
            (case.variant_id, Jsonb(case.identity)),
        )
        cur.execute(
            "INSERT INTO factor.model (model_id,model_name,source) "
            "VALUES ('receipt_fixture','回执约束测试','ricequant')"
        )
        cur.execute(
            "INSERT INTO factor.model_run "
            "(run_id,model_id,model_version,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units,calibrated,estimated_at,source) "
            "VALUES (%s,'receipt_fixture',%s,%s,1,%s,'annual_252',%s,false,%s,'ricequant')",
            (
                case.run_id,
                case.run_id.hex,
                ["comovement"],
                hashlib.md5(b"comovement").hexdigest(),
                Jsonb(case.units),
                case.captured_at,
            ),
        )
        _capture(cur, case)
    pg_conn.commit()
    return case


def _capture(cur, case, **changes):
    values = {
        "provider": "ricequant",
        "dataset_name": "rq_risk_model",
        "partition_key": case.partition_key,
        "state": Jsonb({"manifest_hash": case.manifest_hash, "purpose": "validation"}),
        "variant_id": case.variant_id,
        "observation_id": case.observation_id,
        "trading_day": case.day,
        "capture_manifest_hash": case.manifest_hash,
        "captured_at": case.captured_at,
    }
    values.update(changes)
    _insert(cur, "ops.import_checkpoint", values)


def _insert(cur, table, values, *, conflict=False):
    # 表名和键均来自本文件常量，不接受外部输入；值始终参数化。
    columns = ",".join(values)
    placeholders = ",".join(["%s"] * len(values))
    cur.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        + (" ON CONFLICT DO NOTHING" if conflict else ""),
        tuple(values.values()),
    )


def _receipt(cur, case, *, conflict=False, **changes):
    values = {
        "receipt_id": case.receipt_id,
        "target": "factor.risk_bundle",
        "variant_id": case.variant_id,
        "manifest_hash": case.manifest_hash,
        "importer_version": case.importer_version,
        "observation_id": case.observation_id,
        "trading_day": case.day,
        "rows_written": 9,
        "quality": Jsonb({"passed": True}),
        "committed_at": case.committed_at,
    }
    values.update(changes)
    _insert(cur, "ops.import_receipt", values, conflict=conflict)


def _binding(cur, case, **changes):
    values = {
        "run_id": case.run_id,
        "receipt_id": case.receipt_id,
        "variant_id": case.variant_id,
        "observation_id": case.observation_id,
        "trading_day": case.day,
    }
    values.update(changes)
    _insert(cur, "factor.model_run_binding", values)


def _advance(cur, case, **changes):
    values = {
        "import_receipt_id": case.receipt_id,
        "imported_at": case.committed_at,
        "watermark_date": case.day,
        "updated_at": case.committed_at,
    }
    values.update(changes)
    cur.execute(
        "UPDATE ops.import_checkpoint SET "
        + ",".join(f"{column}=%s" for column in values)
        + " WHERE provider='ricequant' AND dataset_name='rq_risk_model' AND partition_key=%s",
        (*values.values(), case.partition_key),
    )


def _finish(case):
    with case.conn.transaction(), case.conn.cursor() as cur:
        _receipt(cur, case)
        _binding(cur, case)
        _advance(cur, case)


def test_receipt_capture_binding_success_and_idempotent_replay(receipt_case):
    case = receipt_case
    _finish(case)
    with case.conn.transaction(), case.conn.cursor() as cur:
        _receipt(cur, case, conflict=True)
        assert cur.rowcount == 0
        cur.execute(
            "SELECT import_receipt_id,imported_at,watermark_date,captured_at "
            "FROM ops.import_checkpoint WHERE partition_key=%s",
            (case.partition_key,),
        )
        assert cur.fetchone() == (case.receipt_id, case.committed_at, case.day, case.captured_at)
        cur.execute("SELECT count(*) FROM factor.model_run_binding WHERE run_id=%s", (case.run_id,))
        assert cur.fetchone()[0] == 1
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _receipt(cur, case, receipt_id=uuid.uuid4())


@pytest.mark.parametrize(
    "purpose,identity",
    [
        ("production", {"purpose": "validation"}),
        ("validation", {}),
        ("validation", {"purpose": None}),
        ("validation", {"purpose": 1}),
        ("validation", []),
        ("other", {"purpose": "other"}),
    ],
)
def test_variant_purpose_cannot_be_forged_on_insert(receipt_case, purpose, identity):
    case = receipt_case
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(
            "INSERT INTO ops.dataset_variant "
            "(variant_id,provider,dataset_name,purpose,identity) "
            "VALUES (%s,'ricequant','rq_risk_model',%s,%s)",
            ("d" * 64, purpose, Jsonb(identity)),
        )


@pytest.mark.parametrize(
    "table", ["ops.dataset_variant", "ops.import_receipt", "factor.model_run_binding"]
)
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_evidence_entities_reject_direct_mutation(receipt_case, table, operation):
    case = receipt_case
    _finish(case)
    assignments = {
        "ops.dataset_variant": "purpose='production'",
        "ops.import_receipt": "rows_written=0",
        "factor.model_run_binding": "observation_id='dddddddddddddddddddddddddddddddd'",
    }
    sql = (
        f"UPDATE {table} SET {assignments[table]}"
        if operation == "update"
        else f"DELETE FROM {table}"
    )
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(sql)


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "production"),
        ("variant_id", "d" * 64),
        ("observation_id", "d" * 32),
        ("trading_day", "2026-10-20"),
        ("model", "v2"),
        ("industry_mapping", "citics_2019"),
        ("purpose", None),
    ],
)
def test_binding_rejects_forged_run_metadata(receipt_case, field, value):
    case = receipt_case
    with case.conn.transaction(), case.conn.cursor() as cur:
        new_run_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO factor.model_run "
            "(run_id,model_id,model_version,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units,calibrated,estimated_at,source) "
            "SELECT %s,model_id,%s,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,%s,calibrated,estimated_at,source "
            "FROM factor.model_run WHERE run_id=%s",
            (new_run_id, new_run_id.hex, Jsonb({**case.units, field: value}), case.run_id),
        )
        case.run_id = new_run_id
        _receipt(cur, case)
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _binding(cur, case)


@pytest.mark.parametrize(
    "change", ["units", "source", "factor_order", "estimated_at", "calibrated", "delete"]
)
def test_bound_model_run_metadata_cannot_be_relabelled(receipt_case, change):
    case = receipt_case
    _finish(case)
    statements = {
        "units": "UPDATE factor.model_run SET units=jsonb_set(units,'{purpose}','\"production\"')",
        "source": "UPDATE factor.model_run SET source='datayes'",
        "factor_order": "UPDATE factor.model_run SET factor_order=ARRAY['other']",
        "estimated_at": "UPDATE factor.model_run SET estimated_at=estimated_at+interval '1 day'",
        "calibrated": "UPDATE factor.model_run SET calibrated=true",
        "delete": "DELETE FROM factor.model_run",
    }
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(statements[change] + " WHERE run_id=%s", (case.run_id,))


@pytest.mark.parametrize("mismatch", ["variant_id", "observation_id", "trading_day"])
def test_binding_composite_identity_cannot_reference_other_receipt(receipt_case, mismatch):
    case = receipt_case
    with case.conn.transaction(), case.conn.cursor() as cur:
        _receipt(cur, case)
    values = {
        "variant_id": "d" * 64,
        "observation_id": "d" * 32,
        "trading_day": case.day - timedelta(days=1),
    }
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _binding(cur, case, **{mismatch: values[mismatch]})


@pytest.mark.parametrize(
    "column", ["observation_id", "trading_day", "capture_manifest_hash", "captured_at"]
)
def test_tagged_capture_required_fields_cannot_use_null(receipt_case, column):
    case = receipt_case
    observation = "d" * 32
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        values = {
            "partition_key": f"{case.variant_id}/{case.day}/{observation}",
            "observation_id": observation,
            column: None,
        }
        _capture(cur, case, **values)


@pytest.mark.parametrize("mutation", ["manifest", "purpose", "day", "clear_tag", "delete"])
def test_captured_identity_cannot_be_rewritten(receipt_case, mutation):
    case = receipt_case
    statements = {
        "manifest": "UPDATE ops.import_checkpoint SET capture_manifest_hash=repeat('d',64)",
        "purpose": (
            "UPDATE ops.import_checkpoint SET state=jsonb_set(state,'{purpose}','\"production\"')"
        ),
        "day": "UPDATE ops.import_checkpoint SET trading_day=trading_day+1",
        "clear_tag": "UPDATE ops.import_checkpoint SET variant_id=NULL",
        "delete": "DELETE FROM ops.import_checkpoint",
    }
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(statements[mutation] + " WHERE partition_key=%s", (case.partition_key,))


@pytest.mark.parametrize("mismatch", ["manifest", "committed_at", "watermark", "binding_missing"])
def test_checkpoint_requires_matching_bound_receipt(receipt_case, mismatch):
    case = receipt_case
    with case.conn.transaction(), case.conn.cursor() as cur:
        _receipt(cur, case, **({"manifest_hash": "d" * 64} if mismatch == "manifest" else {}))
        if mismatch != "binding_missing":
            _binding(cur, case)
    changes = {}
    if mismatch == "committed_at":
        changes["imported_at"] = case.committed_at + timedelta(seconds=1)
    elif mismatch == "watermark":
        changes["watermark_date"] = case.day + timedelta(days=1)
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _advance(cur, case, **changes)


def test_receipt_binding_and_checkpoint_roll_back_together(receipt_case):
    case = receipt_case
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _receipt(cur, case)
        _binding(cur, case)
        _advance(cur, case, watermark_date=case.day + timedelta(days=1))
    with case.conn.transaction(), case.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.import_receipt")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM factor.model_run_binding")
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT import_receipt_id,imported_at,watermark_date FROM ops.import_checkpoint "
            "WHERE partition_key=%s",
            (case.partition_key,),
        )
        assert cur.fetchone() == (None, None, None)


def test_imported_checkpoint_cannot_rewind_or_refresh(receipt_case):
    case = receipt_case
    _finish(case)
    for assignment in (
        "import_receipt_id=NULL,imported_at=NULL,watermark_date=NULL",
        "updated_at=updated_at+interval '1 second'",
        "watermark_date=watermark_date+1",
    ):
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            case.conn.transaction(),
            case.conn.cursor() as cur,
        ):
            cur.execute(
                f"UPDATE ops.import_checkpoint SET {assignment} WHERE partition_key=%s",
                (case.partition_key,),
            )


def test_legacy_checkpoint_updates_and_delete_remain_compatible(receipt_case):
    case = receipt_case
    with case.conn.transaction(), case.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.import_checkpoint(provider,dataset_name,partition_key,watermark_date) "
            "VALUES ('legacy','history','old-partition','2024-01-02')"
        )
        cur.execute(
            "UPDATE ops.import_checkpoint SET watermark_date='2024-02-01',state='[]' "
            "WHERE provider='legacy'"
        )
        assert cur.rowcount == 1
        cur.execute("DELETE FROM ops.import_checkpoint WHERE provider='legacy'")
        assert cur.rowcount == 1


@pytest.mark.parametrize(
    "assignment",
    [
        "units=jsonb_set(units,'{purpose}','\"production\"')",
        "units=jsonb_set(units,'{variant_id}',to_jsonb(repeat('d',64)))",
        "units=jsonb_set(units,'{observation_id}',to_jsonb(repeat('d',32)))",
        "units=jsonb_set(units,'{trading_day}','\"2026-10-20\"')",
        "units=units-'purpose'",
        "source='datayes'",
    ],
)
def test_unbound_validation_run_identity_cannot_be_relabelled(receipt_case, assignment):
    case = receipt_case
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(f"UPDATE factor.model_run SET {assignment} WHERE run_id=%s", (case.run_id,))


def test_legacy_fixed_run_without_purpose_cannot_be_promoted(receipt_case):
    case = receipt_case
    legacy_id = uuid.uuid4()
    with case.conn.transaction(), case.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO factor.model_run "
            "(run_id,model_id,model_version,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units,calibrated,estimated_at,source) "
            "SELECT %s,model_id,%s,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units-'purpose'-'trading_day',calibrated,estimated_at,source "
            "FROM factor.model_run WHERE run_id=%s",
            (legacy_id, legacy_id.hex, case.run_id),
        )
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute(
            "UPDATE factor.model_run SET units=jsonb_set(units,'{purpose}','\"production\"') "
            "WHERE run_id=%s",
            (legacy_id,),
        )
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        cur.execute("DELETE FROM factor.model_run WHERE run_id=%s", (legacy_id,))


def test_receipt_cannot_be_bound_to_a_second_run(receipt_case):
    case = receipt_case
    _finish(case)
    duplicate_run_id = uuid.uuid4()
    with case.conn.transaction(), case.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO factor.model_run "
            "(run_id,model_id,model_version,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units,calibrated,estimated_at,source) "
            "SELECT %s,model_id,%s,factor_order,factor_count,factor_order_hash,"
            "annualization_basis,units,calibrated,estimated_at,source "
            "FROM factor.model_run WHERE run_id=%s",
            (duplicate_run_id, duplicate_run_id.hex, case.run_id),
        )
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _binding(cur, case, run_id=duplicate_run_id)


def test_receipt_rejects_non_bundle_target(receipt_case):
    case = receipt_case
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        case.conn.transaction(),
        case.conn.cursor() as cur,
    ):
        _receipt(cur, case, target="factor.exposure")
