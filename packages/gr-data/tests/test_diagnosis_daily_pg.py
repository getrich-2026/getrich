"""显式一次性库与阶段A原件的事务验收；不默认触碰工作库。"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from gr_data.cli import _pg
from gr_data.config.pipeline import load_config
from gr_data.db.postgres.sync import connect
from gr_data.diagnosis_daily import apply, latest_publication, prepare
from gr_data.diagnosis_daily.evidence import digest, fingerprints
from gr_tools.config import load_environment


@pytest.fixture
def daily_case():
    database = os.environ.get("GETRICH_DIAG_DAILY_DB", "")
    path = os.environ.get("GETRICH_DIAG_DAILY_ARTIFACT", "")
    if not database or not path:
        pytest.skip("requires explicit isolated daily database and prepared artifact")
    assert database.startswith("getrich_diag_") and database != "getrich"
    cfg = load_config(environment=load_environment())
    pg = _pg(cfg)
    pg.dbname = database
    artifact = Path(path)
    data = json.loads((artifact / "prepared.json").read_text())
    return pg, artifact, data


def state(pg, data):
    with connect(pg) as conn, conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET LOCAL timezone='Asia/Shanghai'")
        publication = latest_publication(conn)
        inputs = fingerprints(
            conn,
            data["baseline_ids"],
            date.fromisoformat(data["history_start"]),
            date.fromisoformat(data["day"]),
        )
        audit = {}
        for table in (
            "ops.diag_input_head",
            "ops.diag_input_receipt",
            "factor.import_checkpoint",
            "factor.import_receipt",
            "factor.model_run_binding",
            "factor.model_run",
            "diag.data_publication",
            "diag.data_version_invalidation",
        ):
            # 固定表白名单，不接收外部SQL标识符。
            from psycopg import sql

            rows = conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.SQL(table)
                )
            ).fetchall()
            audit[table] = digest(rows)
        return {
            "publication": publication["data_version_id"],
            "valid": publication["valid"],
            "inputs": inputs,
            "audit": audit,
        }


def test_phase_a_missing_vendor_input_preserves_publication(daily_case, monkeypatch, tmp_path):
    import gr_data.diagnosis_daily as daily

    pg, _, data = daily_case
    before = state(pg, data)

    def missing(*args):
        raise ValueError("Missing vendor closing data")

    monkeypatch.setattr(daily, "collect_tushare", missing)
    with pytest.raises(ValueError, match="Missing vendor"):
        prepare(pg, tmp_path, date.fromisoformat(data["day"]), tushare=Mock(), ricequant=Mock())
    assert state(pg, data) == before
    assert json.loads((tmp_path / "status.json").read_text())["stage"] == "tushare_capture"


@pytest.mark.parametrize("point", ["basics", "risk", "publication"])
def test_phase_b_failure_restores_all_inputs_receipts_and_publication(daily_case, point):
    pg, artifact, data = daily_case
    before = state(pg, data)
    assert before["valid"] and before["publication"] == data["previous_version"]
    with pytest.raises(RuntimeError, match="Injected failure"):
        apply(pg, artifact, fail_after=point)
    assert state(pg, data) == before


def test_normal_next_day_and_replay_zero_changes(daily_case):
    pg, artifact, data = daily_case
    result = apply(pg, artifact)
    assert not result["replay"] and result["version_id"] == data["version_id"]
    before = state(pg, data)
    assert before["valid"] and before["publication"] == data["version_id"]
    replay = apply(pg, artifact)
    assert replay["replay"] and replay["business_rows_written"] == 0
    assert state(pg, data) == before
