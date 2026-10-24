"""风险五件套的事务、单位与不可变观测回归；数据库交互使用可回滚内存替身。"""

from __future__ import annotations

import copy
import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from gr_data.common.ownership import OwnershipError
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant import riskmodel as writer
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS, validate_bundle
from psycopg.pq import TransactionStatus


class MemoryConnection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.state = {"tables": {}, "owners": {}, "runs": {}, "etl": []}
        self.instruments = [("600000.SH", "XSHG", 11), ("000001.SZ", "XSHE", 22)]
        self.aliases = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_table = None
        self.locked = False
        self.receipt_migration_applied = True

    @contextmanager
    def transaction(self):
        snapshot = copy.deepcopy(self.state)
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
        except Exception:
            self.state = snapshot
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    @contextmanager
    def cursor(self):
        yield MemoryCursor(self)


class MemoryCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def execute(self, sql, params=()):
        state = self.conn.state
        if sql.startswith("SELECT file_name FROM ops.schema_migrations"):
            self.result = [(params[0],)] if self.conn.receipt_migration_applied else []
        elif sql.startswith("INSERT INTO ops.dataset_variant"):
            state.setdefault("variants", {}).setdefault(params[0], (*params[:4], params[4].obj))
        elif sql.startswith("SELECT variant_id, provider, dataset_name, purpose, identity"):
            row = state.get("variants", {}).get(params[0])
            self.result = [row] if row else []
        elif sql.startswith("INSERT INTO ops.import_checkpoint"):
            row = (*params[3:8], params[8].obj)
            state.setdefault("checkpoints", {}).setdefault(tuple(params[:3]), [row, None])
        elif sql.startswith("SELECT variant_id,observation_id,trading_day,capture_manifest_hash"):
            row = state.get("checkpoints", {}).get(tuple(params))
            self.result = [row[0]] if row else []
        elif sql.startswith("INSERT INTO ops.import_receipt"):
            key = (params[1], params[3], params[4])
            row = (*params[:8], params[8].obj, datetime.now(timezone.utc))
            state.setdefault("receipts", {}).setdefault(key, row)
        elif sql.startswith("SELECT receipt_id, target, variant_id, manifest_hash"):
            row = state.get("receipts", {}).get(tuple(params))
            self.result = [row] if row else []
        elif sql.startswith("INSERT INTO factor.model_run_binding"):
            state.setdefault("bindings", {}).setdefault(params[0], tuple(params))
        elif sql.startswith("SELECT run_id,receipt_id,variant_id,observation_id,trading_day"):
            row = state.get("bindings", {}).get(params[0])
            self.result = [row] if row else []
        elif sql.startswith("UPDATE ops.import_checkpoint SET import_receipt_id"):
            record = state.get("checkpoints", {}).get(tuple(params[3:]))
            if record and record[1] is None:
                record[1] = tuple(params[:3])
        elif sql.startswith("SELECT import_receipt_id,imported_at,watermark_date"):
            record = state.get("checkpoints", {}).get(tuple(params))
            self.result = [record[1] or (None, None, None)] if record else []
        elif sql.endswith(" LIMIT 0"):
            self.result = []
        elif sql.startswith("LOCK TABLE "):
            self.conn.locked = True
        elif sql.startswith("SELECT target, provider, channel"):
            self.result = [state["owners"][params[0]]] if params[0] in state["owners"] else []
        elif "INSERT INTO ops.table_ownership" in sql:
            assert self.conn.locked
            state["owners"][params[0]] = tuple(params)
        elif sql.startswith("SELECT 'canonical'"):
            self.result = [
                ("canonical", symbol, symbol, exchange, instrument_id)
                for symbol, exchange, instrument_id in self.conn.instruments
                if symbol in params[0]
            ]
            aliases = [
                *self.conn.aliases,
                *[
                    (record["source"], record["source_symbol"], record["instrument_id"])
                    for record in state["tables"].get("meta.symbol_map", {}).values()
                ],
            ]
            for source, code, instrument_id in aliases:
                if (source == "ricequant" and code in params[1]) or (
                    source == "tushare" and code in params[2]
                ):
                    self.result.extend(
                        (source, code, symbol, exchange, instrument_id)
                        for symbol, exchange, identity in self.conn.instruments
                        if identity == instrument_id
                    )
        elif sql.startswith("SELECT instrument_id, symbol, exchange"):
            self.result = [
                (identity, symbol, exchange)
                for symbol, exchange, identity in self.conn.instruments
                if identity in params[0]
            ]
        elif sql.startswith("SELECT instrument_id FROM meta.symbol_map"):
            self.result = [
                (identity,)
                for source, code, identity in self.conn.aliases
                if source in {"tushare", "ricequant"} and code == params[0]
            ]
        elif sql.startswith("SELECT run_id, instrument_id"):
            contract = writer.contracts.MODEL_RUN_COVERAGE
            self.result = [
                tuple(record[column] for column in contract.columns)
                for record in sorted(
                    state["tables"].get(contract.qualified, {}).values(),
                    key=lambda row: row["instrument_id"],
                )
                if record["run_id"] == params[0]
            ]
        elif sql.startswith("INSERT INTO factor.model_run"):
            assert "DO NOTHING" in sql
            row = (*params[:8], params[8].obj, *params[9:])
            state["runs"].setdefault(params[0], row)
        elif sql.startswith("SELECT run_id, model_id"):
            self.result = [state["runs"][params[0]]]
        elif sql.startswith("SELECT run_id::text, factor_count FROM factor.model_run"):
            # 跨表 factor_count 门禁：门禁传带连字符的 UUID 文本，runs 的键统一后再比较。
            count_col = writer.contracts.MODEL_RUN.columns.index("factor_count")
            wanted = set(params[0])
            self.result = [
                (str(uuid.UUID(str(key))), row[count_col])
                for key, row in state["runs"].items()
                if str(uuid.UUID(str(key))) in wanted
            ]
        elif sql.startswith("INSERT INTO ops.etl_job_run"):
            state["etl"].append(params)
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


def memory_upsert(conn, contract, rows):
    if conn.fail_table == contract.qualified:
        raise RuntimeError("simulated database write failure")
    table = conn.state["tables"].setdefault(contract.qualified, {})
    for row in rows:
        record = copy.deepcopy(dict(zip(contract.columns, row, strict=True)))
        key = tuple(record[key] for key in contract.conflict_keys)
        table[key] = record
    return len(rows)


@pytest.fixture
def risk_case(monkeypatch, tmp_path):
    from gr_data.db import risk_receipts

    monkeypatch.setattr(risk_receipts, "get_importer_version", lambda **kwargs: "1" * 40)
    day = date(2024, 1, 2)
    options = RiskOptions(
        model="v1",
        industry_mapping="sws_2021",
        start_date=day,
        end_date=day,
        order_book_ids=("000001.XSHE", "600000.XSHG"),
        source_units={
            "covariance": "dec2_daily",
            "specific_risk": "dec_daily",
            "factor_return": "pct_daily",
            "specific_return": "dec_daily",
        },
        units_evidence="fixture only; no account unit claim",
    )
    order = [*sorted(STYLE_FACTORS["v1"]), "comovement", "银行"]
    count = len(order)
    exposure = pd.DataFrame(np.ones((2, count)), index=options.order_book_ids, columns=order)
    frames = validate_bundle(
        {
            "exposure": exposure,
            "covariance": pd.DataFrame(
                (np.eye(count) + np.ones((count, count))) * 0.00001, index=order, columns=order
            ),
            "factor_return": pd.DataFrame([np.arange(count) / 10], index=[day], columns=order),
            "specific_return": pd.DataFrame(
                [[0.012, -0.03]], index=[day], columns=options.order_book_ids
            ),
            "specific_risk": pd.DataFrame(
                [[0.01, 0.02]], index=[day], columns=options.order_book_ids
            ),
        },
        options,
        day,
    )
    manifest = {
        "day": day.isoformat(),
        "observed_at": "2026-09-18T09:30:00+08:00",
        "observation_id": "00000000000000000000000000000001",
        "variant_id": options.variant_id,
    }
    bundles = [(manifest, frames)]
    monkeypatch.setattr(writer, "read_bundles", lambda *args, **kwargs: iter(bundles))
    monkeypatch.setattr(writer, "upsert_rows", memory_upsert)
    return SimpleNamespace(
        options=options,
        manifest=manifest,
        frames=frames,
        bundles=bundles,
        conn=MemoryConnection(),
        ctx=IngestContext(paths=RawPaths(tmp_path)),
    )


def records(case, table):
    return list(case.conn.state["tables"][f"factor.{table}"].values())


def test_real_storage_rounds_binary_midpoint_without_mutating_calculation_values():
    # 生产 002426.XSHE / investment_quality：十进制文本直转 REAL 会向另一侧舍入。
    midpoint = 1.394935429096222
    samples = np.array([[midpoint, -midpoint, 0.0, np.finfo(np.float32).smallest_subnormal]])
    values = {
        key: samples.copy()
        for key in ("exposure", "factor_return", "specific_return", "specific_risk", "covariance")
    }
    stored = writer._storage_values(values)
    for key in values:
        assert np.array_equal(values[key], samples)
        if key == "covariance":
            assert stored[key] is values[key]
        else:
            assert np.array_equal(stored[key], samples.astype(np.float32))
            assert stored[key].tolist()[0][0] == 1.3949353694915771


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, 1e39, 1e-50, -1e-50])
def test_real_storage_rejects_invalid_or_underflow_values(value):
    with pytest.raises(ContractViolationError):
        writer._storage_values({"exposure": np.array([[value]])})


def test_pg_real_midpoint_roundtrip_all_four_pieces(risk_case, pg_conn, monkeypatch):
    from gr_data.db.copy import upsert_rows

    case = prepare_dynamic_pg(risk_case, pg_conn, monkeypatch)
    midpoint = 1.394935429096222
    case.options = replace(
        case.options,
        source_units={
            **case.options.source_units,
            "factor_return": "dec_daily",
            "specific_return": "pct_daily",
        },
    )
    case.manifest["variant_id"] = case.options.variant_id
    case.manifest["identity"] = case.options.identity
    case.frames["exposure"].iloc[0, 0] = midpoint
    case.frames["factor_return"].iloc[0, 0] = midpoint
    case.frames["specific_return"].iloc[0, 0] = midpoint
    normalized = writer._normalize(case.frames, case.options)
    # 风险量边界同样验证；这里只替换归一结果，以隔离平方换算与存储舍入。
    normalized["specific_risk"][0, 0] = midpoint
    monkeypatch.setattr(writer, "_normalize", lambda *args: normalized)
    monkeypatch.setattr(writer, "upsert_rows", upsert_rows)
    result = writer.run_risk_ingest(pg_conn, case.ctx, case.options)
    assert result.ok
    with pg_conn.cursor(binary=True) as cur:
        for table, column in (
            ("exposure", "exposure[1]"),
            ("factor_return", "ret_vector[1]"),
            ("specific_return", "specific_ret"),
            ("specific_risk", "specific_var"),
        ):
            cur.execute(
                f"SELECT {column} FROM factor.{table}"
                + (" WHERE instrument_id=22" if table != "factor_return" else "")
            )
            assert cur.fetchone()[0] == float(np.float32(midpoint))


def test_atomic_bundle_units_order_mapping_and_observed_time(risk_case):
    case = risk_case
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert result.rows_written == 8
    assert result.dataset == "rq_risk_model"
    assert result.ok
    assert case.conn.commits == 1
    run = next(iter(case.conn.state["runs"].values()))
    assert run[1].startswith("rq_") and len(run[1]) == 32
    assert run[1] != "barra_cne6"
    assert run[3] == list(case.frames["exposure"].columns)
    assert run[5] == hashlib.md5("|".join(run[3]).encode()).hexdigest()
    assert run[8]["source_units"] == case.options.source_units
    assert run[8]["units_evidence"] == case.options.units_evidence
    assert run[9] is False
    assert run[12] is None  # 未公开估计参数不能被采集参数指纹冒充。
    assert [row["instrument_id"] for row in records(case, "exposure")] == [22, 11]
    definitions = records(case, "definition")
    assert [row["factor_code"] for row in definitions] == run[3]
    assert {row["factor_code"]: row["factor_type"] for row in definitions}["银行"] == "industry"
    assert {row["factor_code"]: row["factor_type"] for row in definitions}["comovement"] == "market"
    assert records(case, "specific_risk")[0]["specific_var"] == pytest.approx(252)
    assert records(case, "specific_risk")[1]["specific_var"] == pytest.approx(1008)
    assert records(case, "specific_return")[0]["specific_ret"] == pytest.approx(1.2)
    assert records(case, "specific_return")[1]["specific_ret"] == pytest.approx(-3)
    expected_cov = case.frames["covariance"].to_numpy() * 2520000
    assert records(case, "covariance")[0]["cov_flat"] == pytest.approx(
        expected_cov[np.triu_indices(len(run[3]))]
    )
    assert records(case, "factor_return")[0]["ret_vector"] == pytest.approx(
        case.frames["factor_return"].iloc[0].to_numpy() / 100
    )
    for table in ("exposure", "covariance", "factor_return", "specific_return", "specific_risk"):
        for record in records(case, table):
            assert record["available_at"] == datetime.fromisoformat(case.manifest["observed_at"])
            assert record["trading_day"] == date(2024, 1, 2)
    # 固定名单保持原有八表归属，不声明动态覆盖表。
    assert set(case.conn.state["owners"]) == {
        "factor.model",
        "factor.definition",
        "factor.model_run",
        "factor.exposure",
        "factor.covariance",
        "factor.factor_return",
        "factor.specific_risk",
        "factor.specific_return",
    }
    assert case.conn.state["etl"][0][4] == 8


def test_replay_is_idempotent_and_observation_revision_is_isolated(risk_case):
    case = risk_case
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    snapshot = copy.deepcopy(case.conn.state["tables"])
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["tables"] == snapshot
    assert len(case.conn.state["runs"]) == 1
    case.manifest["observation_id"] = "00000000000000000000000000000002"
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert len(case.conn.state["runs"]) == 2
    assert len(records(case, "specific_return")) == 4
    assert len(records(case, "model")) == 1


def test_changed_observed_time_cannot_rewrite_immutable_run(risk_case):
    case = risk_case
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    snapshot = copy.deepcopy(case.conn.state)
    case.manifest["observed_at"] = "2026-09-18T10:30:00+08:00"
    with pytest.raises(ContractViolationError, match="Immutable"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert {key: value for key, value in case.conn.state.items() if key != "etl"} == {
        key: value for key, value in snapshot.items() if key != "etl"
    }
    assert case.conn.state["etl"][-1][3] == "failed"
    assert case.conn.rollbacks == 1


@pytest.mark.parametrize("fail_table", ["factor.covariance", "factor.specific_return"])
def test_write_failure_rolls_back_metadata_mapping_ownership_and_all_pieces(risk_case, fail_table):
    case = risk_case
    case.conn.fail_table = fail_table
    before = copy.deepcopy(case.conn.state)
    with pytest.raises(RuntimeError, match="simulated"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert {key: value for key, value in case.conn.state.items() if key != "etl"} == {
        key: value for key, value in before.items() if key != "etl"
    }
    assert case.conn.state["etl"][-1][3] == "failed"
    assert case.conn.commits == 1  # 只提交独立失败审计。
    assert case.conn.rollbacks == 1


def test_other_provider_ownership_refuses_and_rolls_back_earlier_claims(risk_case):
    case = risk_case
    case.conn.state["owners"]["factor.specific_risk"] = (
        "factor.specific_risk",
        "datayes",
        "ingest",
    )
    before = copy.deepcopy(case.conn.state)
    with pytest.raises(OwnershipError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert {key: value for key, value in case.conn.state.items() if key != "etl"} == {
        key: value for key, value in before.items() if key != "etl"
    }
    assert case.conn.state["etl"][-1][3] == "failed"


def test_completed_day_survives_later_day_failure(risk_case, monkeypatch):
    case = risk_case
    case.options = replace(case.options, end_date=date(2024, 1, 3))
    second_manifest = {
        **case.manifest,
        "day": "2024-01-03",
        "observation_id": "00000000000000000000000000000002",
    }
    second_frames = {key: frame.copy() for key, frame in case.frames.items()}
    for key in ("factor_return", "specific_return", "specific_risk"):
        second_frames[key].index = [date(2024, 1, 3)]
    case.bundles.append((second_manifest, second_frames))

    def fail_second_day(conn, contract, rows):
        if contract.qualified == "factor.specific_return" and rows[0][2] == date(2024, 1, 3):
            raise RuntimeError("second day failure")
        return memory_upsert(conn, contract, rows)

    monkeypatch.setattr(writer, "upsert_rows", fail_second_day)
    with pytest.raises(RuntimeError, match="second day"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.commits == 2
    assert case.conn.rollbacks == 1
    assert len(case.conn.state["runs"]) == 1
    assert len(case.conn.state["etl"]) == 2
    assert [row[3] for row in case.conn.state["etl"]] == ["success", "failed"]
    assert case.conn.state["etl"][-1][6:9] == (date(2024, 1, 3),) * 3
    assert {row["trading_day"] for row in records(case, "specific_return")} == {date(2024, 1, 2)}


def test_force_and_existing_transaction_are_rejected_before_work(risk_case):
    case = risk_case
    with pytest.raises(OwnershipError, match="own release/set"):
        writer.run_risk_ingest(case.conn, replace(case.ctx, force_ownership=True), case.options)
    case.conn.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(ValueError, match="idle"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.locked


def test_missing_canonical_instrument_does_not_silently_drop_stock(risk_case):
    case = risk_case
    case.conn.instruments = case.conn.instruments[:1]
    with pytest.raises(ContractViolationError, match="unmapped"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]
    assert not case.conn.state["owners"]


@pytest.mark.parametrize("sigma", [-1, float("nan"), float("inf"), 1e20])
def test_invalid_or_overflowing_sigma_is_rejected_before_database(risk_case, sigma):
    case = risk_case
    case.frames["specific_risk"].iloc[0, 0] = sigma
    with pytest.raises(ContractViolationError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.locked


@pytest.mark.parametrize(
    ("cov_unit", "sigma_unit", "expected_cov", "expected_var"),
    [
        ("dec2_daily", "dec_daily", 2520000, 2520000),
        ("pct2_daily", "pct_daily", 252, 252),
        ("dec2_annual", "dec_annual", 10000, 10000),
        ("pct2_annual", "pct_annual", 1, 1),
    ],
)
def test_all_risk_source_unit_conversions(
    risk_case, cov_unit, sigma_unit, expected_cov, expected_var
):
    case = risk_case
    units = {**case.options.source_units, "covariance": cov_unit, "specific_risk": sigma_unit}
    options = replace(case.options, source_units=units)
    case.frames["covariance"].iloc[:, :] = 1
    case.frames["specific_risk"].iloc[:, :] = 1
    normalized = writer._normalize(case.frames, options)
    assert np.all(normalized["covariance"] == expected_cov)
    assert np.all(normalized["specific_risk"] == expected_var)


def test_new_factor_set_cannot_replace_old_model_definitions(risk_case):
    case = risk_case
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    original = copy.deepcopy(records(case, "definition"))
    for key in ("exposure", "factor_return"):
        case.frames[key].rename(columns={"银行": "汽车"}, inplace=True)
    case.frames["covariance"].rename(columns={"银行": "汽车"}, index={"银行": "汽车"}, inplace=True)
    case.manifest["observation_id"] = "00000000000000000000000000000002"
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert len(records(case, "model")) == 2
    assert all(row in records(case, "definition") for row in original)


def test_audit_identity_quality_dates_and_real_elapsed_times(risk_case, monkeypatch):
    case = risk_case
    case.manifest["quota_observation"] = {
        "before": {"bytes_used": 200, "bytes_limit": 100000, "observed_at": "2026-10-22T12:00:00Z"},
        "after": {"bytes_used": 200, "bytes_limit": 100000, "observed_at": "2026-10-22T12:00:01Z"},
    }
    start = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    ticks = iter([start, start + timedelta(seconds=2), start + timedelta(seconds=3)])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return next(ticks)

    monkeypatch.setattr(writer, "datetime", Clock)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    audit = case.conn.state["etl"][0]
    run_id = next(iter(case.conn.state["runs"]))
    assert audit[6:9] == (date(2024, 1, 2),) * 3
    assert audit[10:12] == (start, start + timedelta(seconds=2))
    assert audit[12] is None
    request = audit[9].obj
    assert request["quota_observation"] == case.manifest["quota_observation"]
    assert request["model"] == "v1"
    assert request["industry_mapping"] == "sws_2021"
    assert request["variant_id"] == case.options.variant_id
    assert request["observation_id"] == case.manifest["observation_id"]
    assert request["model_run_id"] == str(run_id)
    assert request["quality"]["covariance"]["condition_number"] > 0
    # 质量报告属于审计，不能修改既有不可变 run 的 units。
    assert "quality" not in case.conn.state["runs"][run_id][8]


def test_replay_audits_same_model_run_identity(risk_case):
    case = risk_case
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    requests = [row[9].obj for row in case.conn.state["etl"]]
    assert requests[0] == requests[1]
    assert len(case.conn.state["runs"]) == 1


def test_quality_warning_reaches_result_and_audit(risk_case):
    case = risk_case
    diagonal = np.full(len(case.frames["covariance"]), 100.0)
    diagonal[0] = 0.00001
    case.frames["covariance"].iloc[:, :] = np.diag(diagonal) / 2520000
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not result.ok
    audit = case.conn.state["etl"][0]
    assert audit[5] == 1
    quality = audit[9].obj["quality"]
    assert quality["covariance"]["condition_number"] == pytest.approx(1e7)
    assert result.warnings == [f"2024-01-02: {quality['warnings'][0]}"]


def test_quality_rejection_records_report_without_business_writes(risk_case):
    case = risk_case
    case.frames["covariance"].iloc[:, :] = np.eye(len(case.frames["covariance"])) * 0.1
    with pytest.raises(ContractViolationError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]
    assert not case.conn.state["runs"]
    audit = case.conn.state["etl"][0]
    assert audit[3:5] == ("failed", 0)
    assert audit[6] == date(2024, 1, 2)
    assert audit[9].obj["quality"] is not None
    assert audit[9].obj["model_run_id"] is not None
    assert audit[12] == "RiskQualityError"


@pytest.mark.parametrize("identified", [False, True])
def test_raw_read_failure_audits_known_day_or_requested_scope(risk_case, monkeypatch, identified):
    case = risk_case
    case.options = replace(case.options, end_date=date(2024, 2, 29))
    case.ctx = replace(case.ctx, months=("2024-02",))
    failure = ContractViolationError("private-payload-must-not-be-audited")
    if identified:
        failure.risk_day = "2024-02-01"
        failure.risk_observation_id = "00000000000000000000000000000003"

    def broken(*args, **kwargs):
        raise failure
        yield  # 生成器在 next 时失败，复现 _load 的错误路径。

    monkeypatch.setattr(writer, "read_bundles", broken)
    with pytest.raises(ContractViolationError) as caught:
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert caught.value is failure
    audit = case.conn.state["etl"][0]
    assert audit[3:5] == ("failed", 0)
    assert audit[12] == "ContractViolationError"
    assert "private-payload" not in repr(audit)
    request = audit[9].obj
    assert request["stage"] == "raw_read"
    assert request["selected_months"] == ["2024-02"]
    assert not case.conn.state["tables"]
    if identified:
        assert audit[6:9] == (date(2024, 2, 1),) * 3
        assert request["model_run_id"] == str(
            writer._model_run_id(case.options, failure.risk_day, failure.risk_observation_id)
        )
    else:
        assert audit[6:9] == (None, date(2024, 1, 2), date(2024, 2, 29))
        assert request["model_run_id"] is None


def test_failure_audit_error_preserves_original_exception(risk_case, monkeypatch):
    case = risk_case
    case.conn.fail_table = "factor.covariance"

    def fail_audit(*args, **kwargs):
        raise ConnectionError("private-connection-string")

    monkeypatch.setattr(writer, "_record_etl", fail_audit)
    with pytest.raises(RuntimeError, match="simulated database write") as caught:
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert caught.value.__notes__ == ["Failure audit unavailable: ConnectionError"]
    assert not case.conn.state["tables"]
    assert not case.conn.state["etl"]


def test_completed_day_survives_later_raw_read_failure(risk_case, monkeypatch):
    case = risk_case
    failure = ContractViolationError("raw day failed")
    failure.risk_day = date(2024, 1, 3)
    failure.risk_observation_id = "00000000000000000000000000000003"

    def broken_after_first(*args, **kwargs):
        yield case.manifest, case.frames
        raise failure

    monkeypatch.setattr(writer, "read_bundles", broken_after_first)
    with pytest.raises(ContractViolationError) as caught:
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert caught.value is failure
    assert len(case.conn.state["runs"]) == 1
    assert [row[3] for row in case.conn.state["etl"]] == ["success", "failed"]
    assert case.conn.state["etl"][-1][6:9] == (date(2024, 1, 3),) * 3
    assert {row["trading_day"] for row in records(case, "specific_return")} == {date(2024, 1, 2)}


def dynamic_case(case):
    """五个候选：完整两只、部分一只、未返回一只、SDK 过滤一只。"""
    case.options = replace(case.options, universe_policy="listed_cn_a_v1", order_book_ids=())
    case.conn.instruments += [
        ("600001.SH", "XSHG", 33),
        ("600002.SH", "XSHG", 44),
        ("600003.SH", "XSHG", 55),
    ]
    candidates = []
    coverage = []
    for symbol, exchange, instrument_id in sorted(case.conn.instruments, key=lambda row: row[2]):
        code = symbol[:6] + "." + exchange
        filtered = instrument_id == 55
        candidate = {
            "instrument_id": instrument_id,
            "canonical_symbol": symbol,
            "input_codes": [code],
            "request_code": None if filtered else code,
            "status": "sdk_filtered" if filtered else None,
            "evidence": {"reason": "synthetic-stock-evidence"},
        }
        candidates.append(candidate)
        status = {
            11: "included",
            22: "included",
            33: "partial_bundle",
            44: "provider_not_returned",
            55: "sdk_filtered",
        }[instrument_id]
        coverage.append(
            {
                **candidate,
                "status": status,
                "pieces": {
                    "exposure": instrument_id in {11, 22, 33},
                    "specific_return": instrument_id in {11, 22},
                    "specific_risk": instrument_id in {11, 22},
                },
            }
        )
    universe = {
        "day": case.manifest["day"],
        "policy": case.options.universe_policy,
        "mapping_version": case.options.mapping_version,
        "metadata_hash": "fixture",
        "candidates": candidates,
        "unresolved": [],
        "reference": {
            "snapshot_hash": "0" * 64,
            "sdk_version": "synthetic",
            "boundary_rule": "listed_date <= day < de_listed_date",
            "alias_selection_rule": "canonical_preferred_if_multiple_accepted",
        },
    }
    case.manifest.update(
        variant_id=case.options.variant_id,
        identity=case.options.identity,
        purpose="validation",
        universe=universe,
        universe_hash=semantic_hash(universe),
        coverage=coverage,
        coverage_hash=semantic_hash(coverage),
        coverage_counts={
            "included": 2,
            "partial_bundle": 1,
            "provider_not_returned": 1,
            "sdk_filtered": 1,
            "candidate": 5,
            "complete": 2,
            "not_returned": 1,
            "anomalous": 2,
        },
        files={name: "0" * 64 for name in case.frames},
    )
    return case


def test_dynamic_partial_bundle_atomic_coverage_and_metadata(risk_case, caplog):
    case = dynamic_case(risk_case)
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert result.rows_written == 13  # 五件套 8 行，覆盖账本 5 行。
    assert result.ok  # 已记录的覆盖降级不触发 CLI 数值复核退出码。
    assert "Degraded coverage" in caplog.text
    ledger = records(case, "model_run_coverage")
    assert len(ledger) == 5
    assert {row["instrument_id"] for row in records(case, "exposure")} == {11, 22}
    assert {row["instrument_id"] for row in records(case, "specific_return")} == {11, 22}
    assert {row["instrument_id"] for row in records(case, "specific_risk")} == {11, 22}
    run_id, run = next(iter(case.conn.state["runs"].items()))
    assert run[8]["purpose"] == "validation" and run[9] is False
    assert run[8]["coverage_hash"] == case.manifest["coverage_hash"]
    assert run[8]["universe_hash"] == case.manifest["universe_hash"]
    assert all(row["run_id"] == run_id and row["trading_day"] == date(2024, 1, 2) for row in ledger)
    assert all(
        row["available_at"] == datetime.fromisoformat(case.manifest["observed_at"])
        for row in ledger
    )
    audit = case.conn.state["etl"][0]
    assert audit[3:6] == ("success", 13, 1)
    assert audit[9].obj["coverage_degraded"] is True
    assert audit[9].obj["manifest_ref"].endswith("/manifest.json")
    assert "factor.model_run_coverage" in case.conn.state["owners"]
    assert writer.contracts.MODEL_RUN_COVERAGE in writer._CONTRACTS
    common = audit[9].obj["universe_evidence"]
    assert common == run[8]["universe_evidence"]
    assert common["sdk_version"] == "synthetic"
    assert common["alias_selection_rule"] == "canonical_preferred_if_multiple_accepted"
    assert all(row["evidence"] == {"reason": "synthetic-stock-evidence"} for row in ledger)


def test_dynamic_replay_and_coverage_tampering(risk_case):
    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    before = copy.deepcopy(case.conn.state["tables"])
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["tables"] == before
    case.manifest["coverage"][0]["evidence"]["reason"] = "new proof"
    case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    # candidate 和覆盖共享 fixture 的 evidence，需要同步 universe hash。
    case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    with pytest.raises(ContractViolationError, match="Immutable"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["tables"] == before
    assert case.conn.state["etl"][-1][3] == "failed"


@pytest.mark.parametrize("status", ["unmapped_symbol", "sdk_filtered", "universe_boundary_unknown"])
@pytest.mark.parametrize("defect", ["request_code", "returned_piece"])
def test_dynamic_unrequested_status_rejects_request_or_data(risk_case, status, defect):
    case = dynamic_case(risk_case)
    candidate = case.manifest["universe"]["candidates"][-1]
    entry = case.manifest["coverage"][-1]
    candidate["status"] = entry["status"] = status
    if defect == "request_code":
        candidate["request_code"] = entry["request_code"] = "600003.XSHG"
    else:
        entry["pieces"]["exposure"] = True
    case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    with pytest.raises(ContractViolationError, match="unrequested candidate"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]
    assert case.conn.state["etl"][-1][3] == "failed"


def test_dynamic_rejects_shared_snapshot_in_stock_evidence(risk_case):
    case = dynamic_case(risk_case)
    case.manifest["coverage"][0]["evidence"]["supplier_snapshot"] = {"instruments": []}
    case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    with pytest.raises(ContractViolationError, match="invalid status, codes or pieces"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]


def test_dynamic_existing_coverage_cannot_be_partially_replaced(risk_case):
    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    ledger = case.conn.state["tables"]["factor.model_run_coverage"]
    ledger.pop(next(iter(ledger)))
    with pytest.raises(ContractViolationError, match="Immutable RiceQuant coverage"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert len(case.conn.state["tables"]["factor.model_run_coverage"]) == 4


def test_dynamic_coverage_write_failure_rolls_back_entire_day(risk_case):
    case = dynamic_case(risk_case)
    case.conn.fail_table = "factor.model_run_coverage"
    with pytest.raises(RuntimeError, match="simulated"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"] and not case.conn.state["runs"]
    assert not case.conn.state["owners"]
    assert [row[3] for row in case.conn.state["etl"]] == ["failed"]


def test_dynamic_coverage_owner_conflict_is_atomic(risk_case):
    case = dynamic_case(risk_case)
    case.conn.state["owners"]["factor.model_run_coverage"] = (
        "factor.model_run_coverage",
        "datayes",
        "ingest",
    )
    with pytest.raises(OwnershipError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"] and not case.conn.state["runs"]
    assert set(case.conn.state["owners"]) == {"factor.model_run_coverage"}


@pytest.mark.parametrize(
    "mutation",
    ["unresolved", "empty", "hash", "date", "intersection", "numeric_status", "duplicate"],
)
def test_dynamic_invalid_ledger_rejected_before_business_write(risk_case, mutation):
    case = dynamic_case(risk_case)
    if mutation == "unresolved":
        case.manifest["universe"]["unresolved"] = [{"code": "123456.XSHE"}]
        case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    elif mutation == "empty":
        case.frames["exposure"] = case.frames["exposure"].iloc[0:0]
        case.bundles[0] = (case.manifest, case.frames)
    elif mutation == "hash":
        case.manifest["coverage_hash"] = "1" * 64
    elif mutation == "date":
        case.frames["specific_return"].index = [date(2024, 1, 3)]
    elif mutation == "intersection":
        case.frames["specific_return"]["600001.XSHG"] = 0.0
    elif mutation == "numeric_status":
        case.manifest["coverage"][0]["status"] = "invalid_value"
        case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    else:
        case.manifest["coverage"][1]["instrument_id"] = 11
        case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    with pytest.raises(ContractViolationError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"] and not case.conn.state["runs"]
    assert case.conn.state["etl"][0][3] == "failed"


def test_fixed_alias_300114_resolves_verified_302132_identity(risk_case):
    case = risk_case
    case.conn.instruments[1] = ("302132.SZ", "XSHE", 22)
    case.conn.aliases = [("tushare", "300114.SZ", 22)]
    assert writer._instrument_ids(case.conn, ["300114.XSHE"]) == [22]
    case.conn.aliases.append(("ricequant", "300114.XSHE", 11))
    with pytest.raises(ContractViolationError, match="Conflicting"):
        writer._instrument_ids(case.conn, ["300114.XSHE"])


def test_alias_conflict_and_same_instrument_twice_are_rejected(risk_case):
    case = risk_case
    case.conn.instruments.append(("300114.SZ", "XSHE", 33))
    case.conn.aliases = [("tushare", "300114.SZ", 22)]
    with pytest.raises(ContractViolationError, match="Conflicting"):
        writer._instrument_ids(case.conn, ["300114.XSHE"])
    case.conn.instruments.pop()
    with pytest.raises(ContractViolationError, match="duplicate canonical"):
        writer._instrument_ids(case.conn, ["000001.XSHE", "300114.XSHE"])


def test_dynamic_old_canonical_replay_requires_retained_alias(risk_case):
    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    case.conn.instruments[1] = ("302132.SZ", "XSHE", 22)
    case.conn.aliases = [("tushare", "000001.SZ", 22)]
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert len(case.conn.state["runs"]) == 1
    # 同证券换码不妨碍重放；把旧代码改指向另一证券才会被拒绝。
    case.conn.aliases = [("tushare", "000001.SZ", 11)]
    with pytest.raises(ContractViolationError, match="Conflicting"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)


def prepare_dynamic_pg(case, pg_conn, monkeypatch):
    """保留固定 raw fixture，但恢复真实 COPY/JSONB writer 与一次性 PostgreSQL。"""
    from gr_data.db.copy import upsert_rows

    dynamic_case(case)
    with pg_conn.cursor() as cur:
        for symbol, exchange, instrument_id in case.conn.instruments:
            cur.execute(
                "INSERT INTO meta.instruments (instrument_id,symbol,asset,exchange) "
                "VALUES (%s,%s,'stock',%s)",
                (instrument_id, symbol, exchange),
            )
    pg_conn.commit()
    case.conn = pg_conn
    monkeypatch.setattr(writer, "upsert_rows", upsert_rows)
    return case


def test_dynamic_pg_partial_coverage_copy_and_replay(risk_case, pg_conn, monkeypatch):
    case = prepare_dynamic_pg(risk_case, pg_conn, monkeypatch)
    result = writer.run_risk_ingest(pg_conn, case.ctx, case.options)
    assert result.rows_written == 13 and result.ok
    replay = writer.run_risk_ingest(pg_conn, case.ctx, case.options)
    assert replay.rows_written == 0
    with pg_conn.cursor() as cur:
        cur.execute("SELECT receipt_id,rows_written FROM ops.import_receipt")
        receipt = cur.fetchone()
        assert receipt[1] == 13
        cur.execute("SELECT receipt_id FROM factor.model_run_binding")
        assert cur.fetchone()[0] == receipt[0]
        cur.execute("SELECT import_receipt_id,watermark_date FROM ops.import_checkpoint")
        assert cur.fetchone() == (receipt[0], date(2024, 1, 2))
        cur.execute("SELECT run_id,units,calibrated FROM factor.model_run")
        rows = cur.fetchall()
        assert len(rows) == 1
        run_id, units, calibrated = rows[0]
        assert units["purpose"] == "validation" and calibrated is False
        cur.execute("SELECT status,count(*) FROM factor.model_run_coverage GROUP BY status")
        assert dict(cur.fetchall()) == {
            "included": 2,
            "partial_bundle": 1,
            "provider_not_returned": 1,
            "sdk_filtered": 1,
        }
        cur.execute(
            "SELECT input_codes,request_code,pieces,evidence,available_at,trading_day,run_id "
            "FROM factor.model_run_coverage WHERE instrument_id=33"
        )
        row = cur.fetchone()
        assert row[:4] == (
            ["600001.XSHG"],
            "600001.XSHG",
            {"exposure": True, "specific_return": False, "specific_risk": False},
            {"reason": "synthetic-stock-evidence"},
        )
        assert row[4:] == (
            datetime.fromisoformat(case.manifest["observed_at"]),
            date(2024, 1, 2),
            run_id,
        )
        for table in ("exposure", "specific_return", "specific_risk"):
            cur.execute(f"SELECT instrument_id FROM factor.{table} ORDER BY instrument_id")
            assert [row[0] for row in cur.fetchall()] == [11, 22]
        cur.execute("SELECT status,warning_count,request FROM ops.etl_job_run ORDER BY started_at")
        audit = cur.fetchall()
        assert len(audit) == 2
        assert all(
            row[0:2] == ("success", 1) and row[2]["coverage_hash"] == units["coverage_hash"]
            for row in audit
        )
    pg_conn.commit()


def test_dynamic_pg_coverage_failure_rolls_back_five_tables_and_run(
    risk_case, pg_conn, monkeypatch
):
    from gr_data.db.copy import upsert_rows
    from psycopg.errors import CheckViolation

    case = prepare_dynamic_pg(risk_case, pg_conn, monkeypatch)

    def invalid_coverage_copy(conn, contract, rows):
        if contract == writer.contracts.MODEL_RUN_COVERAGE:
            rows = [tuple([*rows[0][:3], [], *rows[0][4:]]), *rows[1:]]
        return upsert_rows(conn, contract, rows)

    monkeypatch.setattr(writer, "upsert_rows", invalid_coverage_copy)
    with pytest.raises(CheckViolation):
        writer.run_risk_ingest(pg_conn, case.ctx, case.options)
    with pg_conn.cursor() as cur:
        for table in (
            "model",
            "model_run",
            "exposure",
            "covariance",
            "factor_return",
            "specific_risk",
            "specific_return",
            "model_run_coverage",
        ):
            cur.execute(f"SELECT count(*) FROM factor.{table}")
            assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM meta.symbol_map")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM ops.table_ownership")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT status,trading_day,request,error FROM ops.etl_job_run")
        audit = cur.fetchall()
        assert len(audit) == 1
        assert audit[0][0:2] == ("failed", date(2024, 1, 2))
        assert audit[0][2]["coverage_counts"]["candidate"] == 5
        assert audit[0][3] == "CheckViolation"
    pg_conn.commit()


def test_pg_verified_300114_alias_and_conflict(risk_case, pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.instruments (instrument_id,symbol,asset,exchange) "
            "VALUES (22,'302132.SZ','stock','XSHE'),(33,'600000.SH','stock','XSHG')"
        )
        cur.execute(
            "INSERT INTO meta.symbol_map (instrument_id,source,source_symbol) "
            "VALUES (22,'tushare','300114.SZ')"
        )
    pg_conn.commit()
    assert writer._instrument_ids(pg_conn, ["300114.XSHE"]) == [22]
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.symbol_map (instrument_id,source,source_symbol) "
            "VALUES (33,'ricequant','300114.XSHE')"
        )
    pg_conn.commit()
    with pytest.raises(ContractViolationError, match="Conflicting"):
        writer._instrument_ids(pg_conn, ["300114.XSHE"])
    pg_conn.rollback()


def test_dynamic_sdk_conversion_without_verified_db_alias_is_rejected(risk_case):
    """SDK 转换及 raw 证据完整，仍不能代替工作库中已核实的证券别名。"""
    from gr_data.common.ricequant_universe import build_universe_provider
    from gr_data.raw.ricequant.risk_dynamic import assess_coverage

    case = risk_case
    case.options = replace(case.options, universe_policy="listed_cn_a_v1", order_book_ids=())
    new_code = "600099.XSHG"
    sdk_mapping = {"000001.XSHE": "000001.XSHE", "600000.XSHG": new_code}
    metadata = {
        "instruments": [
            {
                "instrument_id": instrument_id,
                "symbol": symbol,
                "exchange": exchange,
                "list_date": "2000-01-01",
                "delist_date": None,
                "status": "L",
            }
            for symbol, exchange, instrument_id in case.conn.instruments
        ],
        "aliases": [],
    }
    reference = {
        "sdk_version": "fixture",
        "instruments": [
            {
                "order_book_id": code,
                "listed_date": "2000-01-01",
                "de_listed_date": "0000-00-00",
            }
            for code in sdk_mapping.values()
        ],
        "sdk_mapping": sdk_mapping,
    }
    universe = build_universe_provider(metadata, reference)(case.manifest["day"])
    case.frames["exposure"].rename(index={"600000.XSHG": new_code}, inplace=True)
    for name in ("specific_return", "specific_risk"):
        case.frames[name].rename(columns={"600000.XSHG": new_code}, inplace=True)
    coverage, counts, complete = assess_coverage(
        case.frames, universe, case.options, date(2024, 1, 2)
    )
    assert counts["complete"] == counts["candidate"] == 2
    assert universe["candidates"][0]["evidence"]["sdk_mapping"] == {"600000.XSHG": new_code}
    case.manifest.update(
        variant_id=case.options.variant_id,
        identity=case.options.identity,
        purpose="validation",
        universe=universe,
        universe_hash=semantic_hash(universe),
        coverage=coverage,
        coverage_hash=semantic_hash(coverage),
        coverage_counts=counts,
        files={name: "0" * 64 for name in complete},
    )
    case.bundles[0] = (case.manifest, complete)
    with pytest.raises(ContractViolationError, match="unmapped instrument: 600099.XSHG"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]  # 包括五件套、覆盖表及新增 symbol_map。
    assert not case.conn.state["runs"] and not case.conn.state["owners"]
    assert len(case.conn.state["etl"]) == 1
    audit = case.conn.state["etl"][0]
    assert audit[3:5] == ("failed", 0)
    assert audit[9].obj["stage"] == "write"
    assert audit[9].obj["coverage_counts"]["complete"] == 2


@pytest.mark.parametrize("defect", [None, "identity", "alias", "status", "conflict"])
def test_historical_unmapped_coverage_requires_exact_known_identity(risk_case, defect):
    case = dynamic_case(risk_case)
    case.conn.instruments.append(("T600018.SH", "XSHG", 99))
    candidate = {
        "instrument_id": 99,
        "canonical_symbol": "T600018.SH",
        "input_codes": ["T600018.SH"],
        "request_code": None,
        "status": "unmapped_symbol",
        "evidence": {"reason": "historical-canonical-code"},
    }
    if defect == "identity":
        candidate["instrument_id"] = 11
    elif defect == "alias":
        candidate["input_codes"].append("600018.XSHG")
    elif defect == "status":
        candidate["status"] = "sdk_filtered"
    elif defect == "conflict":
        case.conn.aliases.append(("tushare", "T600018.SH", 11))
        with pytest.raises(ContractViolationError, match="Conflicting historical stock aliases"):
            writer._verify_coverage_identities(case.conn, [candidate])
        return
    if defect:
        with pytest.raises(ContractViolationError, match="historical stock identity"):
            writer._verify_coverage_identities(case.conn, [candidate])
        return
    case.manifest["universe"]["candidates"].append(candidate)
    case.manifest["coverage"].append(
        {
            **candidate,
            "pieces": {
                "exposure": False,
                "specific_return": False,
                "specific_risk": False,
            },
        }
    )
    case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    case.manifest["coverage_counts"].update(unmapped_symbol=1, candidate=6, anomalous=3)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    row = next(row for row in records(case, "model_run_coverage") if row["instrument_id"] == 99)
    assert row["request_code"] is None and row["input_codes"] == ["T600018.SH"]
    assert all(row["instrument_id"] != 99 for row in records(case, "exposure"))


def test_dynamic_symbol_interval_evidence_and_shared_rule_pointer(risk_case):
    case = dynamic_case(risk_case)
    reference = case.manifest["universe"]["reference"]
    reference.update(symbol_rules_version="cn_stock_code_intervals_v1", symbol_rules_hash="a" * 64)
    proof = {"selected_source_symbol": "300114.SZ", "effective_from": "2010-08-27"}
    case.manifest["coverage"][0]["evidence"]["symbol_interval"] = proof
    case.manifest["coverage_hash"] = semantic_hash(case.manifest["coverage"])
    case.manifest["universe_hash"] = semantic_hash(case.manifest["universe"])
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    ledger = records(case, "model_run_coverage")
    assert ledger[0]["evidence"]["symbol_interval"] == proof
    run = next(iter(case.conn.state["runs"].values()))
    common = run[8]["universe_evidence"]
    assert common["symbol_rules_version"] == "cn_stock_code_intervals_v1"
    assert common["symbol_rules_hash"] == "a" * 64
    assert case.conn.state["etl"][0][9].obj["universe_evidence"] == common
    assert all("symbol_rules_hash" not in row["evidence"] for row in ledger)


def test_dynamic_capture_survives_write_failure_and_retry_binds_receipt(risk_case):
    case = dynamic_case(risk_case)
    case.conn.fail_table = "factor.covariance"
    with pytest.raises(RuntimeError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    checkpoint = next(iter(case.conn.state["checkpoints"].values()))
    assert checkpoint[0][3] == semantic_hash(case.manifest)
    assert checkpoint[1] is None
    assert not case.conn.state.get("receipts")
    assert not case.conn.state.get("bindings")
    case.conn.fail_table = None
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    receipt = next(iter(case.conn.state["receipts"].values()))
    binding = next(iter(case.conn.state["bindings"].values()))
    checkpoint = next(iter(case.conn.state["checkpoints"].values()))
    assert receipt[1] == "factor.risk_bundle"
    assert receipt[3] == semantic_hash(case.manifest)
    assert receipt[7] == 13
    assert binding[1:] == (
        receipt[0],
        case.options.variant_id,
        case.manifest["observation_id"],
        date(2024, 1, 2),
    )
    assert checkpoint[1] == (receipt[0], receipt[9], date(2024, 1, 2))
    assert [row[3] for row in case.conn.state["etl"]] == ["failed", "success"]


def test_dynamic_receipt_replay_never_upserts_business(risk_case, monkeypatch):
    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    before = copy.deepcopy(case.conn.state)

    def unexpected_write(*args, **kwargs):
        raise AssertionError("Receipt replay must not upsert business rows")

    monkeypatch.setattr(writer, "upsert_rows", unexpected_write)
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert result.rows_written == 0
    for key in ("tables", "runs", "receipts", "bindings", "checkpoints", "variants"):
        assert case.conn.state[key] == before[key]
    audit = case.conn.state["etl"][-1]
    assert audit[4] == 0 and audit[9].obj["replay"] is True
    assert audit[9].obj["receipt_id"] == str(next(iter(case.conn.state["receipts"].values()))[0])


def test_receipt_failure_rolls_back_business_but_keeps_capture(risk_case, monkeypatch):
    case = dynamic_case(risk_case)
    commit = writer.commit_receipt

    def fail_after_receipt(*args, **kwargs):
        commit(*args, **kwargs)
        raise RuntimeError("crash before transaction commit")

    monkeypatch.setattr(writer, "commit_receipt", fail_after_receipt)
    with pytest.raises(RuntimeError, match="crash"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"] and not case.conn.state["runs"]
    assert not case.conn.state.get("receipts") and not case.conn.state.get("bindings")
    assert next(iter(case.conn.state["checkpoints"].values()))[1] is None
    assert case.conn.state["etl"][-1][3] == "failed"


def production_case(case):
    case = dynamic_case(case)
    case.options = replace(case.options, purpose="production")
    case.manifest.update(
        purpose="production", identity=case.options.identity, variant_id=case.options.variant_id
    )
    return case


def test_production_degraded_receipt_commits_then_stops_batch(risk_case):
    case = production_case(risk_case)
    case.bundles.append((case.manifest, case.frames))
    with pytest.raises(writer.PublicationGateError, match="committed but publication ineligible"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    receipt = next(iter(case.conn.state["receipts"].values()))
    assert receipt[8]["publication_eligible"] is False
    assert receipt[8]["publication_reasons"] == ["complete_coverage_below_99_9_percent"]
    assert len(case.conn.state["etl"]) == 1
    assert case.conn.state["etl"][0][3:5] == ("success", 13)
    assert len(case.conn.state["runs"]) == len(case.conn.state["bindings"]) == 1
    assert next(iter(case.conn.state["checkpoints"].values()))[1] is not None
    # 同一不合格收据重放也停止，不能靠续跑跳过发布门槛。
    with pytest.raises(writer.PublicationGateError):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["etl"][-1][4] == 0


@pytest.mark.parametrize(
    ("candidate", "complete", "boundary", "unmapped", "eligible"),
    [
        (1000, 999, 0, 0, True),
        (1001, 999, 0, 0, False),
        (10000, 9990, 0, 0, True),
        (1000, 1000, 1, 0, False),
        (1000, 1000, 0, 1, False),
    ],
)
def test_publication_coverage_integer_boundary(candidate, complete, boundary, unmapped, eligible):
    quality = writer._publication_quality(
        {
            "coverage_counts": {
                "candidate": candidate,
                "complete": complete,
                "universe_boundary_unknown": boundary,
                "unmapped_symbol": unmapped,
            }
        }
    )
    assert quality["publication_eligible"] is eligible


def test_variant_purpose_cannot_change_existing_registration(risk_case):
    from gr_data.db.risk_receipts import prepare_capture

    case = dynamic_case(risk_case)
    prepare_capture(case.conn, case.options)
    registered = case.conn.state["variants"][case.options.variant_id]
    case.conn.state["variants"][case.options.variant_id] = (
        *registered[:3],
        "production",
        registered[4],
    )
    with pytest.raises(ContractViolationError, match="Immutable RiceQuant dataset variant"):
        prepare_capture(case.conn, case.options)


@pytest.mark.parametrize("missing", ["binding", "checkpoint"])
def test_lone_receipt_cannot_skip_incomplete_commit(risk_case, missing):
    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    if missing == "binding":
        case.conn.state["bindings"].clear()
    else:
        next(iter(case.conn.state["checkpoints"].values()))[1] = None
    before = copy.deepcopy(case.conn.state["tables"])
    with pytest.raises(ContractViolationError, match="no matching"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["tables"] == before
    assert case.conn.state["etl"][-1][3] == "failed"


def test_production_complete_receipt_is_publication_eligible(risk_case):
    case = production_case(risk_case)
    case.manifest["coverage"] = case.manifest["coverage"][:2]
    case.manifest["universe"]["candidates"] = case.manifest["universe"]["candidates"][:2]
    case.manifest.update(
        coverage_hash=semantic_hash(case.manifest["coverage"]),
        universe_hash=semantic_hash(case.manifest["universe"]),
        coverage_counts={
            "included": 2,
            "candidate": 2,
            "complete": 2,
            "not_returned": 0,
            "anomalous": 0,
        },
    )
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert result.rows_written == 10 and result.ok
    receipt = next(iter(case.conn.state["receipts"].values()))
    assert receipt[8]["publication_eligible"] is True
    assert receipt[8]["publication_reasons"] == []


def test_production_cannot_use_legacy_path_without_receipts(risk_case):
    case = risk_case
    case.options = replace(case.options, purpose="production")
    with pytest.raises(ContractViolationError, match="dynamic universe receipts"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"] and not case.conn.state["etl"]


def test_capture_preflight_requires_migration_before_variant_registration(risk_case):
    from gr_data.db.risk_receipts import prepare_capture

    case = dynamic_case(risk_case)
    case.conn.receipt_migration_applied = False
    with pytest.raises(ContractViolationError, match="requires migration 049"):
        prepare_capture(case.conn, case.options)
    assert not case.conn.state.get("variants")
    assert not case.conn.state.get("checkpoints")


def setup_provider_case(case, monkeypatch):
    from gr_data import ingest
    from gr_data.config import ricequant
    from gr_data.ingest.base import IngestResult

    class Before:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            return IngestResult("before", "meta.fixture", 7, [])

    class After(Before):
        def run(self):
            pytest.fail("Importer after stopped risk bundle must not run")

    names = ["before", "rq_risk_model", "after"]
    registry = {"before": Before, "rq_risk_model": None, "after": After}
    monkeypatch.setattr(ingest, "_registry_groups", lambda _: (registry, {}))
    monkeypatch.setattr(ingest, "plan_importers", lambda *a, **k: names)
    monkeypatch.setattr(
        ricequant,
        "parse_ricequant_options",
        lambda *a, **k: SimpleNamespace(datasets={"rq_risk_model": case.options}),
    )
    monkeypatch.setattr(
        ingest, "_record_failure", lambda *a, **k: pytest.fail("False failure audit")
    )
    return SimpleNamespace(raw_root=case.ctx.paths.root)


def test_provider_preserves_committed_stop_without_failed_audit(risk_case, monkeypatch):
    from gr_data import ingest

    case = production_case(risk_case)
    case.options = replace(case.options, end_date=date(2024, 1, 5))
    cfg = setup_provider_case(case, monkeypatch)
    with pytest.raises(ingest.IngestRunStoppedError) as caught:
        ingest.run_provider("ricequant", case.conn, cfg, months=("2024-01",))
    stopped = caught.value
    assert stopped.stop.outcome == "publication_ineligible"
    assert [row.rows_written for row in stopped.completed] == [7, 13]
    assert stopped.skipped == ["after"]
    assert stopped.stop.committed_days == (date(2024, 1, 2),)
    assert stopped.stop.requested_end == date(2024, 1, 5)
    assert [row[3] for row in case.conn.state["etl"]] == ["success"]


def test_cli_reports_real_committed_stop_and_nonzero_code(risk_case, monkeypatch, capsys):
    from gr_data import cli

    case = production_case(risk_case)
    cfg = setup_provider_case(case, monkeypatch)
    monkeypatch.setattr(cli, "_pg", lambda _: None)

    @contextmanager
    def connect(*args):
        yield case.conn

    monkeypatch.setattr(cli, "connect", connect)
    args = SimpleNamespace(provider="ricequant", only=None, force_ownership=False, months="2024-01")
    assert cli.cmd_ingest(args, cfg) == cli.EXIT_INGEST_PUBLICATION_STOPPED == 4
    output = capsys.readouterr().err
    assert "数据已提交，发布资格不满足" in output
    assert "meta.fixture=7, factor.risk_bundle=13" in output
    assert "2024-01-02" in output and "after" in output
    assert "失败" not in output and "已提交: 无" not in output
    assert [row[3] for row in case.conn.state["etl"]] == ["success"]


@pytest.mark.parametrize("sqlstate", [None, "57P01", "40003"])
@pytest.mark.parametrize("connection_lost", [False, True])
def test_commit_response_lost_reconciles_or_reports_unknown_and_replays_zero(
    risk_case, monkeypatch, connection_lost, sqlstate
):
    from gr_data import ingest
    from psycopg import OperationalError

    case = dynamic_case(risk_case)
    cfg = setup_provider_case(case, monkeypatch)
    original_transaction = case.conn.transaction
    dropped = False

    @contextmanager
    def transaction_with_lost_response():
        nonlocal dropped
        with original_transaction():
            yield
        if not dropped and case.conn.state.get("receipts"):
            dropped = True
            if connection_lost:
                case.conn.info.transaction_status = TransactionStatus.UNKNOWN
            if sqlstate == "57P01":
                from psycopg.errors import AdminShutdown

                raise AdminShutdown("server connection terminated")
            if sqlstate == "40003":
                from psycopg.errors import StatementCompletionUnknown

                raise StatementCompletionUnknown("statement completion unknown")
            raise OperationalError("commit response lost")

    monkeypatch.setattr(case.conn, "transaction", transaction_with_lost_response)
    with pytest.raises(ingest.IngestRunStoppedError) as caught:
        ingest.run_provider("ricequant", case.conn, cfg)
    stop = caught.value.stop
    assert stop.outcome == ("commit_outcome_unknown" if connection_lost else "commit_confirmed")
    assert stop.result.rows_written == (0 if connection_lost else 13)
    assert [row[3] for row in case.conn.state["etl"]] == ["success"]
    # 新连接保留服务器端已经提交的状态；只使用已有 raw，不产生 SDK 请求。
    restored = MemoryConnection()
    restored.state = case.conn.state
    restored.instruments = case.conn.instruments
    case.conn = restored
    before = copy.deepcopy(case.conn.state)
    result = writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert result.rows_written == 0
    for key in ("tables", "runs", "receipts", "bindings", "checkpoints"):
        assert case.conn.state[key] == before[key]
    assert [row[3] for row in case.conn.state["etl"]] == ["success", "success"]


def test_importer_version_change_fails_before_business_rewrite(risk_case, monkeypatch):
    from gr_data.db import risk_receipts

    case = dynamic_case(risk_case)
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    before = copy.deepcopy(case.conn.state)
    monkeypatch.setattr(risk_receipts, "get_importer_version", lambda **kwargs: "2" * 40)
    monkeypatch.setattr(writer, "upsert_rows", lambda *a, **k: pytest.fail("Version rewrote rows"))
    with pytest.raises(ContractViolationError, match="another importer version"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    for key in ("tables", "runs", "receipts", "bindings", "checkpoints"):
        assert case.conn.state[key] == before[key]


def test_deferred_database_rejection_is_rollback_not_unknown_commit(risk_case, monkeypatch):
    from psycopg.errors import CheckViolation

    case = dynamic_case(risk_case)
    original_transaction = case.conn.transaction
    rejected = False

    @contextmanager
    def reject_at_commit():
        nonlocal rejected
        with original_transaction():
            yield
            if not rejected and case.conn.state.get("receipts"):
                rejected = True
                raise CheckViolation("deferred constraint rejected commit")

    monkeypatch.setattr(case.conn, "transaction", reject_at_commit)
    with pytest.raises(CheckViolation):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert not case.conn.state["tables"]
    assert not case.conn.state.get("receipts")
    assert [row[3] for row in case.conn.state["etl"]] == ["failed"]
    assert next(iter(case.conn.state["checkpoints"].values()))[1] is None


def test_explicit_observation_new_version_preserves_old_binding(risk_case, monkeypatch):
    from gr_data.db import risk_receipts

    case = dynamic_case(risk_case)
    selected = []

    def read_selected(*args, observation_id=None, **kwargs):
        selected.append(observation_id)
        return iter([(case.manifest, case.frames)])

    monkeypatch.setattr(writer, "read_bundles", read_selected)
    case.ctx.observation_id = case.manifest["observation_id"]
    writer.run_risk_ingest(case.conn, case.ctx, case.options)
    old_bindings = copy.deepcopy(case.conn.state["bindings"])
    old_receipts = copy.deepcopy(case.conn.state["receipts"])
    assert writer.run_risk_ingest(case.conn, case.ctx, case.options).rows_written == 0
    monkeypatch.setattr(risk_receipts, "get_importer_version", lambda **kwargs: "2" * 40)
    with pytest.raises(ContractViolationError, match="another importer version"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state["bindings"] == old_bindings
    assert case.conn.state["receipts"] == old_receipts
    case.manifest["observation_id"] = "3" * 32
    case.ctx.observation_id = "3" * 32
    assert writer.run_risk_ingest(case.conn, case.ctx, case.options).rows_written > 0
    assert len(case.conn.state["bindings"]) == 2
    assert all(case.conn.state["bindings"][key] == value for key, value in old_bindings.items())
    assert all(case.conn.state["receipts"][key] == value for key, value in old_receipts.items())
    assert selected == ["0" * 31 + "1"] * 3 + ["3" * 32]
