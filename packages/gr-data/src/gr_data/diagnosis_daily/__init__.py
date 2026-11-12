"""持仓诊断两阶段日更：离线准备，单连接原子发布。"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, LiteralString
from uuid import UUID

import polars as pl
import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from gr_data.common import contracts
from gr_data.common.contracts import TableContract
from gr_data.common.ownership import OwnershipManager
from gr_data.common.paths import RawPaths
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.db.postgres.risk_receipts import get_importer_version
from gr_data.db.postgres.sync import PgConfig, connect
from gr_data.diagnostic_publication import (
    BARRIER_KEY,
    ENHANCED_BASIC_DATASETS,
    Component,
    InputReceipt,
    accept_input,
    accept_risk_input,
    admit_risk_universe,
    publish_version,
    security_universe_hash,
)
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant.riskmodel import _model_run_id, run_risk_ingest
from gr_data.ingest.tushare.financial import write_annual_roe
from gr_data.ingest.tushare.industry import IndustrySnapshot, write_industry_snapshot

from ._bridge import publication_connection
from .collect import collect_risk, collect_tushare, normalize_tushare
from .evidence import digest, file_hash, fingerprints, write_frame, write_json


log = logging.getLogger(__name__)
METRICS = sorted(
    (
        "annual_variance",
        "volatility",
        "daily_prediction_volatility",
        "risk_contribution",
        "risk_contribution_ratio",
        "marginal_risk_contribution",
        "l3_effective_count",
    )
)
CONTRACT = "diag-publication-v3"
_CONTRACTS = {
    c.qualified: c
    for c in (
        contracts.INSTRUMENTS,
        contracts.SYMBOL_MAP,
        contracts.TRADING_CALENDAR,
        contracts.bar_1d("stock"),
        contracts.ADJ_FACTOR_TS,
        contracts.STOCK_SUSPEND_EVENT,
        contracts.STOCK_SUSPEND_COVERAGE,
        contracts.VALUATION_1D,
        contracts.INSTRUMENT_CATEGORY,
    )
}


def _row(conn: psycopg.Connection, query: LiteralString, args: tuple = ()) -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, args).fetchone()


def latest_publication(conn: psycopg.Connection) -> dict:
    row = _row(
        conn,
        (
            "SELECT "
            "p.*,v.available_options,diag.publication_is_valid(p.data_version_id)"
            " AS valid FROM diag.data_publication p JOIN diag.data_version v "
            "USING(data_version_id) ORDER BY publication_seq DESC LIMIT 1"
        ),
    )
    if not row:
        raise ValueError("Daily update requires an accepted initial publication")
    return row


def risk_options(conn: psycopg.Connection, day: date, publication: dict) -> RiskOptions:
    """沿用已验收 v2 源单位与换码规则，不从样例猜测。"""
    scope = publication["available_options"]["publication_scope"]
    row = _row(conn, "SELECT units FROM factor.model_run WHERE run_id=%s", (scope["run_id"],))
    units = row["units"]
    if (
        units["purpose"] != "production"
        or units["model"] != "v2"
        or units["universe_policy"] != "listed_cn_a_v2"
    ):
        raise ValueError("Daily update requires accepted production v2 source conventions")
    return RiskOptions(
        model="v2",
        industry_mapping=units["industry_mapping"],
        start_date=day,
        end_date=day,
        order_book_ids=(),
        source_units=units["source_units"],
        units_evidence=units["units_evidence"],
        universe_policy=units["universe_policy"],
        purpose="production",
        production_symbol_rules_version=units["universe_evidence"]["symbol_rules_version"],
    )


def prepare(
    pg: PgConfig,
    artifact: Path,
    day: date,
    *,
    tushare: Any,
    ricequant: Any,
    reuse_raw: Path | None = None,
) -> dict:
    """阶段A：只读PG，网络与预检均在发布屏障之外；失败仅落盘报告。"""
    artifact.mkdir(parents=True, exist_ok=True)
    phase = "initial_state"
    try:
        if (artifact / "prepared.json").exists():
            raise ValueError(
                "Prepared artifacts are immutable; use apply or a new artifact directory"
            )
        version = get_importer_version(require_clean=True)
        with connect(pg) as conn, conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            previous = latest_publication(conn)
            options = risk_options(conn, day, previous)
        if day <= previous["as_of_date"]:
            raise ValueError(
                "Target must follow the latest publication; replay an existing artifact with apply"
            )
        paths = RawPaths(artifact / "raw")
        if reuse_raw is not None:
            if reuse_raw.resolve() == paths.root.resolve():
                raise ValueError("Reused raw must be outside the new artifact raw directory")
            shutil.copytree(reuse_raw, paths.root, dirs_exist_ok=True)
        phase = "tushare_capture"
        if reuse_raw is None:
            observed = collect_tushare(tushare, paths, day, previous["as_of_date"])
        else:
            captured = json.loads(
                (paths.dataset_dir("tushare", "daily_capture") / "complete.json").read_text()
            )
            if captured["day"] != str(day) or captured["previous"] != str(previous["as_of_date"]):
                raise ValueError("Reused raw dates differ from the publication boundary")
            observed = datetime.fromisoformat(captured["observed_at"])
        phase = "canonical_preflight"
        with connect(pg) as conn, conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            conn.execute("SET LOCAL timezone='Asia/Shanghai'")
            current = latest_publication(conn)
            if current["data_version_id"] != previous["data_version_id"] or not current["valid"]:
                raise ValueError("Current publication changed or is invalid")
            frames, metadata, symbols, start = normalize_tushare(conn, paths, day, observed)
            ids = sorted(r["instrument_id"] for r in metadata["instruments"])
            before = fingerprints(conn, ids, start, day)
            owners = dict(
                conn.execute("SELECT target,provider FROM ops.table_ownership").fetchall()
            )
            for table in ENHANCED_BASIC_DATASETS:
                if table != "meta.symbol_map" and owners.get(table) != "tushare":
                    raise ValueError(f"Unexpected input owner: {table}")
            # 当前历史窗口可有IPO/停牌缺口；逐股历史计算按既有规则明确降级。
            history = conn.execute(
                (
                    "SELECT count(DISTINCT trading_day) FROM "
                    "market.stock_suspend_coverage WHERE source='tushare' AND trading_day"
                    " >= %s AND trading_day < %s"
                ),
                (start, day),
            ).fetchone()
            expected = conn.execute(
                (
                    "SELECT count(*) FROM meta.trading_calendar WHERE exchange='XSHG' AND"
                    " is_open AND trading_day >= %s AND trading_day < %s"
                ),
                (start, day),
            ).fetchone()
            if history is None or expected is None or history[0] != expected[0]:
                raise ValueError("Historical suspension coverage is incomplete")
        phase = "ricequant_capture_preflight"
        risk = collect_risk(ricequant, paths, day, options, metadata)
        if not set(risk["security_ids"]) <= set(symbols.values()):
            raise ValueError("Risk universe contains stocks outside the source target-day universe")
        for table, frame in frames.items():
            output = artifact / "canonical" / (table + ".parquet")
            output.parent.mkdir(exist_ok=True)
            write_frame(output, frame)
        files = {
            p.relative_to(artifact).as_posix(): file_hash(p)
            for p in (artifact / "canonical").glob("*.parquet")
        }
        raw_files = {
            p.relative_to(paths.root).as_posix(): file_hash(p)
            for p in paths.root.rglob("*")
            if p.is_file() and ".tmp-" not in p.name and not p.name.endswith(".lock")
        }
        options_dict = asdict(options)
        evidence = {
            "protocol": "diagnosis-daily-v1",
            "day": str(day),
            "history_start": str(start),
            "observed_at": str(observed),
            "importer_version": version,
            "previous_version": previous["data_version_id"],
            "owners": owners,
            "baseline": before,
            "baseline_ids": ids,
            "security_ids": risk["security_ids"],
            "industry_missing_ids": sorted(
                set(symbols.values()) - set(frames["classify.instrument_industry"]["instrument_id"])
            ),
            "options": options_dict,
            "risk_observation_id": risk["manifest"]["observation_id"],
            "risk_manifest_hash": digest(risk["manifest"]),
            "quality": risk["quality"],
            "canonical_files": files,
            "raw_files": raw_files,
            "raw_root": str(paths.root.resolve()),
        }
        evidence["artifact_hash"] = digest(evidence)
        evidence["version_id"] = f"diag-v3-{day:%Y%m%d}-daily-{evidence['artifact_hash'][:16]}"
        write_json(artifact / "prepared.json", evidence)
        write_json(
            artifact / "status.json",
            {"phase": "A", "status": "ready", "day": day, "version_id": evidence["version_id"]},
        )
        return evidence
    except Exception as exc:
        write_json(
            artifact / "status.json",
            {
                "phase": "A",
                "stage": phase,
                "status": "failed",
                "day": day,
                "reason": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise


def _load(artifact: Path) -> tuple[dict, dict[str, pl.DataFrame], RawPaths, RiskOptions]:
    data = json.loads((artifact / "prepared.json").read_text())
    if (
        digest({k: v for k, v in data.items() if k not in {"artifact_hash", "version_id"}})
        != data["artifact_hash"]
    ):
        raise ValueError("Prepared artifact identity changed")
    if get_importer_version(require_clean=True) != data["importer_version"]:
        raise ValueError("Importer changed since phase A; prepare again")
    paths = RawPaths(data["raw_root"])
    frames = {}
    for name, expected in data["canonical_files"].items():
        path = artifact / name
        if not path.resolve().is_relative_to(artifact.resolve()) or file_hash(path) != expected:
            raise ValueError("Canonical artifact checksum mismatch")
        frames[path.stem] = pl.read_parquet(path)
    for name, expected in data["raw_files"].items():
        path = paths.root / name
        if not path.resolve().is_relative_to(paths.root.resolve()) or file_hash(path) != expected:
            raise ValueError("Raw artifact checksum mismatch")
    opts = data["options"]
    opts["start_date"] = date.fromisoformat(opts["start_date"])
    opts["end_date"] = date.fromisoformat(opts["end_date"])
    opts["order_book_ids"] = tuple(opts["order_book_ids"])
    return data, frames, paths, RiskOptions(**opts)


def _upsert_changed(
    conn: psycopg.Connection,
    contract: TableContract,
    frame: pl.DataFrame,
    *,
    ignore: tuple[str, ...] = (),
) -> int:
    """COPY临时表再仅更新实质变化；不刷新无变化行的观察时间。"""
    if frame.is_empty():
        return 0
    columns = contract.columns
    updates = [c for c in columns if c not in contract.conflict_keys]
    compared = [c for c in updates if c not in ignore]
    stage = sql.Identifier("daily_" + contract.table)
    table = sql.Identifier(contract.schema, contract.table)
    cols = sql.SQL(",").join(map(sql.Identifier, columns))
    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
            stage, table
        )
    )
    with conn.cursor() as cur:
        with cur.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(stage, cols)) as cp:
            types = contract.pg_types_for(columns)
            if types:
                cp.set_types(types)
            for row in frame.select(columns).iter_rows():
                cp.write_row(row)
        tail = sql.SQL("DO NOTHING")
        if updates:
            tail = sql.SQL("DO UPDATE SET {} WHERE ROW({}) IS DISTINCT FROM ROW({})").format(
                sql.SQL(",").join(
                    sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                    for c in updates
                ),
                sql.SQL(",").join(sql.Identifier("target", c) for c in compared),
                sql.SQL(",").join(sql.Identifier("excluded", c) for c in compared),
            )
        cur.execute(
            sql.SQL("INSERT INTO {} AS target ({}) SELECT {} FROM {} ON CONFLICT ({}) {}").format(
                table,
                cols,
                cols,
                stage,
                sql.SQL(",").join(map(sql.Identifier, contract.conflict_keys)),
                tail,
            )
        )
        count = cur.rowcount
        cur.execute(sql.SQL("DROP TABLE {}").format(stage))
    return count


async def _apply(
    conn: psycopg.Connection,
    data: dict,
    frames: dict[str, pl.DataFrame],
    paths: RawPaths,
    options: RiskOptions,
    *,
    fail_after: str | None = None,
) -> dict:
    c = publication_connection(conn)
    day = date.fromisoformat(data["day"])
    start = date.fromisoformat(data["history_start"])
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("Phase B requires one outer transaction")
    conn.execute("SET LOCAL lock_timeout='10s'")
    conn.execute("SET LOCAL statement_timeout='180s'")
    conn.execute("SET LOCAL timezone='Asia/Shanghai'")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (BARRIER_KEY,))
    old = _row(
        conn,
        (
            "SELECT diag.publication_is_valid(data_version_id) AS valid FROM "
            "diag.data_publication WHERE data_version_id=%s"
        ),
        (data["version_id"],),
    )
    if old:
        if not old["valid"]:
            raise ValueError("Existing daily publication is invalid; prepare a new observation")
        return {"version_id": data["version_id"], "replay": True, "business_rows_written": 0}
    current = latest_publication(conn)
    if current["data_version_id"] != data["previous_version"] or not current["valid"]:
        raise ValueError("Publication changed since phase A")
    # 屏障防止常规写入；锁定归属和身份，避免并发采集修改CAS前提。
    conn.execute(
        "LOCK TABLE ops.table_ownership,meta.instruments,meta.symbol_map IN "
        "SHARE ROW EXCLUSIVE MODE"
    )
    if fingerprints(conn, data["baseline_ids"], start, day) != data["baseline"]:
        raise ValueError("Canonical inputs changed since phase A")
    if (
        dict(conn.execute("SELECT target,provider FROM ops.table_ownership").fetchall())
        != data["owners"]
    ):
        raise ValueError("Input ownership changed since phase A")
    owner = OwnershipManager(conn)
    for table in _CONTRACTS:
        owner.check(table, "tushare")
        if table != "meta.symbol_map" and data["owners"].get(table) is None:
            owner.claim(table, "tushare")
    written = 0
    master = frames["meta.instruments"]
    existing_ids = {
        r[0] for r in conn.execute("SELECT instrument_id FROM meta.instruments").fetchall()
    }
    new_ids = set(master["instrument_id"]) - existing_ids
    if new_ids:
        maximum = conn.execute("SELECT max(instrument_id) FROM meta.instruments").fetchone()
        if maximum is None or min(new_ids) <= maximum[0]:
            raise ValueError("New stock identity allocation changed since phase A")
    master_contract = TableContract(
        schema="meta",
        table="instruments",
        columns=("instrument_id", *contracts.INSTRUMENTS.columns),
        conflict_keys=contracts.INSTRUMENTS.conflict_keys,
    )
    written += _upsert_changed(conn, master_contract, master)
    for table in (
        "meta.symbol_map",
        "meta.trading_calendar",
        "market.adj_factor_ts",
        "market.stock_suspend_event",
        "market.stock_suspend_coverage",
        "market.stock_bar_1d",
        "fundamental.valuation_1d",
        "classify.instrument_category",
    ):
        if table == "market.stock_suspend_event":
            # 源空响应也可撤销旧事件；只替换这批沪深股票的目标日事件。
            conn.execute(
                (
                    "DELETE FROM market.stock_suspend_event WHERE source='tushare' AND "
                    "trading_day=%s AND instrument_id=ANY(%s)"
                ),
                (day, data["baseline_ids"]),
            )
        written += _upsert_changed(conn, _CONTRACTS[table], frames[table], ignore=("available_at",))
    audit_file = paths.dataset_dir("tushare", "daily_capture") / "audits.json"
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES (%s,%s,%s)",
            json.loads(audit_file.read_text()),
        )
    await write_industry_snapshot(
        c,
        IndustrySnapshot(
            frames["classify.industry_node"],
            frames["classify.instrument_industry"],
            tuple(data["industry_missing_ids"]),
            frames["industry_closed"],
            day,
        ),
        expected_owners={
            t: data["owners"].get(t)
            for t in ("classify.scheme", "classify.industry_node", "classify.instrument_industry")
        },
    )
    await write_annual_roe(
        c,
        frames["fundamental.indicator_q"],
        expected_owner=data["owners"].get("fundamental.indicator_q"),
    )
    if fail_after == "basics":
        raise RuntimeError("Injected failure after basic writes")
    run_risk_ingest(
        conn,
        IngestContext(paths, observation_id=data["risk_observation_id"]),
        options,
        transaction_managed=True,
    )
    if fail_after == "risk":
        raise RuntimeError("Injected failure after risk writes")
    run_id = _model_run_id(options, str(day), data["risk_observation_id"])
    run = _row(
        conn,
        (
            "SELECT r.*,b.receipt_id FROM factor.model_run r JOIN "
            "factor.model_run_binding b USING(run_id) WHERE r.run_id=%s"
        ),
        (run_id,),
    )
    ids = data["security_ids"]
    fp = fingerprints(conn, data["baseline_ids"], start, day)
    components = []
    for table in ENHANCED_BASIC_DATASETS:
        providers = [data["owners"].get(table, "tushare")]
        if table == "meta.symbol_map":
            providers = [
                r[0]
                for r in conn.execute(
                    (
                        "SELECT DISTINCT source FROM meta.symbol_map WHERE "
                        "instrument_id=ANY(%s) ORDER BY source"
                    ),
                    (data["baseline_ids"],),
                ).fetchall()
            ]
        for provider in providers:
            part = f"daily-{day}-{provider}"
            evidence = {
                "kind": "two-phase-daily-v1",
                "artifact_hash": data["artifact_hash"],
                "row_fingerprint": fp[table],
                "source_partition": provider,
                "ownership_evidence": {
                    "provider": data["owners"].get(table),
                    "D012_source_partition": table == "meta.symbol_map",
                },
                "security_hash": security_universe_hash(ids),
                "observed_not_historical_pit": True,
            }
            head = _row(
                conn,
                (
                    "SELECT revision FROM ops.diag_input_head WHERE dataset_key=%s AND "
                    "partition_key=%s"
                ),
                (table, part),
            )
            await accept_input(
                c,
                InputReceipt(
                    table,
                    part,
                    provider,
                    digest(evidence),
                    data["importer_version"],
                    start,
                    day,
                    {"accepted": True},
                    evidence,
                ),
                expected_revision=head["revision"] if head else None,
            )
            components.append(Component(table, part, start, day))
    risk_part = f"daily-{day}-v2"
    head = _row(
        conn,
        (
            "SELECT revision FROM ops.diag_input_head WHERE "
            "dataset_key='factor.risk_bundle' AND partition_key=%s"
        ),
        (risk_part,),
    )
    await accept_risk_input(
        c,
        run_id=run_id,
        receipt_id=run["receipt_id"],
        as_of_date=day,
        partition_key=risk_part,
        expected_revision=head["revision"] if head else None,
    )
    components.append(Component("factor.risk_bundle", risk_part, day, day))
    proof = {
        "kind": "two-phase-daily-v1",
        "artifact_hash": data["artifact_hash"],
        "calibrated": False,
        "rc_definition": "volatility contribution; sum(RC)=sqrt(annual_variance)",
    }
    admission = await admit_risk_universe(
        c,
        run_id=run_id,
        receipt_id=run["receipt_id"],
        as_of_date=day,
        instrument_ids=ids,
        factor_order_hash=run["factor_order_hash"],
        units_evidence={
            "source_units": options.source_units,
            "evidence": options.units_evidence,
            "stored_variance": "pct2_annual",
        },
        evidence=proof,
        metrics=METRICS,
        contract_version=CONTRACT,
    )
    scope = {
        "scope_type": "security_universe",
        "as_of": str(day),
        "model": "v2",
        "run_id": str(run_id),
        "receipt_id": str(run["receipt_id"]),
        "metrics": METRICS,
        "security_ids": ids,
        "security_hash": security_universe_hash(ids),
        "universe_admission_id": str(admission),
        "calibrated": False,
    }
    await publish_version(
        c,
        version_id=data["version_id"],
        as_of_date=day,
        components=components,
        available_options={**current["available_options"], "publication_scope": scope},
        contract_version=CONTRACT,
    )
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
    if not _row(conn, "SELECT diag.publication_is_valid(%s) AS valid", (data["version_id"],))[
        "valid"
    ]:
        raise ValueError("Final publication failed validity check")
    if fail_after == "publication":
        raise RuntimeError("Injected failure after publication")
    if new_ids:
        conn.execute(
            "SELECT "
            "setval(pg_get_serial_sequence('meta.instruments','instrument_id'), "
            "greatest((SELECT max(instrument_id) FROM meta.instruments), (SELECT "
            "last_value FROM meta.instruments_instrument_id_seq)))"
        )
    return {
        "version_id": data["version_id"],
        "day": str(day),
        "replay": False,
        "business_rows_written": written,
        "security_count": len(ids),
        "run_id": str(run_id),
        "receipt_id": str(run["receipt_id"]),
        "fingerprints": fp,
    }


def apply(pg: PgConfig, artifact: Path, *, fail_after: str | None = None) -> dict:
    """阶段B没有供应商请求；成功在外层退出时一次提交，失败整笔回滚。"""
    try:
        data, frames, paths, options = _load(artifact)
        with connect(pg) as conn, conn.transaction():
            result = asyncio.run(_apply(conn, data, frames, paths, options, fail_after=fail_after))
        with connect(pg) as conn, conn.transaction():
            if not _row(
                conn, "SELECT diag.publication_is_valid(%s) AS valid", (result["version_id"],)
            )["valid"]:
                raise ValueError("Publication invalidated after commit; inspect external writes")
        write_json(artifact / "status.json", {"phase": "B", "status": "published", **result})
        return result
    except Exception as exc:
        write_json(
            artifact / "status.json",
            {
                "phase": "B",
                "status": "failed",
                "reason": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        raise
