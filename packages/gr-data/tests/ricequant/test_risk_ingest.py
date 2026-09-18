"""风险五件套的事务、单位与不可变观测回归；数据库交互使用可回滚内存替身。"""

from __future__ import annotations

import copy
import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from gr_data.common.ownership import OwnershipError
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import ContractViolationError
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
        self.commits = 0
        self.rollbacks = 0
        self.fail_table = None
        self.locked = False

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
        if sql.startswith("LOCK TABLE ops.table_ownership"):
            self.conn.locked = True
        elif sql.startswith("SELECT target, provider, channel"):
            self.result = [state["owners"][params[0]]] if params[0] in state["owners"] else []
        elif "INSERT INTO ops.table_ownership" in sql:
            assert self.conn.locked
            state["owners"][params[0]] = tuple(params)
        elif sql.startswith("SELECT symbol, exchange, instrument_id"):
            assert params[0] == ["000001.SZ", "600000.SH"]
            self.result = self.conn.instruments
        elif sql.startswith("INSERT INTO factor.model_run"):
            assert "DO NOTHING" in sql
            row = (*params[:8], params[8].obj, *params[9:])
            state["runs"].setdefault(params[0], row)
        elif sql.startswith("SELECT run_id, model_id"):
            self.result = [state["runs"][params[0]]]
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
        record = dict(zip(contract.columns, row, strict=True))
        key = tuple(record[key] for key in contract.conflict_keys)
        table[key] = record
    return len(rows)


@pytest.fixture
def risk_case(monkeypatch, tmp_path):
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
    assert set(case.conn.state["owners"]) == {contract.qualified for contract in writer._CONTRACTS}
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
    assert case.conn.state == snapshot
    assert case.conn.rollbacks == 1


@pytest.mark.parametrize("fail_table", ["factor.covariance", "factor.specific_return"])
def test_write_failure_rolls_back_metadata_mapping_ownership_and_all_pieces(risk_case, fail_table):
    case = risk_case
    case.conn.fail_table = fail_table
    before = copy.deepcopy(case.conn.state)
    with pytest.raises(RuntimeError, match="simulated"):
        writer.run_risk_ingest(case.conn, case.ctx, case.options)
    assert case.conn.state == before
    assert case.conn.commits == 0
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
    assert case.conn.state == before


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
    assert case.conn.commits == 1
    assert case.conn.rollbacks == 1
    assert len(case.conn.state["runs"]) == 1
    assert len(case.conn.state["etl"]) == 1
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
