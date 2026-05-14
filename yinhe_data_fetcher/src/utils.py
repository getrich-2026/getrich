"""通用工具: 日期, 切块, parquet I/O."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypeVar

import pandas as pd

T = TypeVar("T")


# -----------------------------------------------------------------------------
# 日期工具
# AmazingData 使用 8 位 int, 例: 20240530
# -----------------------------------------------------------------------------
def today_int() -> int:
    return int(date.today().strftime("%Y%m%d"))


def to_int_date(d: int | str | date | datetime | pd.Timestamp) -> int:
    if isinstance(d, int):
        return d
    if isinstance(d, str):
        s = d.replace("-", "").replace("/", "")
        return int(s[:8])
    if isinstance(d, (datetime, pd.Timestamp)):
        return int(d.strftime("%Y%m%d"))
    if isinstance(d, date):
        return int(d.strftime("%Y%m%d"))
    raise TypeError(f"Unsupported date type: {type(d)}")


def int_to_date(d: int) -> date:
    return datetime.strptime(str(int(d)), "%Y%m%d").date()


def next_int_date(d: int, days: int = 1) -> int:
    return to_int_date(int_to_date(d) + timedelta(days=days))


# -----------------------------------------------------------------------------
# 切块
# -----------------------------------------------------------------------------
def chunk_list(items: Sequence[T], size: int) -> Iterator[list[T]]:
    """把 list 切成大小为 size 的小块."""
    if size <= 0:
        raise ValueError(f"chunk size must be > 0, got {size}")
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def chunk_date_range(start: int, end: int, step_days: int) -> Iterator[tuple[int, int]]:
    """把 [start, end] (闭区间, int8 date) 切成不超过 step_days 的子区间."""
    if step_days <= 0:
        raise ValueError(f"step_days must be > 0, got {step_days}")
    if start > end:
        return
    cur = int_to_date(start)
    end_d = int_to_date(end)
    while cur <= end_d:
        chunk_end = min(cur + timedelta(days=step_days - 1), end_d)
        yield to_int_date(cur), to_int_date(chunk_end)
        cur = chunk_end + timedelta(days=1)


# -----------------------------------------------------------------------------
# Parquet I/O
# -----------------------------------------------------------------------------
def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


import logging
import uuid

_logger = logging.getLogger(__name__)


def _has_named_index(df: pd.DataFrame) -> bool:
    """判断 DataFrame 是否有可用于去重的命名索引."""
    if isinstance(df.index, pd.MultiIndex):
        return all(n is not None for n in df.index.names)
    return df.index.name is not None


def _duckdb_merge(
    old_path: str,
    new_path: str,
    idx_names: list[str],
) -> pd.DataFrame:
    """用 DuckDB SQL 完成 old + new 的合并去重排序.

    核心逻辑:
    1. UNION BY NAME 处理 schema drift（新增列自动补 NULL）。
    2. ROW_NUMBER PARTITION BY index_cols 去重，新数据优先。
    3. ORDER BY index_cols 排序。

    Time Complexity: O(N log N)  (N = old_rows + new_rows)
    Space Complexity: DuckDB native memory, 不经过 pandas 中间态。
    """
    import duckdb

    idx_cols_sql = ", ".join(f'"{n}"' for n in idx_names)

    sql = f"""
    WITH merged AS (
        SELECT *, 1 AS _src_order FROM read_parquet('{old_path}')
        UNION BY NAME
        SELECT *, 0 AS _src_order FROM read_parquet('{new_path}')
    ),
    deduped AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY {idx_cols_sql}
                   ORDER BY _src_order ASC
               ) AS _rn
        FROM merged
    )
    SELECT * EXCLUDE (_src_order, _rn)
    FROM deduped
    WHERE _rn = 1
    ORDER BY {idx_cols_sql}
    """
    result_df: pd.DataFrame = duckdb.sql(sql).df()
    # DuckDB 输出丢失 pandas index 元信息, 需要重建
    result_df.set_index(idx_names if len(idx_names) > 1 else idx_names[0], inplace=True)
    return result_df


def _pandas_merge(old_path: str, df: pd.DataFrame) -> pd.DataFrame:
    """Pandas 全量合并: 用于无命名索引或 DuckDB 不可用的降级路径."""
    old = pd.read_parquet(old_path)
    combined = pd.concat([old, df], axis=0)
    if combined.index.name or isinstance(combined.index, pd.MultiIndex):
        combined = combined[~combined.index.duplicated(keep="last")]
    else:
        combined = combined.drop_duplicates(keep="last")
    combined.sort_index(inplace=True)
    return combined


def write_parquet(df: pd.DataFrame, path: Path, *, append: bool = False) -> None:
    """写 parquet; append 时会先读旧文件并按索引/列去重合并.

    当 DataFrame 拥有命名索引时, 优先使用 DuckDB 路径完成合并,
    避免将整个旧文件加载到 pandas 内存中. 无命名索引或 DuckDB
    不可用时自动降级为纯 pandas 合并.
    """
    path = Path(path)
    ensure_dir(path.parent)
    tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp.parquet")

    try:
        if append and path.exists():
            if _has_named_index(df):
                merged_df = _write_parquet_duckdb(df, path, tmp_path)
            else:
                merged_df = _pandas_merge(str(path), df)
            merged_df.to_parquet(tmp_path, index=True)
        else:
            df.to_parquet(tmp_path, index=True)

        tmp_path.replace(path)
    except Exception as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise e


def _write_parquet_duckdb(
    df: pd.DataFrame, path: Path, tmp_path: Path
) -> pd.DataFrame:
    """DuckDB 合并路径: 写新数据到临时文件, 用 SQL 合并旧文件, 返回结果 DataFrame.

    若 DuckDB 导入或执行失败, 自动降级为 pandas 合并并记录日志.
    """
    new_tmp = path.with_suffix(f".{uuid.uuid4().hex}.new.tmp.parquet")
    try:
        # 将新增数据先落盘为临时 parquet, 供 DuckDB 读取
        df.to_parquet(new_tmp, index=True)

        idx_names: list[str]
        if isinstance(df.index, pd.MultiIndex):
            idx_names = [str(n) for n in df.index.names]
        else:
            idx_names = [str(df.index.name)]

        try:
            return _duckdb_merge(str(path), str(new_tmp), idx_names)
        except Exception as exc:
            _logger.warning(
                "DuckDB merge failed, fallback to pandas: %s", exc
            )
            return _pandas_merge(str(path), df)
    finally:
        if new_tmp.exists():
            try:
                new_tmp.unlink()
            except OSError:
                pass


def read_parquet_if_exists(path: Path) -> pd.DataFrame | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def read_parquet_index(path: Path) -> pd.DataFrame | None:
    """仅读取 parquet 文件的索引，不加载数据列，用于快速检查."""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path, columns=[])
    except Exception:
        return None


def last_index_date(df: pd.DataFrame | None) -> int | None:
    """返回 df.index 的最后一个日期 (int8 date); 若无返回 None."""
    if df is None or len(df.index) == 0:
        return None
    idx = df.index
    try:
        last = idx.max()
    except Exception:
        return None
    try:
        return to_int_date(last)
    except Exception:
        try:
            return int(last)
        except Exception:
            return None


# -----------------------------------------------------------------------------
# 重试 / 限流
# -----------------------------------------------------------------------------
def sleep_s(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def retry_call(
    fn,
    *args,
    max_retries: int = 5,
    backoff_base: float = 3.0,
    logger=None,
    **kwargs,
):
    """指数退避重试. 最后一次失败会抛原异常."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == max_retries:
                break
            wait = backoff_base * (2 ** (attempt - 1))
            if logger:
                logger.warning(
                    "call %s failed (attempt %d/%d): %s; sleep %.1fs then retry",
                    getattr(fn, "__name__", str(fn)),
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def flatten_iter(it: Iterable[Iterable[T]]) -> list[T]:
    out: list[T] = []
    for x in it:
        out.extend(x)
    return out
