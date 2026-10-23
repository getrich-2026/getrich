"""动态历史名单的不可变原始响应、覆盖归因及逐日发布。"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import numpy as np
import pandas as pd

from gr_data.common.retry import chunk_list, sleep_s
from gr_data.common.ricequant_risk_quality import validate_covariance
from gr_data.common.ricequant_specs import ContractViolationError, RawIntegrityError, semantic_hash
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.fetchers.supplements import _check_quota
from gr_data.raw.ricequant.risk_shapes import (
    PIECES,
    STYLE_FACTORS,
    _dated,
    _frame,
    decode_piece,
    validate_bundle,
)
from gr_data.raw.ricequant.store import file_hash


log = logging.getLogger(__name__)
T = TypeVar("T")
INDIVIDUAL = ("exposure", "specific_return", "specific_risk")


def validate_universe(universe: dict, options: RiskOptions, day: date) -> list[str]:
    """核对冻结身份与请求的一一映射；未知上市边界不伪装为供应商缺失。"""
    if (
        not isinstance(universe, dict)
        or universe.get("day") != str(day)
        or universe.get("policy") != options.universe_policy
        or universe.get("mapping_version") != options.mapping_version
        or not isinstance(universe.get("metadata_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", universe["metadata_hash"])
        or not isinstance(universe.get("reference"), dict)
        or not isinstance(universe.get("unresolved"), list)
        or not isinstance(universe.get("candidates"), list)
        or not universe["candidates"]
    ):
        raise RawIntegrityError("动态风险名单身份或结构非法")
    reference = universe["reference"]
    if (
        "metadata" not in reference
        or "supplier_snapshot" not in reference
        or semantic_hash(reference["metadata"]) != universe["metadata_hash"]
        or semantic_hash(reference["supplier_snapshot"]) != reference.get("snapshot_hash")
    ):
        raise RawIntegrityError("动态风险名单参考快照哈希不一致")
    if options.symbol_rules_hash is not None and (
        reference.get("symbol_rules_hash") != options.symbol_rules_hash
        or reference.get("symbol_rules_version") != options.symbol_rules_version
        or not isinstance(reference.get("symbol_rules"), dict)
        or semantic_hash(reference["symbol_rules"]) != options.symbol_rules_hash
    ):
        raise RawIntegrityError("动态风险换码区间规则版本或哈希不一致")
    rebuilt = build_universe_provider(
        reference["metadata"],
        reference["supplier_snapshot"],
        universe_policy=options.universe_policy,
        mapping_version=options.mapping_version,
        symbol_rules=reference.get("symbol_rules"),
    )(str(day))
    if rebuilt != universe:
        raise RawIntegrityError("动态风险名单不能由冻结参考快照重现")
    seen_ids, seen_codes = set(), set()
    for row in universe["candidates"]:
        if not isinstance(row, dict):
            raise RawIntegrityError("动态风险名单候选格式非法")
        instrument_id = row.get("instrument_id")
        code, status = row.get("request_code"), row.get("status")
        if (
            type(instrument_id) is not int
            or instrument_id <= 0
            or instrument_id in seen_ids
            or not isinstance(row.get("canonical_symbol"), str)
            or not (
                re.fullmatch(r"[0-9]{6}\.(SH|SZ)", row["canonical_symbol"])
                or (
                    status == "unmapped_symbol" and row["canonical_symbol"].endswith((".SH", ".SZ"))
                )
            )
            or not isinstance(row.get("input_codes"), list)
            or not isinstance(row.get("evidence"), dict)
            or status not in {None, "unmapped_symbol", "sdk_filtered", "universe_boundary_unknown"}
            or (status is None and code is None)
            or (status is not None and code is not None)
        ):
            raise RawIntegrityError("动态风险名单身份重复或候选状态非法")
        seen_ids.add(instrument_id)
        if code is not None:
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", code):
                raise RawIntegrityError("动态风险请求代码非法")
            if code in seen_codes:
                raise RawIntegrityError("动态风险请求代码对应多个身份")
            seen_codes.add(code)
    if universe["unresolved"]:
        raise RawIntegrityError("动态风险名单存在无法归属的源代码，禁止发布")
    return sorted(seen_codes)


def _decode_partial(
    piece: str, response: object, day: date, codes: tuple[str, ...], factors: list[str]
) -> pd.DataFrame:
    """空个股响应表示成功但未覆盖；数值或轴异常仍拒绝整日。"""
    if response is None:
        return (
            pd.DataFrame(index=pd.Index([], name="order_book_id"), columns=factors, dtype=float)
            if piece == "exposure"
            else pd.DataFrame(index=pd.Index([day], name="date"), dtype=float)
        )
    if not isinstance(response, pd.DataFrame):
        raise ContractViolationError("动态风险接口返回类型非法")
    if not response.index.is_unique or not response.columns.is_unique:
        raise ContractViolationError("动态风险响应含重复轴标签")
    if response.empty:
        if piece == "exposure":
            if len(response.index) or (
                len(response.columns) and set(response.columns) != set(factors)
            ):
                raise ContractViolationError("空风险暴露存在异常股票或因子轴")
        elif len(response.columns):
            raise ContractViolationError("空特异响应缺少请求日期")
        elif len(response.index):
            _dated(response, day)
        return _decode_partial(piece, None, day, codes, factors)
    frame = _frame(response)
    if piece == "exposure":
        if (
            not isinstance(frame.index, pd.MultiIndex)
            or frame.index.nlevels != 2
            or set(frame.index.names) != {"date", "order_book_id"}
            or not (pd.to_datetime(frame.index.get_level_values("date")).date == day).all()
        ):
            raise ContractViolationError("风险暴露日期或股票轴非法")
        frame.index = frame.index.get_level_values("order_book_id")
        if not frame.index.is_unique or not set(frame.index) <= set(codes):
            raise ContractViolationError("风险暴露包含未请求代码或重复身份")
        if set(frame.columns) != set(factors):
            raise ContractViolationError("风险暴露因子集合不一致")
        industry_columns = [
            factor for factor in factors if all("\u4e00" <= char <= "\u9fff" for char in factor)
        ]
        industry = frame.loc[:, industry_columns].to_numpy()
        if (
            "comovement" not in frame
            or not (frame["comovement"] == 1).all()
            or not industry_columns
            or not np.isin(industry, [0.0, 1.0]).all()
            or not (industry.sum(axis=1) == 1).all()
        ):
            raise ContractViolationError("风险暴露必须有单位市场载荷和唯一行业归属")
        return frame.loc[:, factors]
    frame = _dated(frame, day)
    if not set(frame.columns) <= set(codes):
        raise ContractViolationError("特异响应包含未请求代码")
    if piece == "specific_risk" and (frame.to_numpy() < 0).any():
        raise ContractViolationError("特异波动率不得为负")
    return frame


def assess_coverage(
    frames: dict[str, pd.DataFrame], universe: dict, options: RiskOptions, day: date
) -> tuple[list[dict], dict[str, int], dict[str, pd.DataFrame]]:
    """从原始返回集合重算覆盖；仅完整交集进入风险数值表，原响应保持不变。"""
    codes = validate_universe(universe, options, day)
    factors = sorted(frames["factor_return"].columns)
    expected = STYLE_FACTORS[options.model] | {"comovement"}
    if not expected < set(factors) or any(
        not all("\u4e00" <= ch <= "\u9fff" for ch in f) for f in set(factors) - expected
    ):
        raise ContractViolationError("风险模型因子集合非法")
    exposure = frames["exposure"]
    if set(exposure.columns) != set(factors):
        raise ContractViolationError("风险暴露与全局因子不一致")
    # 即使股票最终缺少其他接口，也不能掩盖已返回的非法暴露或负方差。
    if len(exposure):
        _frame(exposure)
        industry = exposure.loc[:, sorted(set(factors) - expected)].to_numpy()
        if (
            not (exposure["comovement"] == 1).all()
            or not np.isin(industry, [0.0, 1.0]).all()
            or not (industry.sum(axis=1) == 1).all()
        ):
            raise ContractViolationError("风险暴露必须有单位市场载荷和唯一行业归属")
    for piece in ("specific_return", "specific_risk"):
        if len(frames[piece].columns):
            _dated(_frame(frames[piece]), day)
            if piece == "specific_risk" and (frames[piece].to_numpy() < 0).any():
                raise ContractViolationError("特异波动率不得为负")
    returned = {
        "exposure": set(exposure.index),
        "specific_return": set(frames["specific_return"].columns),
        "specific_risk": set(frames["specific_risk"].columns),
    }
    if any(not values <= set(codes) for values in returned.values()):
        raise ContractViolationError("风险响应出现未请求代码")
    coverage = []
    for candidate in universe["candidates"]:
        row = dict(candidate)
        pieces = {piece: row["request_code"] in returned[piece] for piece in INDIVIDUAL}
        row["pieces"] = pieces
        if row["status"] is None:
            count = sum(pieces.values())
            row["status"] = (
                "included"
                if count == 3
                else "provider_not_returned"
                if count == 0
                else "partial_bundle"
            )
        coverage.append(row)
    included = sorted(row["request_code"] for row in coverage if row["status"] == "included")
    if not included:
        raise ContractViolationError("动态风险日没有完整股票，无法执行 R1，禁止发布")
    complete = dict(frames)
    complete["exposure"] = exposure.loc[included]
    for piece in ("specific_return", "specific_risk"):
        complete[piece] = frames[piece].loc[:, included]
    complete = validate_bundle(complete, replace(options, order_book_ids=tuple(included)), day)
    counts = dict(Counter(row["status"] for row in coverage))
    counts["candidate"] = len(coverage)
    counts["complete"] = len(included)
    counts["not_returned"] = counts.get("provider_not_returned", 0)
    counts["anomalous"] = len(coverage) - len(included) - counts["not_returned"]
    return coverage, counts, complete


def _write_frame(path: Path, frame: pd.DataFrame) -> str:
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        frame.to_parquet(temporary, compression="zstd", index=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return file_hash(path)


def _read_frame(folder: Path, name: str, checksum: str) -> pd.DataFrame:
    path = folder / name
    if not path.resolve().is_relative_to(folder.resolve()) or file_hash(path) != checksum:
        raise RawIntegrityError("动态风险原始响应路径或哈希不一致")
    return pd.read_parquet(path)


def _reconstruct(
    receipts: list[dict], responses: list[object], options: RiskOptions, day: date, codes: list[str]
) -> dict[str, pd.DataFrame]:
    """逐请求验证成功凭据，不能把没有调用的代码登记为供应商未覆盖。"""
    expected = [(piece, []) for piece in ("factor_return", "covariance")]
    if len(receipts) < 2 or (len(receipts) - 2) % 3 or len(responses) != len(receipts):
        raise RawIntegrityError("动态风险请求凭据数量不完整")
    requested = []
    for index in range(2, len(receipts), 3):
        batch = receipts[index].get("codes")
        if (
            not isinstance(batch, list)
            or not batch
            or any(not isinstance(code, str) for code in batch)
        ):
            raise RawIntegrityError("动态风险请求凭据股票列表非法")
        requested.extend(batch)
        expected.extend((piece, batch) for piece in INDIVIDUAL)
    if sorted(requested) != codes:
        raise RawIntegrityError("动态风险请求未完整覆盖冻结名单或重复请求")
    frames, parts = {}, {piece: [] for piece in INDIVIDUAL}
    for receipt, response, (piece, batch) in zip(receipts, responses, expected, strict=True):
        if (
            receipt.get("piece") != piece
            or receipt.get("codes") != batch
            or receipt.get("success") is not True
        ):
            raise RawIntegrityError("动态风险请求凭据身份不一致")
        if piece in ("factor_return", "covariance"):
            frames[piece] = decode_piece(piece, response, day, ())
        else:
            parts[piece].append(
                _decode_partial(
                    piece, response, day, tuple(batch), sorted(frames["factor_return"].columns)
                )
            )
    for piece in INDIVIDUAL:
        if not parts[piece]:
            frames[piece] = _decode_partial(
                piece, None, day, (), sorted(frames["factor_return"].columns)
            )
        else:
            frames[piece] = pd.concat(parts[piece], axis=0 if piece == "exposure" else 1)
    return frames


def load_dynamic(path: Path, options: RiskOptions) -> tuple[dict, dict[str, pd.DataFrame]]:
    """逐文件验哈希，并从成功响应凭据重算名单、覆盖和完整交集。"""
    try:
        if not path.resolve().is_relative_to(path.parents[2].resolve()):
            raise RawIntegrityError("动态风险观察路径逃逸")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        day = date.fromisoformat(manifest["day"])
        observed = datetime.fromisoformat(manifest["observed_at"])
        if (
            manifest["identity"] != options.identity
            or manifest["variant_id"] != options.variant_id
            or manifest["purpose"] != options.purpose
            or observed.tzinfo is None
            or path.parent.name != manifest["observation_id"]
            or not re.fullmatch(r"[0-9a-f]{32}", manifest["observation_id"])
            or path.parent.parent.name != str(day)
            or set(manifest["files"]) != set(PIECES)
            or manifest["universe_hash"] != semantic_hash(manifest["universe"])
            or manifest["coverage_hash"] != semantic_hash(manifest["coverage"])
        ):
            raise RawIntegrityError("动态风险观察身份或哈希不一致")
        codes = validate_universe(manifest["universe"], options, day)
        responses = []
        for index, receipt in enumerate(manifest["requests"]):
            if receipt["response_kind"] == "none":
                if receipt.get("file") is not None or receipt.get("sha256") is not None:
                    raise RawIntegrityError("空响应不得引用文件")
                responses.append(None)
            elif receipt["response_kind"] == "dataframe":
                if receipt["file"] != f"response-{index:05d}.parquet":
                    raise RawIntegrityError("动态风险响应文件名非法")
                responses.append(_read_frame(path.parent, receipt["file"], receipt["sha256"]))
            else:
                raise RawIntegrityError("动态风险响应类型非法")
        frames = _reconstruct(manifest["requests"], responses, options, day, codes)
        for piece in PIECES:
            saved = _read_frame(path.parent, piece + ".parquet", manifest["files"][piece])
            if not saved.equals(frames[piece]):
                raise RawIntegrityError("风险汇总响应与原始请求凭据不一致")
        coverage, counts, complete = assess_coverage(frames, manifest["universe"], options, day)
        if coverage != manifest["coverage"] or counts != manifest["coverage_counts"]:
            raise RawIntegrityError("动态风险覆盖记录与原始响应不一致")
        return manifest, complete
    except (KeyError, ValueError, TypeError, OSError, IndexError) as exc:
        raise RawIntegrityError("动态风险观察损坏、身份不匹配或文件缺失") from exc


def run_dynamic_locked(
    client: RqdatacClient,
    ctx: RawContext,
    options: RiskOptions,
    shared: RicequantImportOptions,
    root: Path,
    mode: str,
    universe_provider: Callable[[str], dict],
    capture_callback: Callable[[dict], None] | None = None,
) -> int:
    """固定每日名单，原响应成功存证后计算覆盖；失败证据不进入发布路径。"""
    from gr_data.raw.ricequant.riskmodel import _json, _quota_snapshot

    def call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        for attempt in range(ctx.max_retries):
            _check_quota(client, shared.quota_reserve_fraction)
            sleep_s(ctx.sleep_between_requests)
            try:
                return fn(*args, **kwargs)
            except ConnectionError:
                if attempt + 1 == ctx.max_retries:
                    raise
                sleep_s(ctx.backoff_base * 2**attempt)
        raise AssertionError("max_retries must be positive")

    scope = semantic_hash([str(options.start_date), str(options.end_date), mode])
    journal = root / ("round-" + scope + ".json")
    if journal.exists():
        plan = json.loads(journal.read_text(encoding="utf-8"))
    else:
        # 完成轮次已移除 plan；只重新确认交易日历，init 仍逐日复用已验证观察。
        days = sorted(
            {
                pd.Timestamp(d).date()
                for d in call(
                    client.get_trading_dates, str(options.start_date), str(options.end_date)
                )
            }
        )
        plan = {"days": [str(d) for d in days], "completed": {}, "universes": {}}
        _json(journal, plan)
    written = 0
    for value in plan["days"]:
        day = date.fromisoformat(value)
        if not options.start_date <= day <= options.end_date:
            raise RawIntegrityError("风险恢复计划日期越界")
        if value in plan["completed"]:
            observation = plan["completed"][value]
            if not isinstance(observation, str) or not re.fullmatch(r"[0-9a-f]{32}", observation):
                raise RawIntegrityError("风险恢复观察标识非法")
            manifest, _ = load_dynamic(root / value / observation / "manifest.json", options)
            if capture_callback is not None:
                capture_callback(manifest)
            continue
        previous = list((root / value).glob("*/manifest.json"))
        if mode == "init" and previous:
            for path in previous:
                manifest, _ = load_dynamic(path, options)
                if capture_callback is not None:
                    capture_callback(manifest)
            continue
        observation = uuid4().hex
        pending = root / "_pending" / value / observation
        if not pending.resolve().is_relative_to(root.resolve()):
            raise RawIntegrityError("动态风险暂存目录逃逸")
        pending.mkdir(parents=True)
        receipt: dict = {
            "day": value,
            "observation_id": observation,
            "variant_id": options.variant_id,
            "identity": options.identity,
            "purpose": options.purpose,
            "requests": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        try:
            if value not in plan["universes"]:
                plan["universes"][value] = universe_provider(value)
                _json(journal, plan)
            universe = plan["universes"][value]
            receipt["universe"] = universe
            receipt["universe_hash"] = semantic_hash(universe)
            _json(pending / "receipt.json", receipt)
            codes = validate_universe(universe, options, day)
            receipt["quota_observation"] = {"before": _quota_snapshot(client)}
            requests = [(piece, []) for piece in ("factor_return", "covariance")]
            requests.extend(
                (piece, list(batch))
                for batch in chunk_list(codes, options.batch_size)
                for piece in INDIVIDUAL
            )
            responses = []
            for index, (piece, batch) in enumerate(requests):
                response = call(
                    client.risk_piece,
                    piece,
                    value,
                    batch,
                    model=options.model,
                    industry_mapping=options.industry_mapping,
                )
                record: dict = {"piece": piece, "codes": batch, "success": True}
                if isinstance(response, pd.DataFrame):
                    record["response_kind"] = "dataframe"
                    record["file"] = f"response-{index:05d}.parquet"
                    if not response.columns.is_unique:
                        # Parquet 不能存重复列名：失败证据保留位置列和原列标签，不发布。
                        diagnostic = response.copy()
                        record["original_columns"] = [str(column) for column in response.columns]
                        diagnostic.columns = [f"column_{i}" for i in range(len(response.columns))]
                        record["sha256"] = _write_frame(pending / record["file"], diagnostic)
                        record["response_kind"] = "invalid_duplicate_columns"
                        receipt["requests"].append(record)
                        raise ContractViolationError("动态风险响应含重复列标签")
                    record["sha256"] = _write_frame(pending / record["file"], response)
                elif response is None:
                    record["response_kind"] = "none"
                else:
                    raise ContractViolationError("动态风险响应不是 DataFrame 或 None")
                receipt["requests"].append(record)
                responses.append(response)
                _json(pending / "receipt.json", receipt)
                # 每次请求后校验，数值异常立即停止，不继续消耗配额。
                if piece in ("factor_return", "covariance"):
                    decoded = decode_piece(piece, response, day, ())
                    if piece == "covariance":
                        if set(decoded.columns) != set(responses[0].columns):
                            raise ContractViolationError("协方差与因子收益的因子集合不一致")
                        validate_covariance(decoded.loc[decoded.columns].to_numpy())
                else:
                    _decode_partial(
                        piece, response, day, tuple(batch), sorted(responses[0].columns)
                    )
            frames = _reconstruct(receipt["requests"], responses, options, day, codes)
            coverage, counts, _ = assess_coverage(frames, universe, options, day)
            receipt.update(
                coverage=coverage, coverage_counts=counts, coverage_hash=semantic_hash(coverage)
            )
            receipt["quota_observation"]["after"] = _quota_snapshot(client)
            receipt["observed_at"] = datetime.now(timezone.utc).isoformat()
            for piece, frame in frames.items():
                receipt["files"][piece] = _write_frame(pending / (piece + ".parquet"), frame)
            _json(pending / "manifest.json", receipt)
            destination = root / value / observation
            if not destination.resolve().is_relative_to(root.resolve()):
                raise RawIntegrityError("动态风险发布目录逃逸")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(pending, destination)
            plan["completed"][value] = observation
            _json(journal, plan)
            written += sum(len(frame) for frame in frames.values())
            log.info(
                "Ricequant dynamic risk published day=%s observation=%s candidates=%d complete=%d",
                value,
                observation,
                counts["candidate"],
                counts["complete"],
            )
        except Exception as exc:
            if pending.exists():
                receipt["failure"] = {
                    "error_type": type(exc).__name__,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                }
                _json(pending / "receipt.json", receipt)
                failed = root / "_failed" / value / observation
                if not failed.resolve().is_relative_to(root.resolve()):
                    raise RawIntegrityError("动态风险失败目录逃逸") from exc
                failed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(pending, failed)
            raise
        # 观察已经原子发布且恢复计划已落盘。数据库失败不改变 raw 完成状态。
        if capture_callback is not None:
            capture_callback(receipt)
    journal.unlink()
    return written
