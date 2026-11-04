"""真实 raw 的隔离库跨库重放验收，必须显式提供一次性库和冻结映射。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import pytest
import yaml
from gr_data.common.contracts import factor as contracts
from gr_data.common.ownership import OwnershipManager
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import semantic_hash
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.config.settings import load_postgres, make_pg_dsn
from gr_data.db.postgres import risk_receipts
from gr_data.db.postgres.copy import upsert_rows
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant import riskmodel as writer
from gr_data.ingest.ricequant.identity_mapping import IdentityMapping
from gr_data.raw.ricequant.riskmodel import read_bundles
from gr_tools.config import load_environment
from psycopg import sql
from psycopg.abc import QueryNoTemplate


def _scalar(conn: psycopg.Connection, query: QueryNoTemplate, params: tuple[Any, ...] = ()) -> Any:
    """读取必有结果的单值查询；无结果行直接判失败。"""
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _row_count(conn: psycopg.Connection, qualified: str) -> int:
    """统计 schema 全限定表的行数。"""
    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(*qualified.split(".")))
    return _scalar(conn, query)


@pytest.mark.skipif(not os.getenv("RQ_REPLAY_MAP"), reason="explicit isolated replay only")
def test_real_cross_database_replay(monkeypatch):
    root = Path(os.environ["RQ_REPLAY_ROOT"])
    env = load_environment(env_file="/Volumes/neoimac/project/getrich/.env")
    database = os.environ.get("RQ_REPLAY_DB", "getrich_rq_restore_20261101")
    assert database.startswith("getrich_rq_")
    cfg = replace(load_postgres(env), database=database)
    mapping = IdentityMapping(Path(os.environ["RQ_REPLAY_MAP"]), os.environ["RQ_REPLAY_HASH"])
    # 仅此隔离测试以待审源码内容哈希标记测试版本；生产入口的 Git 清洁门禁不变。
    source_hash = hashlib.sha256(Path(writer.__file__).read_bytes()).hexdigest()[:40]
    if os.getenv("RQ_REPLAY_COMMITTED") == "1":
        source_hash = risk_receipts.get_importer_version(require_clean=True)
    else:
        monkeypatch.setattr(risk_receipts, "get_importer_version", lambda **kwargs: source_hash)
    ledger = json.loads((root / "ledger.json").read_text())
    jobs = [*json.loads((root / "baseline.json").read_text())["jobs"], *ledger["jobs"].values()]
    selections = [("2024-01-02", m) for m in ("v1", "v2", "v2trd")]
    selections += [
        ("2024-01-30", "v1"),
        ("2024-12-11", "v2"),
        ("2025-02-14", "v2"),
        ("2025-02-17", "v2"),
        ("2026-10-21", "v2"),
    ]
    reports = []
    with psycopg.connect(make_pg_dsn(cfg)) as conn:
        # 隔离库沿用恢复后的真实主数据；所有风险表在写入前明确登记。
        conn.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
        owner = OwnershipManager(conn)
        for contract in writer._CONTRACTS:
            owner.claim(contract.qualified, "ricequant", channel="ingest", force=False)
        conn.commit()
        aliases_before = _scalar(conn, "select count(*) from meta.symbol_map")
        conn.commit()
        for day, model in selections:
            job = next(j for j in jobs if j["day"] == day and j["model"] == model)
            obs = job["import_evidence"]["capture_checkpoint"]["partition_key"].split("/")[-1]
            config = yaml.safe_load((root / f"templates/{model}.yaml").read_text())
            opts = parse_risk_options(config["providers"]["ricequant"]["risk_model"])
            opts = replace(
                opts, start_date=date.fromisoformat(day), end_date=date.fromisoformat(day)
            )
            ctx = IngestContext(
                RawPaths(Path("/Volumes/myssd/data/raw_parquet")), observation_id=obs
            )
            manifest, frames = next(read_bundles(ctx.paths, opts, observation_id=obs))
            original = semantic_hash(manifest)
            # 第一日写到 specific_risk 时失败，检查此前 COPY/模型元数据全部回滚。
            if not reports:
                tables = [c.qualified for c in writer._CONTRACTS]
                before = {t: _row_count(conn, t) for t in tables}
                conn.commit()

                def fail(c, contract, rows, _upsert=upsert_rows):
                    if contract == contracts.SPECIFIC_RISK:
                        raise RuntimeError("isolated rollback injection")
                    return _upsert(c, contract, rows)

                with monkeypatch.context() as patch:
                    patch.setattr(writer, "upsert_rows", fail)
                    with pytest.raises(RuntimeError, match="rollback injection"):
                        writer.run_risk_ingest(conn, ctx, opts, identity_mapping=mapping)
                assert {t: _row_count(conn, t) for t in tables} == before
                conn.commit()
            result = writer.run_risk_ingest(conn, ctx, opts, identity_mapping=mapping)
            run = writer._model_run_id(opts, day, obs)
            conn.commit()
            translated = mapping.translate(conn, manifest, manifest["coverage"])
            resolved = writer._verify_coverage_identities(conn, translated)
            ids = [resolved[s] for s in frames["exposure"].index]
            # 全行全元素独立归一化，REAL 二进制精确相等，协方差 DOUBLE 精确相等。
            expected = {
                "exposure": frames["exposure"].to_numpy().astype(np.float32),
                "specific_risk": (frames["specific_risk"].to_numpy() ** 2 * 10000).astype(
                    np.float32
                )[0],
                "specific_return": (frames["specific_return"].to_numpy() * 100).astype(np.float32)[
                    0
                ],
            }
            for table, column in [
                ("exposure", "exposure"),
                ("specific_risk", "specific_var"),
                ("specific_return", "specific_ret"),
            ]:
                rows = dict(
                    conn.execute(
                        sql.SQL("SELECT instrument_id,{} FROM {} WHERE run_id=%s").format(
                            sql.Identifier(column), sql.Identifier("factor", table)
                        ),
                        (run,),
                    ).fetchall()
                )
                actual = np.asarray([rows[i] for i in ids], dtype=np.float32)
                np.testing.assert_array_equal(actual, expected[table])
            factor_return = _scalar(
                conn, "SELECT ret_vector FROM factor.factor_return WHERE run_id=%s", (run,)
            )
            np.testing.assert_array_equal(
                np.asarray(factor_return, dtype=np.float32),
                frames["factor_return"].to_numpy().astype(np.float32)[0],
            )
            covariance = _scalar(
                conn, "SELECT cov_flat FROM factor.covariance WHERE run_id=%s", (run,)
            )
            matrix = frames["covariance"].to_numpy() * 10000
            np.testing.assert_array_equal(
                np.asarray(covariance), matrix[np.triu_indices(len(matrix))]
            )
            rows = conn.execute(
                (
                    "SELECT instrument_id,input_codes,request_code,status,pieces,evidence "
                    "FROM factor.model_run_coverage WHERE run_id=%s ORDER BY instrument_id"
                ),
                (run,),
            ).fetchall()
            expected_cov = sorted(translated, key=lambda r: r["instrument_id"])
            assert rows == [
                (
                    r["instrument_id"],
                    r["input_codes"],
                    r["request_code"],
                    r["status"],
                    r["pieces"],
                    r["evidence"],
                )
                for r in expected_cov
            ]
            units = _scalar(conn, "SELECT units FROM factor.model_run WHERE run_id=%s", (run,))
            assert units["cross_database_identity"] == mapping.evidence
            conn.commit()
            replay = writer.run_risk_ingest(conn, ctx, opts, identity_mapping=mapping)
            assert replay.rows_written == 0
            assert semantic_hash(manifest) == original
            assert _scalar(conn, "select count(*) from meta.symbol_map") == aliases_before
            conn.commit()
            reports.append(
                {
                    "day": day,
                    "model": model,
                    "observation_id": obs,
                    "rows": result.rows_written,
                    "all_values_equal": True,
                    "idempotent": True,
                    "coverage_equal": True,
                }
            )
        old = "4cc48d3d-663a-5fc9-be51-17548ec23966"  # 旧观察绝不作为修复日输入。
        assert not conn.execute("SELECT 1 FROM factor.model_run WHERE run_id=%s", (old,)).fetchall()
    Path(os.environ["RQ_REPLAY_REPORT"]).write_text(
        json.dumps(
            {
                "status": "passed",
                "test_source_version": source_hash,
                "mapping_sha256": mapping.digest,
                "rollback_verified": True,
                "observations": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
