"""米筐日度风险五件套：不可变观察、完整发布、按日恢复。"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from collections.abc import Callable, Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import pandas as pd

from gr_data.common.paths import RawPaths
from gr_data.common.retry import chunk_list, sleep_s
from gr_data.common.ricequant_specs import RawIntegrityError, semantic_hash
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.fetchers.supplements import _check_quota
from gr_data.raw.ricequant.risk_shapes import PIECES, decode_piece, validate_bundle
from gr_data.raw.ricequant.store import file_hash


log = logging.getLogger(__name__)
T = TypeVar("T")


def _json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(path: Path, options: RiskOptions) -> tuple[dict, dict[str, pd.DataFrame]]:
    try:
        if not path.resolve().is_relative_to(path.parents[2].resolve()):
            raise ValueError("path escapes variant")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        day = date.fromisoformat(manifest["day"])
        observed = datetime.fromisoformat(manifest["observed_at"])
        if (
            observed.tzinfo is None
            or manifest["identity"] != options.identity
            or manifest["variant_id"] != options.variant_id
        ):
            raise ValueError("identity")
        if (
            path.parent.name != manifest["observation_id"]
            or path.parent.parent.name != day.isoformat()
        ):
            raise ValueError("path")
        if set(manifest["files"]) != set(PIECES):
            raise ValueError("files")
        frames = {}
        for piece in PIECES:
            file = path.parent / (piece + ".parquet")
            if (
                not file.resolve().is_relative_to(path.parent.resolve())
                or file_hash(file) != manifest["files"][piece]
            ):
                raise ValueError("checksum")
            frames[piece] = pd.read_parquet(file)
        return manifest, validate_bundle(frames, options, day)
    except (KeyError, ValueError, TypeError, OSError) as exc:
        raise RawIntegrityError("米筐风险观察损坏、身份不匹配或文件缺失") from exc


def read_bundles(
    paths: RawPaths, options: RiskOptions, months: tuple[str, ...] | None = None
) -> Iterator[tuple[dict, dict[str, pd.DataFrame]]]:
    """只读取完整发布的观察；逐日有界内存，不以最新快照覆盖历史可用时间。"""
    root = paths.ricequant_variant("rq_risk_model", "v1", options.variant_id)
    found = False
    for path in sorted(root.glob("????-??-??/*/manifest.json")):
        day = date.fromisoformat(path.parent.parent.name)
        if not options.start_date <= day <= options.end_date or (
            months and day.strftime("%Y-%m") not in months
        ):
            continue
        found = True
        yield _load(path, options)
    if not found:
        raise RawIntegrityError("所选范围没有完整的米筐风险五件套，请先执行 raw")


def run_risk_raw(
    client: RqdatacClient,
    ctx: RawContext,
    options: RiskOptions,
    shared: RicequantImportOptions,
    *,
    mode: str,
) -> int:
    """交易日历来自 SDK；一天五份全部校验后发布，失败保留已完成日等待续跑。

    init 跳过已完整观察的日期；update 每轮重抓显式日期范围，失败后续跑同一轮。
    内存上界为显式股票范围的一日矩阵（最多 10000 只），SDK 分批至 batch_size。
    """
    if mode not in {"init", "update"}:
        raise ValueError("未知采集模式")
    root = ctx.paths.ricequant_variant("rq_risk_model", "v1", options.variant_id)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _run_locked(client, ctx, options, shared, root, mode)


def _run_locked(
    client: RqdatacClient,
    ctx: RawContext,
    options: RiskOptions,
    shared: RicequantImportOptions,
    root: Path,
    mode: str,
) -> int:
    def call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        for attempt in range(ctx.max_retries):
            _check_quota(client, shared.quota_reserve_fraction)
            sleep_s(ctx.sleep_between_requests)
            try:
                return fn(*args, **kwargs)
            except ConnectionError:
                if attempt + 1 == ctx.max_retries:
                    raise
                log.warning("Ricequant risk request retry attempt=%d", attempt + 1)
                sleep_s(ctx.backoff_base * 2**attempt)
        raise AssertionError("max_retries must be positive")

    scope = semantic_hash([str(options.start_date), str(options.end_date), mode])
    journal = root / ("round-" + scope + ".json")
    if journal.exists():
        plan = json.loads(journal.read_text(encoding="utf-8"))
    else:
        dates = call(client.get_trading_dates, str(options.start_date), str(options.end_date))
        days = sorted({pd.Timestamp(d).date() for d in dates})
        if any(not options.start_date <= d <= options.end_date for d in days):
            raise RawIntegrityError("SDK 交易日历越出请求范围")
        plan = {"days": [str(d) for d in days], "completed": {}}
        _json(journal, plan)
    written = 0
    for value in plan["days"]:
        day = date.fromisoformat(value)
        if not options.start_date <= day <= options.end_date:
            raise RawIntegrityError("风险恢复计划日期越界")
        if value in plan["completed"]:
            observation = plan["completed"][value]
            if (
                not isinstance(observation, str)
                or len(observation) != 32
                or any(c not in "0123456789abcdef" for c in observation)
            ):
                raise RawIntegrityError("风险恢复观察标识非法")
            _load(root / value / observation / "manifest.json", options)
            continue
        previous = list((root / value).glob("*/manifest.json"))
        if mode == "init" and previous:
            for path in previous:
                _load(path, options)
            continue
        frames = {}
        for piece in ("factor_return", "covariance"):
            response = call(
                client.risk_piece,
                piece,
                value,
                [],
                model=options.model,
                industry_mapping=options.industry_mapping,
            )
            frames[piece] = decode_piece(piece, response, day, options.order_book_ids)
        chunks = {key: [] for key in ("exposure", "specific_return", "specific_risk")}
        for codes in chunk_list(options.order_book_ids, options.batch_size):
            for piece in chunks:
                response = call(
                    client.risk_piece,
                    piece,
                    value,
                    codes,
                    model=options.model,
                    industry_mapping=options.industry_mapping,
                )
                chunks[piece].append(decode_piece(piece, response, day, tuple(codes)))
        for piece, parts in chunks.items():
            # 不允许 concat 以外连接方式悄悄并集不同批次的因子标签。
            if piece == "exposure" and any(set(p.columns) != set(parts[0].columns) for p in parts):
                raise RawIntegrityError("风险暴露批次间因子集合变化")
            frames[piece] = pd.concat(parts, axis=0 if piece == "exposure" else 1)
        frames = validate_bundle(frames, options, day)
        observation = uuid4().hex
        folder = root / value / observation
        folder.mkdir(parents=True)
        manifest = {
            "day": value,
            "observation_id": observation,
            "variant_id": options.variant_id,
            "identity": options.identity,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }
        for piece, frame in frames.items():
            path = folder / (piece + ".parquet")
            temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
            frame.to_parquet(temporary, compression="zstd", index=True)
            os.replace(temporary, path)
            manifest["files"][piece] = file_hash(path)
        _json(folder / "manifest.json", manifest)
        plan["completed"][value] = observation
        _json(journal, plan)
        written += sum(len(frame) for frame in frames.values())
        log.info(
            "Ricequant risk bundle published dataset=rq_risk_model day=%s observation=%s rows=%d",
            value,
            observation,
            written,
        )
    journal.unlink()
    return written
