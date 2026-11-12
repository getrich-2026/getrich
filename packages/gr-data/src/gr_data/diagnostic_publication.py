"""诊断专用收据与不可变发布；调用方负责外层事务，不提交无关写入。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from gr_data.db import DictConnection


BARRIER_KEY = 7342061105
BASIC_DATASETS = (
    "meta.instruments",
    "meta.symbol_map",
    "meta.trading_calendar",
    "market.stock_bar_1d",
    "market.stock_suspend_event",
    "market.stock_suspend_coverage",
    "fundamental.valuation_1d",
    "classify.instrument_category",
    "classify.instrument_industry",
    "classify.industry_node",
    "classify.scheme",
)


ENHANCED_BASIC_DATASETS = (*BASIC_DATASETS, "fundamental.indicator_q")


@dataclass(frozen=True)
class InputReceipt:
    """已验收的基础观察；日期范围和manifest为真实证据，不采集或填补数据。"""

    dataset_key: str
    partition_key: str
    provider: str
    manifest_hash: str
    importer_version: str
    coverage_start: date
    coverage_end: date
    quality: dict[str, Any]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class Component:
    """发布时必需组成与范围；实际收据和修订在写入屏障内解析一次。"""

    dataset_key: str
    partition_key: str
    coverage_start: date
    coverage_end: date


def portfolio_hash(holdings: Mapping[int, Decimal]) -> str:
    """精确非零权重规范化hash；不重新归一化，禁止float权重。"""
    if not holdings or any(
        not isinstance(w, Decimal) or not w.is_finite() or w < 0 for w in holdings.values()
    ):
        raise ValueError("Portfolio weights require finite nonnegative Decimal values")
    if sum(holdings.values(), Decimal(0)) != Decimal(1):
        raise ValueError("Portfolio weights must sum exactly to one")
    normalized = [[i, format(w.normalize(), "f")] for i, w in sorted(holdings.items()) if w != 0]
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


def security_universe_hash(instrument_ids: Sequence[int]) -> str:
    """证券清单hash，不含权重；拒绝空值、重复与非正整数ID，不改变组合语义。"""
    if not instrument_ids or any(type(i) is not int or i <= 0 for i in instrument_ids):
        raise ValueError("Security universe requires positive integer instrument IDs")
    if len(set(instrument_ids)) != len(instrument_ids):
        raise ValueError("Security universe contains duplicate instrument IDs")
    normalized = sorted(instrument_ids)
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


async def admit_risk_universe(
    conn: DictConnection,
    *,
    run_id: UUID,
    receipt_id: UUID,
    as_of_date: date,
    instrument_ids: Sequence[int],
    factor_order_hash: str,
    units_evidence: dict[str, Any],
    evidence: dict[str, Any],
    metrics: Sequence[str] = ("annual_variance", "daily_prediction_volatility", "volatility"),
    contract_version: str = "diag-publication-v2-universe",
) -> UUID:
    """验收同run证券清单内任意非负权重组合的指定指标，不扩为旧精确组合证据。

    所有证券的同日风险输入及生命周期由数据库检查，实际原件和数值复验由evidence固定。
    外层事务归调用方；同清单重放仅允许全部证据一致，新增清单使旧run发布失效。
    """
    scope = security_universe_hash(instrument_ids)
    ids = sorted(instrument_ids)
    metric_list = sorted(set(metrics))
    if not metric_list or len(metric_list) != len(metrics):
        raise ValueError("Universe metrics require a nonempty unique metric list")
    async with conn.transaction():
        await _barrier(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """SELECT * FROM factor.risk_universe_admission
                   WHERE run_id=%s AND security_hash=%s AND contract_version=%s""",
                (run_id, scope, contract_version),
            )
            old = await cur.fetchone()
            expected = {
                "run_id": run_id,
                "receipt_id": receipt_id,
                "as_of_date": as_of_date,
                "security_ids": ids,
                "security_hash": scope,
                "metrics": metric_list,
                "factor_order_hash": factor_order_hash,
                "units_evidence": units_evidence,
                "evidence": evidence,
            }
            if old:
                if any(old[k] != v for k, v in expected.items()):
                    raise ValueError("Immutable risk universe admission replay differs")
                return old["admission_id"]
            admission_id = uuid4()
            await cur.execute(
                """INSERT INTO factor.risk_universe_admission
                   (admission_id,run_id,receipt_id,as_of_date,security_ids,security_hash,
                    metrics,factor_order_hash,units_evidence,evidence,contract_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    admission_id,
                    run_id,
                    receipt_id,
                    as_of_date,
                    ids,
                    scope,
                    metric_list,
                    factor_order_hash,
                    Jsonb(units_evidence),
                    Jsonb(evidence),
                    contract_version,
                ),
            )
            await cur.executemany(
                """INSERT INTO factor.risk_universe_member(admission_id,instrument_id)
                   VALUES (%s,%s)""",
                [(admission_id, iid) for iid in ids],
            )
            return admission_id


async def _barrier(conn: DictConnection) -> None:
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (BARRIER_KEY,))


async def accept_input(
    conn: DictConnection,
    receipt: InputReceipt,
    *,
    expected_revision: int | None,
    write: Callable[[], Awaitable[None]] | None = None,
) -> UUID:
    """验收观察并原子切换head；相同收据重放不写canonical、不产生新失效。

    Args:
        conn: 调用方独占连接。内部savepoint失败回滚，外层提交由调用方负责。
        receipt: 验证通过的来源观察和范围；evidence记录验收源码、原件与授权。
        expected_revision: 当前head的CAS；首次None。不能据修订号推断供应商先后。
        write: 已完成网络准备的canonical写入；不允许自行commit或网络调用。
    Raises:
        ValueError: 未验收、归属冲突、修订过时或同观察证据不同。
    """
    if (
        receipt.dataset_key not in ENHANCED_BASIC_DATASETS
        or receipt.quality.get("accepted") is not True
        or not receipt.evidence
    ):
        raise ValueError("Diagnostic input needs accepted scoped evidence")
    async with conn.transaction():
        await _barrier(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT provider FROM ops.table_ownership WHERE target=%s", (receipt.dataset_key,)
            )
            owner = await cur.fetchone()
            if not owner and not receipt.evidence.get("ownership_evidence"):
                raise ValueError("Unregistered input source needs explicit ownership evidence")
            if (
                owner
                and owner["provider"] != receipt.provider
                and receipt.dataset_key != "meta.symbol_map"
            ):
                raise ValueError("Diagnostic input provider differs from table ownership")
            await cur.execute(
                """SELECT * FROM ops.diag_input_receipt WHERE dataset_key=%s
                AND partition_key=%s AND
                manifest_hash=%s AND importer_version=%s""",
                (
                    receipt.dataset_key,
                    receipt.partition_key,
                    receipt.manifest_hash,
                    receipt.importer_version,
                ),
            )
            old = await cur.fetchone()
            if old:
                if any(old[k] != getattr(receipt, k) for k in receipt.__dataclass_fields__):
                    raise ValueError("Immutable input receipt replay differs")
                return old["receipt_id"]
            await cur.execute(
                """SELECT revision FROM ops.diag_input_head WHERE dataset_key=%s
                AND partition_key=%s
                FOR UPDATE""",
                (receipt.dataset_key, receipt.partition_key),
            )
            head = await cur.fetchone()
            if (head["revision"] if head else None) != expected_revision:
                raise ValueError("Diagnostic input head changed; reassess source ordering")
            if write is not None:
                await write()
            rid = uuid4()
            await cur.execute(
                """INSERT INTO ops.diag_input_receipt
                (receipt_id,dataset_key,partition_key,provider,manifest_hash,importer_version,
                 coverage_start,coverage_end,quality,evidence)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    rid,
                    receipt.dataset_key,
                    receipt.partition_key,
                    receipt.provider,
                    receipt.manifest_hash,
                    receipt.importer_version,
                    receipt.coverage_start,
                    receipt.coverage_end,
                    Jsonb(receipt.quality),
                    Jsonb(receipt.evidence),
                ),
            )
            await cur.execute(
                """INSERT INTO
                ops.diag_input_head(dataset_key,partition_key,basic_receipt_id,revision,dirty)
                VALUES (%s,%s,%s,1,false) ON CONFLICT(dataset_key,partition_key) DO UPDATE
                SET basic_receipt_id=EXCLUDED.basic_receipt_id,risk_receipt_id=NULL,run_id=NULL,
                    revision=ops.diag_input_head.revision+1,dirty=false""",
                (receipt.dataset_key, receipt.partition_key, rid),
            )
            return rid


async def accept_risk_input(
    conn: DictConnection,
    *,
    run_id: UUID,
    receipt_id: UUID,
    as_of_date: date,
    partition_key: str,
    expected_revision: int | None,
) -> None:
    """将同日production风险收据设为head，不创建或改写风险run。"""
    async with conn.transaction():
        await _barrier(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT diag.risk_run_is_publishable(%s,%s,%s) AS valid",
                (run_id, receipt_id, as_of_date),
            )
            row = await cur.fetchone()
            if not row or not row["valid"]:
                raise ValueError(
                    "Risk run is disabled, validation-only, incomplete, or has unsupported units"
                )
            await cur.execute(
                """SELECT * FROM ops.diag_input_head WHERE dataset_key='factor.risk_bundle' AND
                partition_key=%s FOR UPDATE""",
                (partition_key,),
            )
            head = await cur.fetchone()
            if (
                head
                and not head["dirty"]
                and head["run_id"] == run_id
                and head["risk_receipt_id"] == receipt_id
            ):
                return
            if (head["revision"] if head else None) != expected_revision:
                raise ValueError("Risk head changed; reassess source ordering")
            await cur.execute(
                """INSERT INTO
                ops.diag_input_head(dataset_key,partition_key,risk_receipt_id,run_id,revision,dirty)
                VALUES ('factor.risk_bundle',%s,%s,%s,1,false)
                ON CONFLICT(dataset_key,partition_key) DO
                UPDATE
                SET
                risk_receipt_id=EXCLUDED.risk_receipt_id,run_id=EXCLUDED.run_id,basic_receipt_id=NULL,
                    revision=ops.diag_input_head.revision+1,dirty=false""",
                (partition_key, receipt_id, run_id),
            )


async def admit_risk_run(
    conn: DictConnection,
    *,
    run_id: UUID,
    receipt_id: UUID,
    as_of_date: date,
    holdings: Mapping[int, Decimal],
    factor_order_hash: str,
    units_evidence: dict[str, Any],
    evidence: dict[str, Any],
    metrics: Sequence[str] = ("annual_variance", "daily_prediction_volatility", "volatility"),
) -> UUID:
    """记录目标组合单日准入；不改变calibrated，重放仅允许全部证据相同。"""
    scope = portfolio_hash(holdings)
    async with conn.transaction():
        await _barrier(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM factor.risk_run_admission WHERE run_id=%s AND portfolio_hash=%s",
                (run_id, scope),
            )
            old = await cur.fetchone()
            expected = {
                "run_id": run_id,
                "receipt_id": receipt_id,
                "as_of_date": as_of_date,
                "portfolio_hash": scope,
                "factor_order_hash": factor_order_hash,
                "units_evidence": units_evidence,
                "evidence": evidence,
                "metrics": list(metrics),
            }
            if old:
                if any(old[k] != v for k, v in expected.items()):
                    raise ValueError("Immutable risk admission replay differs")
                return old["admission_id"]
            admission_id = uuid4()
            await cur.execute(
                """INSERT INTO factor.risk_run_admission
                (admission_id,run_id,receipt_id,as_of_date,portfolio_hash,metrics,factor_order_hash,units_evidence,evidence)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    admission_id,
                    run_id,
                    receipt_id,
                    as_of_date,
                    scope,
                    list(metrics),
                    factor_order_hash,
                    Jsonb(units_evidence),
                    Jsonb(evidence),
                ),
            )
            return admission_id


async def publish_version(
    conn: DictConnection,
    *,
    version_id: str,
    as_of_date: date,
    components: Sequence[Component],
    available_options: dict[str, Any],
    contract_version: str | None = None,
) -> str:
    """在排他屏障内一次发布完整清单；最新失效版本不能原地复活。

    收据包含源范围和验收证据。发布不填补数据、不做历史PIT认证。
    同version重放必须清单完全一致；已失效时拒绝发布同一version。
    """
    universe_scope = (available_options.get("publication_scope") or {}).get(
        "scope_type"
    ) == "security_universe"
    contract = contract_version or (
        "diag-publication-v2-universe" if universe_scope else "diag-publication-v1"
    )
    if contract not in {
        "diag-publication-v1",
        "diag-publication-v2-universe",
        "diag-publication-v3",
    }:
        raise ValueError("Unsupported diagnostic publication contract")
    required = ENHANCED_BASIC_DATASETS if contract == "diag-publication-v3" else BASIC_DATASETS
    keys = {(c.dataset_key, c.partition_key) for c in components}
    if len(keys) != len(components) or not set(required) <= {c.dataset_key for c in components}:
        raise ValueError(
            "Publication requires every diagnostic base dataset exactly once per partition"
        )
    async with conn.transaction():
        await _barrier(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            resolved = []
            for component in sorted(components, key=lambda c: (c.dataset_key, c.partition_key)):
                await cur.execute(
                    """SELECT * FROM ops.diag_input_head WHERE dataset_key=%s
                    AND partition_key=%s FOR
                    UPDATE""",
                    (component.dataset_key, component.partition_key),
                )
                h = await cur.fetchone()
                if not h or h["dirty"]:
                    raise ValueError("Publication input missing or dirty")
                resolved.append(
                    {
                        "dataset_key": component.dataset_key,
                        "partition_key": component.partition_key,
                        "coverage_start": component.coverage_start,
                        "coverage_end": component.coverage_end,
                        "basic_receipt_id": h["basic_receipt_id"],
                        "risk_receipt_id": h["risk_receipt_id"],
                        "run_id": h["run_id"],
                        "head_revision": h["revision"],
                    }
                )
            admissions = []
            for run_id in sorted({c["run_id"] for c in resolved if c["run_id"]}, key=str):
                await cur.execute(
                    """SELECT admission_id,portfolio_hash,metrics,factor_order_hash,
                              units_evidence,evidence FROM factor.risk_run_admission
                       WHERE run_id=%s ORDER BY portfolio_hash""",
                    (run_id,),
                )
                admissions.extend(await cur.fetchall())
            universe_admissions = []
            for run_id in sorted({c["run_id"] for c in resolved if c["run_id"]}, key=str):
                await cur.execute(
                    """SELECT admission_id,security_ids,security_hash,metrics,factor_order_hash,
                              units_evidence,evidence FROM factor.risk_universe_admission
                       WHERE run_id=%s ORDER BY security_hash,admission_id""",
                    (run_id,),
                )
                universe_admissions.extend(await cur.fetchall())
            manifest = {
                "as_of_date": str(as_of_date),
                "components": resolved,
                "admissions": admissions,
                "available_options": available_options,
            }
            scope = available_options.get("publication_scope") or {}
            universe_scope = scope.get("scope_type") == "security_universe"
            if universe_admissions:
                manifest["universe_admissions"] = universe_admissions
            if universe_scope:
                manifest["contract_version"] = contract
            digest = hashlib.sha256(
                json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode()
            ).hexdigest()
            await cur.execute(
                """SELECT p.*,v.available_options,
                diag.publication_is_valid(p.data_version_id) AS valid
                FROM diag.data_publication p JOIN diag.data_version v USING(data_version_id) WHERE
                p.data_version_id=%s""",
                (version_id,),
            )
            old = await cur.fetchone()
            if old:
                if not old["valid"] or old["manifest_hash"] != digest:
                    raise ValueError("Existing publication differs or is invalidated")
                return version_id
            await cur.execute("SELECT clock_timestamp() AS ts")
            stamp_row = await cur.fetchone()
            assert stamp_row is not None
            stamp = stamp_row["ts"]
            await cur.execute(
                """INSERT INTO
                diag.data_version(data_version_id,snapshot_at,schemas_covered,available_options)
                VALUES (%s,%s,%s,%s)""",
                (
                    version_id,
                    stamp,
                    ["meta", "market", "classify", "fundamental", "factor"],
                    Jsonb(available_options),
                ),
            )
            await cur.execute(
                """INSERT INTO
                diag.data_publication(data_version_id,as_of_date,published_at,manifest_hash,contract_version)
                VALUES (%s,%s,%s,%s,%s)""",
                (version_id, as_of_date, stamp, digest, contract),
            )
            for c in resolved:
                await cur.execute(
                    """INSERT INTO diag.data_version_component
                    (data_version_id,dataset_key,partition_key,coverage_start,coverage_end,basic_receipt_id,risk_receipt_id,run_id,head_revision)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        version_id,
                        c["dataset_key"],
                        c["partition_key"],
                        c["coverage_start"],
                        c["coverage_end"],
                        c["basic_receipt_id"],
                        c["risk_receipt_id"],
                        c["run_id"],
                        c["head_revision"],
                    ),
                )
            await cur.execute("SELECT diag.publication_is_valid(%s) AS valid", (version_id,))
            valid_row = await cur.fetchone()
            if not valid_row or not valid_row["valid"]:
                raise ValueError("Publication failed final admission")
            return version_id
