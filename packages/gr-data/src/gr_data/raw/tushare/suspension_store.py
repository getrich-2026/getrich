"""停复牌稀疏分区的覆盖凭据：空响应也必须有成功请求证据。"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd


class InvalidCoverageError(ValueError):
    """凭据与分区不一致或内容非法；读取端拒绝消费，抓取端据此整月重建。"""


def read_coverage(
    path: Path, *, content: bytes | None = None
) -> tuple[list[date], datetime, str] | None:
    """校验文件哈希并读取实际请求日期；旧分区返回 None，损坏凭据拒绝消费。

    Raises:
        InvalidCoverageError: 哈希不符（如写完分区、未写凭据即中断）或凭据内容非法。
    """
    manifest = path.with_suffix(".coverage.json")
    if not manifest.exists():
        return None
    try:
        value = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        raise InvalidCoverageError(f"Invalid suspension coverage: {path.name}") from exc
    digest = hashlib.sha256(path.read_bytes() if content is None else content).hexdigest()
    if value.get("version") != 1 or value.get("sha256") != digest:
        raise InvalidCoverageError(f"Invalid suspension coverage: {path.name}")
    try:
        days = [date.fromisoformat(day) for day in value["requested_dates"]]
        observed = datetime.fromisoformat(value["observed_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCoverageError(f"Invalid suspension coverage dates: {path.name}") from exc
    if (
        not days
        or len(days) != len(set(days))
        or any(day.strftime("%Y-%m") != path.stem for day in days)
        or observed.utcoffset() is None
    ):
        raise InvalidCoverageError(f"Invalid suspension coverage dates: {path.name}")
    return sorted(days), observed, digest


def publish_coverage(path: Path, days: list[date]) -> None:
    """在 Parquet 成功替换后原子发布凭据；中断导致哈希不匹配时读取端拒绝。"""
    value = {
        "version": 1,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "requested_dates": [day.isoformat() for day in sorted(set(days))],
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest = path.with_suffix(".coverage.json")
    temporary = manifest.with_suffix(f".tmp-{uuid4().hex}")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(manifest)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_events(frame: pd.DataFrame) -> pd.DataFrame:
    """保留 S/R 与时段原义；同键冲突拒绝，不用最后一条静默裁决。"""
    columns = ["ts_code", "trade_date", "suspend_type", "suspend_timing"]
    if set(columns) - set(frame.columns):
        raise ValueError("suspend_d missing required fields; recapture the raw partition")
    result = frame[columns].copy()
    result["ts_code"] = result["ts_code"].astype("string").str.strip()
    if result["ts_code"].isna().any() or result["ts_code"].eq("").any():
        raise ValueError("suspend_d contains empty symbols")
    dates = pd.to_datetime(result["trade_date"].astype(str), format="%Y%m%d", errors="raise")
    if dates.isna().any() or not result["suspend_type"].isin(["S", "R"]).all():
        raise ValueError("suspend_d contains invalid dates or event types")
    result["trade_date"] = dates.dt.date
    timing = result["suspend_timing"].astype("string").str.strip()
    result["suspend_timing"] = timing.mask(timing.eq(""), pd.NA)
    result = result.drop_duplicates()
    if result.duplicated(["ts_code", "trade_date", "suspend_type"]).any():
        raise ValueError("suspend_d contains conflicting event timings")
    return result.reset_index(drop=True)
