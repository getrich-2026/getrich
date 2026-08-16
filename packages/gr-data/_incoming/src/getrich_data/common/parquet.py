"""Parquet 原子读写与去重合并。

- 写：先写 UUID 临时文件，再 ``os.replace`` 原子替换，避免半成品文件。
- 追加：与已有文件按索引去重合并（pandas，新数据胜出），处理 schema 漂移。

依赖 pandas + pyarrow。K 线按 code+月分区，单文件很小，pandas 合并足够。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd


def read_parquet_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:  # noqa: BLE001 - 损坏文件按不存在处理，交由上层重写
        return None


def _idx_names(df: pd.DataFrame) -> list[str]:
    return [n for n in (df.index.names or []) if n is not None]


def _merge(old_path: Path, new_df: pd.DataFrame, idx_names: list[str]) -> pd.DataFrame:
    """合并旧文件与新数据：按索引去重，冲突时取新数据（keep='last'）。

    新数据拼在末尾，``keep='last'`` 保证同键冲突时新数据胜出。``concat`` 按列名对齐，
    新增列在旧行自动填 NaN，处理 schema 漂移。
    """
    old = pd.read_parquet(old_path)
    combined = pd.concat([old, new_df], axis=0)
    if idx_names:
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def write_parquet(df: pd.DataFrame, path: Path, *, append: bool = False) -> None:
    """原子写 parquet（zstd）。append=True 时与已有文件按索引去重合并。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    idx_names = _idx_names(df)

    out_df = df
    if append and path.exists():
        out_df = _merge(path, df, idx_names)

    tmp = path.with_suffix(f".tmp-{uuid.uuid4().hex}.parquet")
    try:
        write_index = bool(idx_names)
        out_df.to_parquet(tmp, compression="zstd", index=write_index)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def last_index_date(df: pd.DataFrame | None) -> int | None:
    """取索引最大值并转 int8（K 线水位用）。"""
    if df is None or df.empty:
        return None
    try:
        mx = df.index.max()
    except (TypeError, ValueError):
        return None
    if hasattr(mx, "strftime"):
        return int(mx.strftime("%Y%m%d"))
    try:
        return int(mx)
    except (TypeError, ValueError):
        return None
