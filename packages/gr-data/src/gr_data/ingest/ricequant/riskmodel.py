"""米筐风险五件套入库：单日原子写入，保留观测时间与独立模型身份。"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from gr_data.common.contracts import factor as contracts
from gr_data.common.contracts.meta import SYMBOL_MAP
from gr_data.common.ownership import OwnershipError, OwnershipManager
from gr_data.common.ricequant_risk_quality import validate_daily_risk
from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.db.copy import upsert_rows
from gr_data.db.risk_receipts import (
    commit_receipt,
    probe_receipt,
    record_capture,
    verify_committed_receipt,
)
from gr_data.ingest.base import IngestContext, IngestResult, IngestStopError
from gr_data.ingest.factor_gate import check_factor_counts
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import read_bundles


log = logging.getLogger(__name__)
_CONTRACTS = (
    contracts.MODEL,
    contracts.DEFINITION,
    contracts.MODEL_RUN,
    contracts.MODEL_RUN_COVERAGE,
    contracts.MODEL_RUN_BINDING,
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


def _instrument_ids(
    conn: psycopg.Connection, symbols: list[str], *, allow_alias_duplicates: bool = False
) -> list[int]:
    """按完整交易所代码解析 canonical 或已核实的别名；证据冲突立即拒绝。"""
    canonical: list[tuple[str, str]] = []
    for symbol in symbols:
        match = re.fullmatch(r"([0-9]{6})\.(XSHG|XSHE)", symbol)
        if match is None:
            raise ContractViolationError(f"Unsupported RiceQuant stock symbol: {symbol}")
        code, exchange = match.groups()
        canonical.append((f"{code}.{'SH' if exchange == 'XSHG' else 'SZ'}", exchange))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 'canonical', symbol, symbol, exchange, instrument_id "
            "FROM meta.instruments WHERE asset = 'stock' AND symbol = ANY(%s) "
            "UNION ALL SELECT m.source, m.source_symbol, i.symbol, i.exchange, "
            "i.instrument_id FROM meta.symbol_map m "
            "JOIN meta.instruments i ON i.instrument_id = m.instrument_id "
            "WHERE i.asset = 'stock' AND ((m.source = 'ricequant' "
            "AND m.source_symbol = ANY(%s)) OR (m.source = 'tushare' "
            "AND m.source_symbol = ANY(%s)))",
            ([symbol for symbol, _ in canonical], symbols, [symbol for symbol, _ in canonical]),
        )
        rows = cur.fetchall()
    lookup: dict[tuple[str, str], set[tuple[str, int]]] = {}
    for source, source_symbol, _canonical_symbol, exchange, instrument_id in rows:
        lookup.setdefault((source, source_symbol), set()).add((exchange, instrument_id))
    result = []
    for source_symbol, (canonical_symbol, expected_exchange) in zip(
        symbols, canonical, strict=True
    ):
        matches = set().union(
            lookup.get(("canonical", canonical_symbol), set()),
            lookup.get(("tushare", canonical_symbol), set()),
            lookup.get(("ricequant", source_symbol), set()),
        )
        if not matches:
            raise ContractViolationError(
                f"RiceQuant risk import has unmapped instrument: {source_symbol}"
            )
        if len(matches) != 1 or next(iter(matches))[0] != expected_exchange:
            raise ContractViolationError(f"Conflicting RiceQuant stock aliases: {source_symbol}")
        result.append(next(iter(matches))[1])
    if not allow_alias_duplicates and len(set(result)) != len(result):
        raise ContractViolationError(
            "RiceQuant request codes resolve to duplicate canonical instruments"
        )
    return result


def _dynamic_coverage(
    manifest: dict[str, Any], frames: dict[str, pd.DataFrame], options: RiskOptions
) -> list[dict[str, Any]]:
    """复核动态名单覆盖账本；只允许完整交集进入三张个股数据表。"""
    universe = manifest.get("universe")
    coverage = manifest.get("coverage")
    if (
        manifest.get("purpose") != options.purpose
        or options.purpose not in {"validation", "production"}
        or manifest.get("identity") != options.identity
        or not isinstance(universe, dict)
        or universe.get("day") != manifest["day"]
        or universe.get("policy") != options.universe_policy
        or universe.get("mapping_version") != options.mapping_version
        or universe.get("unresolved")
        or not isinstance(coverage, list)
        or not coverage
        or manifest.get("universe_hash") != semantic_hash(universe)
        or manifest.get("coverage_hash") != semantic_hash(coverage)
    ):
        raise ContractViolationError(
            "RiceQuant dynamic universe identity or coverage hash is invalid"
        )
    candidates = universe.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(coverage):
        raise ContractViolationError("RiceQuant coverage must account for every universe candidate")
    ids: set[int] = set()
    requests: set[str] = set()
    included: list[str] = []
    piece_names = {"exposure", "specific_return", "specific_risk"}
    allowed = {
        "included",
        "provider_not_returned",
        "partial_bundle",
        "sdk_filtered",
        "universe_boundary_unknown",
        "unmapped_symbol",
    }
    for candidate, entry in zip(candidates, coverage, strict=True):
        if not isinstance(candidate, dict) or not isinstance(entry, dict):
            raise ContractViolationError("RiceQuant candidate and coverage must be objects")
        instrument_id = entry.get("instrument_id")
        if type(instrument_id) is not int or instrument_id <= 0 or instrument_id in ids:
            raise ContractViolationError(
                "RiceQuant coverage has invalid or duplicate canonical identity"
            )
        ids.add(instrument_id)
        for key in ("instrument_id", "canonical_symbol", "input_codes", "request_code"):
            if key not in candidate or entry.get(key) != candidate[key]:
                raise ContractViolationError(
                    "RiceQuant coverage changed universe candidate identity"
                )
        codes = entry.get("input_codes")
        request = entry.get("request_code")
        pieces = entry.get("pieces")
        status = entry.get("status")
        if (
            not isinstance(codes, list)
            or not codes
            or any(not isinstance(code, str) or not code.strip() for code in codes)
            or len(codes) != len(set(codes))
            or not isinstance(entry.get("evidence"), dict)
            or set(entry["evidence"])
            - {"canonical", "supplier", "sdk_mapping", "reason", "symbol_interval"}
            or not isinstance(pieces, dict)
            or set(pieces) != piece_names
            or any(type(value) is not bool for value in pieces.values())
            or status not in allowed
        ):
            raise ContractViolationError(
                "RiceQuant coverage contains invalid status, codes or pieces"
            )
        if request is not None:
            if not isinstance(request, str) or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", request):
                raise ContractViolationError("RiceQuant coverage request_code is invalid")
            if request in requests:
                raise ContractViolationError("RiceQuant coverage has duplicate request codes")
            requests.add(request)
        present = sum(pieces.values())
        if status in {"included", "provider_not_returned", "partial_bundle"}:
            expected = (
                "included"
                if present == 3
                else "provider_not_returned"
                if present == 0
                else "partial_bundle"
            )
            if request is None or status != expected:
                raise ContractViolationError(
                    "RiceQuant coverage status does not match returned pieces"
                )
        elif present or request is not None:
            raise ContractViolationError(
                "RiceQuant unrequested candidate must have null request_code and false pieces"
            )
        if status == "included":
            included.append(request)
    counts = dict(Counter(entry["status"] for entry in coverage))
    complete = counts.get("included", 0)
    not_returned = counts.get("provider_not_returned", 0)
    counts.update(
        candidate=len(coverage),
        complete=complete,
        not_returned=not_returned,
        anomalous=len(coverage) - complete - not_returned,
    )
    if manifest.get("coverage_counts") != counts:
        raise ContractViolationError("RiceQuant coverage summary differs from candidate records")
    if not included or list(frames["exposure"].index) != sorted(included):
        raise ContractViolationError(
            "RiceQuant risk data must contain the nonempty complete intersection"
        )
    for name in ("specific_return", "specific_risk"):
        if list(frames[name].columns) != sorted(included):
            raise ContractViolationError("RiceQuant individual pieces have inconsistent coverage")
    for name in ("factor_return", "specific_return", "specific_risk"):
        if list(pd.to_datetime(frames[name].index).date) != [date.fromisoformat(manifest["day"])]:
            raise ContractViolationError("RiceQuant piece trading day differs from coverage")
    return coverage


def _verify_coverage_identities(
    conn: psycopg.Connection, coverage: list[dict[str, Any]]
) -> dict[str, int]:
    """快照不可用当前名单重建；仅复核快照身份仍存在且已登记别名不冲突。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, symbol, exchange FROM meta.instruments "
            "WHERE asset = 'stock' AND instrument_id = ANY(%s) FOR SHARE",
            ([entry["instrument_id"] for entry in coverage],),
        )
        canonical = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    requests: dict[str, int] = {}
    aliases: dict[str, int] = {}
    for entry in coverage:
        instrument_id = entry["instrument_id"]
        symbol = entry["canonical_symbol"]
        if not isinstance(symbol, str):
            raise ContractViolationError("RiceQuant canonical universe symbol is invalid")
        expected_exchange = (
            "XSHG" if symbol.endswith(".SH") else "XSHE" if symbol.endswith(".SZ") else None
        )
        stored = canonical.get(instrument_id)
        if stored is None or stored[1] != expected_exchange or expected_exchange is None:
            raise ContractViolationError(
                "RiceQuant canonical universe identity changed or is unsupported"
            )
        if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol):
            # 已知历史身份不等于可请求代码。保留原码，绝不剥前缀并入六位同号证券。
            # 无法转换的别名也不能免检；本分支只接受与库内 canonical 完全相同的原码。
            if (
                entry["status"] != "unmapped_symbol"
                or entry["request_code"] is not None
                or stored[0] != symbol
                or entry["input_codes"] != [symbol]
            ):
                raise ContractViolationError("Unmapped historical stock identity is unverified")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instrument_id FROM meta.symbol_map "
                    "WHERE source IN ('tushare', 'ricequant') AND source_symbol = %s",
                    (symbol,),
                )
                if any(row[0] != instrument_id for row in cur.fetchall()):
                    raise ContractViolationError("Conflicting historical stock aliases")
            continue
        # 官方换码后旧快照仍可重放，但旧完整代码必须保留在已核实的别名表里。
        for input_code in [symbol, *entry["input_codes"]]:
            if re.fullmatch(r"[0-9]{6}\.(SH|SZ)", input_code):
                input_code = input_code[:6] + (".XSHG" if input_code.endswith(".SH") else ".XSHE")
            if input_code in aliases and aliases[input_code] != instrument_id:
                raise ContractViolationError("RiceQuant input alias belongs to multiple candidates")
            aliases[input_code] = instrument_id
        request = entry["request_code"]
        if request is not None:
            requests[request] = instrument_id
            if request in aliases and aliases[request] != instrument_id:
                raise ContractViolationError("RiceQuant request alias belongs to another candidate")
            aliases[request] = instrument_id
    # 只按已核实的整码别名解析。SDK 可接受某个代码，不足以证明它属于目标证券。
    resolved = _instrument_ids(conn, list(aliases), allow_alias_duplicates=True)
    if resolved != list(aliases.values()):
        raise ContractViolationError(
            "RiceQuant request alias conflicts with canonical universe identity"
        )
    return requests


def _write_coverage(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    day: date,
    observed_at: datetime,
    coverage: list[dict[str, Any]],
    *,
    verify_only: bool = False,
) -> int:
    """同日事务内写全体候选，重放只接受完全相同的覆盖账本。"""
    contract = contracts.MODEL_RUN_COVERAGE
    rows = [
        (
            run_id,
            entry["instrument_id"],
            day,
            entry["input_codes"],
            entry["request_code"],
            entry["status"],
            entry["pieces"],
            entry["evidence"],
            observed_at,
        )
        for entry in coverage
    ]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(contract.columns)} FROM factor.model_run_coverage "
            "WHERE run_id = %s ORDER BY instrument_id",
            (run_id,),
        )
        stored = cur.fetchall()
    if stored or verify_only:
        if [tuple(row) for row in stored] != sorted(rows, key=lambda row: row[1]):
            raise ContractViolationError(f"Immutable RiceQuant coverage conflict: {run_id}")
        return len(rows)
    return upsert_rows(conn, contract, rows)


def _universe_evidence(manifest: dict[str, Any]) -> dict[str, Any]:
    """整日共用的规则与快照指针只记入 run／ETL，不复制到逐股 evidence。"""
    universe = manifest["universe"]
    reference = universe["reference"]
    evidence = {
        "metadata_hash": universe["metadata_hash"],
        "reference_hash": reference.get("snapshot_hash"),
        "sdk_version": reference.get("sdk_version"),
        "boundary_rule": reference.get("boundary_rule"),
        "alias_selection_rule": reference.get("alias_selection_rule"),
    }
    for key in ("symbol_rules_version", "symbol_rules_hash"):
        if key in reference:
            evidence[key] = reference[key]
    return evidence


def _model_run_id(options: RiskOptions, day: str, observation_id: str) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL, f"ricequant-risk:{options.variant_id}:{day}:{observation_id}"
    )


def _request(options: RiskOptions, ctx: IngestContext) -> dict[str, Any]:
    return {
        "model": options.model,
        "industry_mapping": options.industry_mapping,
        "variant_id": options.variant_id,
        "selected_months": list(ctx.months) if ctx.months else None,
        "observation_id": None,
        "model_run_id": None,
        "quality": None,
        "stage": "raw_read",
    }


def _record_etl(
    conn: psycopg.Connection,
    options: RiskOptions,
    request: dict[str, Any],
    started_at: datetime,
    *,
    day: date | None,
    status: str,
    rows_written: int = 0,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> None:
    # 审计使用进程真实时刻，不能用同事务固定不变的 PostgreSQL now()。
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ops.etl_job_run "
            "(job_name, provider, dataset_name, status, rows_written, warning_count, "
            "trading_day, start_date, end_date, request, started_at, finished_at, error) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "ingest.ricequant.rq_risk_model",
                "ricequant",
                "rq_risk_model",
                status,
                rows_written,
                len(warnings or []),
                day,
                day or options.start_date,
                day or options.end_date,
                Jsonb(request),
                started_at,
                datetime.now(timezone.utc),
                error,
            ),
        )


def _record_failure(
    conn: psycopg.Connection,
    options: RiskOptions,
    request: dict[str, Any],
    started_at: datetime,
    day: date | None,
    exc: Exception,
) -> None:
    # 业务事务已退出并回滚；失败审计独立提交，且不能覆盖原始异常。
    quality = getattr(exc, "quality_report", None)
    if quality is not None:
        request["quality"] = quality
    warnings = (request.get("quality") or {}).get("warnings", [])
    try:
        with conn.transaction():
            _record_etl(
                conn,
                options,
                request,
                started_at,
                day=day,
                status="failed",
                warnings=warnings,
                error=type(exc).__name__,
            )
    except Exception as audit_exc:
        log.error(
            "Risk failure audit unavailable provider=ricequant model=%s day=%s error_type=%s",
            options.model,
            day,
            type(audit_exc).__name__,
        )
        exc.add_note(f"Failure audit unavailable: {type(audit_exc).__name__}")


def _audited_bundles(
    conn: psycopg.Connection, ctx: IngestContext, options: RiskOptions
) -> Iterator[tuple[dict[str, Any], dict[str, pd.DataFrame], datetime]]:
    bundles = iter(read_bundles(ctx.paths, options, months=ctx.months))
    while True:
        started_at = datetime.now(timezone.utc)
        try:
            manifest, frames = next(bundles)
        except StopIteration:
            return
        except Exception as exc:
            request = _request(options, ctx)
            # 读取器若能确定失败路径，则使用它提供的日期及观察身份；否则只记请求范围。
            raw_day = getattr(exc, "risk_day", None)
            day = (
                (raw_day if isinstance(raw_day, date) else date.fromisoformat(raw_day))
                if raw_day
                else None
            )
            observation_id = getattr(exc, "risk_observation_id", None)
            if day is not None and observation_id is not None:
                request["observation_id"] = observation_id
                request["model_run_id"] = str(
                    _model_run_id(options, day.isoformat(), observation_id)
                )
            _record_failure(conn, options, request, started_at, day, exc)
            raise
        yield manifest, frames, started_at


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
    run_id = _model_run_id(options, manifest["day"], manifest["observation_id"])
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
    if options.contract_version == "v2":
        units.update(
            purpose=manifest["purpose"],
            trading_day=manifest["day"],
            raw_contract=options.identity["contract"],
            universe_policy=options.universe_policy,
            mapping_version=options.mapping_version,
            universe_hash=manifest["universe_hash"],
            coverage_hash=manifest["coverage_hash"],
            coverage_counts=manifest["coverage_counts"],
            raw_files_hash=semantic_hash(manifest["files"]),
            universe_evidence=_universe_evidence(manifest),
        )
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
        f"ricequant-risk-{options.contract_version}",
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


class PublicationGateError(IngestStopError):
    """整包与降级收据已提交，但发布资格不满足；停止后续日期供人工检查。"""


def _publication_quality(manifest: dict[str, Any]) -> dict[str, Any]:
    counts = manifest["coverage_counts"]
    reasons = []
    if counts["complete"] * 1000 < counts["candidate"] * 999:
        reasons.append("complete_coverage_below_99_9_percent")
    for status in ("universe_boundary_unknown", "unmapped_symbol"):
        if counts.get(status, 0):
            reasons.append(status)
    return {"publication_eligible": not reasons, "publication_reasons": reasons}


def run_risk_ingest(
    conn: psycopg.Connection, ctx: IngestContext, options: RiskOptions
) -> IngestResult:
    """逐日读取经过校验的五件套并原子写库。

    Args:
        conn: 空闲 PostgreSQL 连接；每个观测日独立提交，失败日完整回滚。
        ctx: raw 路径和可选月份过滤；禁止通过 force_ownership 隐式切换源。
        options: 已确认模型、单位和标的范围的配置。

    Returns:
        五张业务数据表和动态覆盖表的累计写入行数，不含模型元数据、映射和 ETL 流水。

    Raises:
        OwnershipError: 风险表属于其他供应商或请求隐式强制切换。
        ContractViolationError: 映射缺失、数值溢出或不可变观测不一致。
        IngestGateError: 明细行的 factor_count 与所属 model_run 不一致。
        ValueError: 连接已有事务，避免提交或回滚调用者的其他操作。

    峰值内存为一个交易日的股票数乘因子数；风险数据 available_at 始终采用
    raw 实际观测时间，不将历史抓取伪装为当时已知的数据。
    """
    if options.purpose == "production" and options.contract_version != "v2":
        raise ContractViolationError("RiceQuant production requires dynamic universe receipts")
    if ctx.force_ownership:
        raise OwnershipError("RiceQuant risk import requires explicit gr-data own release/set")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("RiceQuant risk import requires an idle connection")
    total = 0
    committed_days: list[date] = []
    warnings: list[str] = []
    for manifest, frames, started_at in _audited_bundles(conn, ctx, options):
        day = None
        request = _request(options, ctx)
        request.update(
            {
                "observation_id": manifest["observation_id"],
                "model_run_id": str(
                    _model_run_id(options, manifest["day"], manifest["observation_id"])
                ),
                "stage": "validate_manifest",
                "quota_observation": manifest.get("quota_observation"),
            }
        )
        transaction_body_complete = False
        try:
            day = date.fromisoformat(manifest["day"])
            observed_at = datetime.fromisoformat(manifest["observed_at"])
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ContractViolationError("RiceQuant observed_at must be timezone-aware")
            if manifest["variant_id"] != options.variant_id:
                raise ContractViolationError(
                    "RiceQuant risk raw variant does not match configuration"
                )
            coverage = (
                _dynamic_coverage(manifest, frames, options)
                if options.contract_version == "v2"
                else None
            )
            if coverage is not None:
                request.update(
                    purpose=manifest["purpose"],
                    raw_contract=options.identity["contract"],
                    universe_hash=manifest["universe_hash"],
                    coverage_hash=manifest["coverage_hash"],
                    coverage_counts=manifest["coverage_counts"],
                    raw_files_hash=semantic_hash(manifest["files"]),
                    universe_evidence=_universe_evidence(manifest),
                    manifest_ref=(
                        f"ricequant/rq_risk_model/{options.contract_version}/{options.variant_id}/"
                        f"{manifest['day']}/{manifest['observation_id']}/manifest.json"
                    ),
                )
            if coverage is not None:
                request["stage"] = "capture_registration"
                record_capture(conn, options, manifest)
            order = list(frames["exposure"].columns)
            if not order or len(order) > 32767 or any(len(name) > 32 for name in order):
                raise ContractViolationError("RiceQuant factor definitions exceed storage contract")
            request["stage"] = "quality"
            values = _normalize(frames, options)
            quality = validate_daily_risk(
                values["exposure"], values["covariance"], values["specific_risk"].reshape(-1)
            )
            if coverage is not None:
                quality.update(_publication_quality(manifest))
            request["quality"] = quality
            day_warnings = list(quality["warnings"])
            if coverage is not None and manifest["coverage_counts"]["complete"] < len(coverage):
                request["coverage_degraded"] = True
                day_warnings.append(
                    "Degraded coverage: "
                    f"{manifest['coverage_counts']['complete']}/{len(coverage)} candidates complete"
                )
            request["stage"] = "write"
            symbols = list(frames["exposure"].index)
            with conn.transaction():
                # 与显式归属修改互斥，避免先检查归属、后写入期间发生切换。
                with conn.cursor() as cur:
                    cur.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
                    cur.execute("LOCK TABLE meta.symbol_map IN SHARE ROW EXCLUSIVE MODE")
                owner = OwnershipManager(conn)
                for contract in _CONTRACTS:
                    # 旧固定名单不产生覆盖表，也不要求迁移 048 或登记其归属。
                    if (
                        contract in {contracts.MODEL_RUN_COVERAGE, contracts.MODEL_RUN_BINDING}
                        and coverage is None
                    ):
                        continue
                    owner.claim(contract.qualified, "ricequant", channel=ctx.channel, force=False)
                if coverage is None:
                    ids = _instrument_ids(conn, symbols)
                else:
                    resolved = _verify_coverage_identities(conn, coverage)
                    ids = [resolved[symbol] for symbol in symbols]
                receipt = probe_receipt(conn, options, manifest) if coverage is not None else None
                request["replay"] = receipt is not None
                if receipt is None:
                    if coverage is not None:
                        candidate_run = _model_run_id(
                            options, manifest["day"], manifest["observation_id"]
                        )
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT run_id,receipt_id,variant_id,observation_id,trading_day "
                                "FROM factor.model_run_binding WHERE run_id=%s",
                                (candidate_run,),
                            )
                            if cur.fetchone() is not None:
                                raise ContractViolationError(
                                    "RiceQuant observation already bound to "
                                    "another importer version; "
                                    "reprocessing requires a separately approved identity"
                                )
                    owner.claim(SYMBOL_MAP.qualified, "ricequant", channel=ctx.channel, force=False)
                    upsert_rows(
                        conn,
                        SYMBOL_MAP,
                        list(zip(ids, ["ricequant"] * len(ids), symbols, strict=True)),
                    )
                    run_id = _run_metadata(conn, options, manifest, order, observed_at)
                    count = len(order)
                    rows = {
                        contracts.EXPOSURE: [
                            (
                                run_id,
                                instrument_id,
                                day,
                                values["exposure"][i].tolist(),
                                count,
                                observed_at,
                            )
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
                    for contract in (
                        contracts.EXPOSURE,
                        contracts.COVARIANCE,
                        contracts.FACTOR_RETURN,
                    ):
                        run_col = contract.columns.index("run_id")
                        count_col = contract.columns.index("factor_count")
                        check_factor_counts(
                            conn,
                            contract.qualified,
                            ((row[run_col], row[count_col]) for row in rows[contract]),
                        )
                    written = sum(
                        upsert_rows(conn, contract, data) for contract, data in rows.items()
                    )
                    if coverage is not None:
                        written += _write_coverage(conn, run_id, day, observed_at, coverage)
                    if coverage is not None:
                        receipt = commit_receipt(conn, options, manifest, run_id, written, quality)
                else:
                    run_id = _model_run_id(options, manifest["day"], manifest["observation_id"])
                    verify_committed_receipt(conn, options, manifest, run_id, receipt)
                    _write_coverage(conn, run_id, day, observed_at, coverage, verify_only=True)
                    written = 0
                if receipt is not None:
                    request["receipt_id"] = str(receipt["receipt_id"])
                _record_etl(
                    conn,
                    options,
                    request,
                    started_at,
                    day=day,
                    status="success",
                    rows_written=written,
                    warnings=day_warnings,
                )
                transaction_body_complete = True
        except Exception as exc:
            # 40003 明确表示完成未知，不能按整个 40 类推断回滚。
            known_database_rejection = (
                isinstance(exc, psycopg.Error)
                and exc.sqlstate
                and (exc.sqlstate.startswith("23") or exc.sqlstate in {"40001", "40P01"})
            )
            if transaction_body_complete and coverage is not None and not known_database_rejection:
                # 只有事务体全部完成、退出事务时才可能丢失 COMMIT 响应。
                # 不对确定性 SQL/质量失败启动此分支，也不尝试替换连接。
                confirmed = False
                if conn.info.transaction_status == TransactionStatus.IDLE:
                    try:
                        with conn.transaction():
                            recovered = probe_receipt(conn, options, manifest)
                            if recovered is not None:
                                verify_committed_receipt(conn, options, manifest, run_id, recovered)
                                confirmed = True
                    except Exception:
                        confirmed = False
                outcome = "commit_confirmed" if confirmed else "commit_outcome_unknown"
                raise IngestStopError(
                    f"RiceQuant {outcome}: day={day}",
                    result=IngestResult(
                        "rq_risk_model",
                        "factor.risk_bundle",
                        total + written if confirmed else total,
                        list(warnings),
                    ),
                    committed_days=tuple([*committed_days, day] if confirmed else committed_days),
                    stopped_day=day,
                    requested_end=options.end_date,
                    selected_months=ctx.months,
                    receipt_id=str(receipt["receipt_id"]),
                    reasons=(outcome,),
                    outcome=outcome,
                ) from exc
            _record_failure(conn, options, request, started_at, day, exc)
            raise
        committed_days.append(day)
        if options.purpose == "production" and not quality.get("publication_eligible", False):
            raise PublicationGateError(
                f"RiceQuant bundle committed but publication ineligible: day={day} "
                f"reasons={quality.get('publication_reasons', [])}",
                result=IngestResult(
                    "rq_risk_model",
                    "factor.risk_bundle",
                    total + written,
                    [*warnings, *day_warnings],
                ),
                committed_days=tuple(committed_days),
                stopped_day=day,
                requested_end=options.end_date,
                selected_months=ctx.months,
                receipt_id=str(receipt["receipt_id"]),
                reasons=tuple(quality.get("publication_reasons", [])),
            )
        # 完整记录的覆盖降级是允许的业务状态，日志与 ETL 留痕即可；
        # IngestResult.warnings 仍只包含需要人工复核、CLI 返回 3 的数值告警。
        warnings.extend(f"{day}: {warning}" for warning in quality["warnings"])
        for warning in day_warnings:
            log.warning("Risk quality warning provider=ricequant day=%s detail=%s", day, warning)
        total += written
        log.info(
            "Risk bundle imported provider=ricequant day=%s run_id=%s rows=%d", day, run_id, written
        )
    return IngestResult(
        dataset="rq_risk_model", target="factor.*", rows_written=total, warnings=warnings
    )
