"""米筐风险五件套入库：单日原子写入，保留观测时间与独立模型身份。"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from gr_data.common.contracts import factor as contracts
from gr_data.common.contracts.meta import SYMBOL_MAP
from gr_data.common.ownership import OwnershipError, OwnershipManager
from gr_data.common.ricequant_specs import ContractViolationError
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.db.copy import upsert_rows
from gr_data.ingest.base import IngestContext, IngestResult
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import read_bundles


log = logging.getLogger(__name__)
_CONTRACTS = (
    contracts.MODEL,
    contracts.DEFINITION,
    contracts.MODEL_RUN,
    contracts.EXPOSURE,
    contracts.COVARIANCE,
    contracts.FACTOR_RETURN,
    contracts.SPECIFIC_RISK,
    contracts.SPECIFIC_RETURN,
)
_COV_SCALE = {
    "dec2_daily": 10000.0 * 252,
    "pct2_daily": 252.0,
    "dec2_annual": 10000.0,
    "pct2_annual": 1.0,
}
_SIGMA_SQUARED_SCALE = {
    "dec_daily": 10000.0 * 252,
    "pct_daily": 252.0,
    "dec_annual": 10000.0,
    "pct_annual": 1.0,
}


def _hash_order(factors: list[str], *, sorted_set: bool = False) -> str:
    # 与现有 factor_order/set_hash 的分隔和 MD5 算法一致，不套用通联名称归一化。
    return hashlib.md5("|".join(sorted(factors) if sorted_set else factors).encode()).hexdigest()


def _checked(values: np.ndarray, label: str, *, real: bool = True) -> np.ndarray:
    if not np.isfinite(values).all():
        raise ContractViolationError(f"RiceQuant {label} contains non-finite normalized values")
    if real and (np.abs(values) > np.finfo(np.float32).max).any():
        raise ContractViolationError(f"RiceQuant {label} exceeds PostgreSQL REAL range")
    return values


def _normalize(frames: dict[str, pd.DataFrame], options: RiskOptions) -> dict[str, np.ndarray]:
    """按显式源单位转换；风险量统一年化百分比平方，收益保持各自日频契约。"""
    units = options.source_units
    sigma = frames["specific_risk"].to_numpy(dtype=float)
    if (sigma < 0).any():
        raise ContractViolationError("RiceQuant specific_risk sigma must be nonnegative")
    with np.errstate(over="ignore", invalid="ignore"):
        out = {
            "exposure": frames["exposure"].to_numpy(dtype=float),
            "covariance": frames["covariance"].to_numpy(dtype=float)
            * _COV_SCALE[units["covariance"]],
            "specific_risk": np.square(sigma) * _SIGMA_SQUARED_SCALE[units["specific_risk"]],
            "factor_return": frames["factor_return"].to_numpy(dtype=float)
            * {"dec_daily": 1.0, "pct_daily": 0.01}[units["factor_return"]],
            "specific_return": frames["specific_return"].to_numpy(dtype=float)
            * {"dec_daily": 100.0, "pct_daily": 1.0}[units["specific_return"]],
        }
    return {key: _checked(value, key, real=key != "covariance") for key, value in out.items()}


def _instrument_ids(conn: psycopg.Connection, symbols: list[str]) -> list[int]:
    canonical: list[tuple[str, str]] = []
    for symbol in symbols:
        match = re.fullmatch(r"([0-9]{6})\.(XSHG|XSHE)", symbol)
        if match is None:
            raise ContractViolationError(f"Unsupported RiceQuant stock symbol: {symbol}")
        code, exchange = match.groups()
        canonical.append((f"{code}.{'SH' if exchange == 'XSHG' else 'SZ'}", exchange))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, exchange, instrument_id FROM meta.instruments "
            "WHERE asset = 'stock' AND symbol = ANY(%s)",
            ([symbol for symbol, _ in canonical],),
        )
        rows = cur.fetchall()
    lookup: dict[tuple[str, str], int] = {}
    for symbol, exchange, instrument_id in rows:
        key = (symbol, exchange)
        if key in lookup:
            raise ContractViolationError(f"Ambiguous canonical stock instrument: {symbol}")
        lookup[key] = instrument_id
    missing = [source for source, key in zip(symbols, canonical, strict=True) if key not in lookup]
    if missing:
        raise ContractViolationError(
            f"RiceQuant risk import has {len(missing)} unmapped instruments; "
            f"first={missing[0]}; import canonical stock instruments first"
        )
    return [lookup[key] for key in canonical]


def _run_metadata(
    conn: psycopg.Connection,
    options: RiskOptions,
    manifest: dict[str, Any],
    order: list[str],
    observed_at: datetime,
) -> uuid.UUID:
    order_hash = _hash_order(order)
    identity = f"{options.model}|{options.industry_mapping}|{order_hash}"
    model_id = "rq_" + hashlib.sha256(identity.encode()).hexdigest()[:29]
    run_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"ricequant-risk:{options.variant_id}:{manifest['day']}:{manifest['observation_id']}",
    )
    units = {
        "mode": "normalized",
        "exposure": "zscore/dummy",
        "factor_return": "dec_daily",
        "specific_return": "pct_daily",
        "covariance": "pct2_annual",
        "specific_risk": "pct2_annual",
        "specific_risk_source_is_variance": False,
        "source_units": dict(options.source_units),
        "units_evidence": options.units_evidence,
        "model": options.model,
        "industry_mapping": options.industry_mapping,
        "variant_id": options.variant_id,
        "observation_id": manifest["observation_id"],
        "annualization_days": 252,
    }
    upsert_rows(
        conn,
        contracts.MODEL,
        [(model_id, f"米筐 {options.model} {options.industry_mapping}", "ricequant")],
    )
    definitions = [
        (
            model_id,
            name,
            name,
            "market"
            if name == "comovement"
            else "style"
            if name in STYLE_FACTORS[options.model]
            else "industry",
            ordinal,
        )
        for ordinal, name in enumerate(order)
    ]
    upsert_rows(conn, contracts.DEFINITION, definitions)
    row = (
        run_id,
        model_id,
        run_id.hex,
        order,
        len(order),
        order_hash,
        _hash_order(order, sorted_set=True),
        "annual_252",
        units,
        False,
        observed_at,
        "ricequant-risk-v1",
        None,  # 供应商未公开模型估计参数，不把采集配置冒充估计参数。
        "ricequant",
    )
    # 不使用通用 UPSERT：model_run 是不可变契约，重放只允许完全一致的元数据。
    columns = ", ".join(contracts.MODEL_RUN.columns)
    placeholders = ", ".join(["%s"] * len(row))
    payload = (*row[:8], Jsonb(units), *row[9:])
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO factor.model_run ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT (run_id) DO NOTHING",
            payload,
        )
        cur.execute(f"SELECT {columns} FROM factor.model_run WHERE run_id = %s", (run_id,))
        stored = cur.fetchone()
    if stored is None or tuple(stored) != row:
        raise ContractViolationError(f"Immutable RiceQuant model_run conflict: {run_id}")
    return run_id


def run_risk_ingest(
    conn: psycopg.Connection, ctx: IngestContext, options: RiskOptions
) -> IngestResult:
    """逐日读取经过校验的五件套并原子写库。

    Args:
        conn: 空闲 PostgreSQL 连接；每个观测日独立提交，失败日完整回滚。
        ctx: raw 路径和可选月份过滤；禁止通过 force_ownership 隐式切换源。
        options: 已确认模型、单位和标的范围的配置。

    Returns:
        五张业务数据表的累计写入行数，不含模型元数据、映射和 ETL 流水。

    Raises:
        OwnershipError: 风险表属于其他供应商或请求隐式强制切换。
        ContractViolationError: 映射缺失、数值溢出或不可变观测不一致。
        ValueError: 连接已有事务，避免提交或回滚调用者的其他操作。

    峰值内存为一个交易日的股票数乘因子数；风险数据 available_at 始终采用
    raw 实际观测时间，不将历史抓取伪装为当时已知的数据。
    """
    if ctx.force_ownership:
        raise OwnershipError("RiceQuant risk import requires explicit gr-data own release/set")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("RiceQuant risk import requires an idle connection")
    total = 0
    for manifest, frames in read_bundles(ctx.paths, options, months=ctx.months):
        day = date.fromisoformat(manifest["day"])
        observed_at = datetime.fromisoformat(manifest["observed_at"])
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ContractViolationError("RiceQuant observed_at must be timezone-aware")
        if manifest["variant_id"] != options.variant_id:
            raise ContractViolationError("RiceQuant risk raw variant does not match configuration")
        order = list(frames["exposure"].columns)
        if not order or len(order) > 32767 or any(len(name) > 32 for name in order):
            raise ContractViolationError("RiceQuant factor definitions exceed storage contract")
        values = _normalize(frames, options)
        symbols = list(frames["exposure"].index)
        with conn.transaction():
            # 与显式归属修改互斥，避免先检查归属、后写入期间发生切换。
            with conn.cursor() as cur:
                cur.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
            owner = OwnershipManager(conn)
            for contract in _CONTRACTS:
                owner.claim(contract.qualified, "ricequant", channel=ctx.channel, force=False)
            ids = _instrument_ids(conn, symbols)
            owner.claim(SYMBOL_MAP.qualified, "ricequant", channel=ctx.channel, force=False)
            upsert_rows(
                conn, SYMBOL_MAP, list(zip(ids, ["ricequant"] * len(ids), symbols, strict=True))
            )
            run_id = _run_metadata(conn, options, manifest, order, observed_at)
            count = len(order)
            rows = {
                contracts.EXPOSURE: [
                    (run_id, instrument_id, day, values["exposure"][i].tolist(), count, observed_at)
                    for i, instrument_id in enumerate(ids)
                ],
                contracts.COVARIANCE: [
                    (
                        run_id,
                        day,
                        values["covariance"][np.triu_indices(count)].tolist(),
                        count,
                        observed_at,
                    )
                ],
                contracts.FACTOR_RETURN: [
                    (run_id, day, values["factor_return"][0].tolist(), count, observed_at)
                ],
                contracts.SPECIFIC_RISK: [
                    (
                        run_id,
                        instrument_id,
                        day,
                        float(values["specific_risk"][0, i]),
                        "ricequant",
                        observed_at,
                    )
                    for i, instrument_id in enumerate(ids)
                ],
                contracts.SPECIFIC_RETURN: [
                    (
                        run_id,
                        instrument_id,
                        day,
                        float(values["specific_return"][0, i]),
                        observed_at,
                    )
                    for i, instrument_id in enumerate(ids)
                ],
            }
            written = sum(upsert_rows(conn, contract, data) for contract, data in rows.items())
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ops.etl_job_run "
                    "(job_name, provider, dataset_name, status, rows_written, warning_count, "
                    "started_at, finished_at) VALUES (%s, %s, %s, %s, %s, %s, now(), now())",
                    (
                        "ingest.ricequant.rq_risk_model",
                        "ricequant",
                        "rq_risk_model",
                        "success",
                        written,
                        0,
                    ),
                )
        total += written
        log.info(
            "Risk bundle imported provider=ricequant day=%s run_id=%s rows=%d", day, run_id, written
        )
    return IngestResult(dataset="rq_risk_model", target="factor.*", rows_written=total, warnings=[])
