"""按后缀自动分发的表格读取。

一个入口读 csv / parquet / xlsx / json / feather，引擎可选 polars（默认）
或 pandas。**只管表格** —— 读图片、npy、纯文本用 stdlib 就够了，包一层
只会多一层要维护的分发表。

移植自 ``lntools.core.filesystem``（2026-08-17），改动：
* 默认引擎写死 ``polars``，不再读 ``~/.config`` 里的全局配置；
* 日志换成 stdlib ``logging``；
* 新增 :func:`read_frame` 与 :func:`cast_all_utf8` —— 导入用户上传的
  证券代码文件时必须走「全列按字符串读」这条路，否则 ``000001`` 会被
  类型推断成整数、丢掉前导零，代码就再也对不上了。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import polars as pl

from gr_tools.fs import PathLike, get_files


logger = logging.getLogger(__name__)

Engine = Literal["polars", "pandas"]

#: 用于 :func:`read_directory` 的日期入参：``date`` / ``datetime`` /
#: ``YYYY-MM-DD`` 字符串 / ``YYYYMMDD`` 整数。
DateLike = date | datetime | str | int

READERS: dict[str, dict[str, Callable[..., Any]]] = {
    "polars": {
        ".csv": pl.read_csv,
        ".txt": pl.read_csv,
        ".parquet": pl.read_parquet,
        ".xlsx": pl.read_excel,
        ".xls": pl.read_excel,
        ".json": pl.read_json,
        ".ndjson": pl.read_ndjson,
        ".feather": pl.read_ipc,
    },
    "pandas": {
        ".csv": pd.read_csv,
        ".txt": pd.read_csv,
        ".parquet": pd.read_parquet,
        ".xlsx": pd.read_excel,
        ".xls": pd.read_excel,
        ".json": pd.read_json,
        ".feather": pd.read_feather,
    },
}

#: 被当作「表格」的后缀，:func:`read_frame` 只认这些。
FRAME_SUFFIXES = frozenset({".csv", ".txt", ".parquet", ".xlsx", ".xls", ".feather"})


def load_data(
    file_path: PathLike, engine: Engine | str = "polars", **kwargs: Any
) -> pl.DataFrame | pd.DataFrame:
    """按后缀选 reader 并读取，不检查文件是否存在。

    Args:
        file_path: 文件路径。
        engine: ``polars``（默认）或 ``pandas``。
        **kwargs: 透传给底层 reader（如 ``separator``、``columns``）。

    Returns:
        DataFrame。

    Raises:
        ValueError: 引擎不支持，或该引擎不支持这个后缀。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if engine not in READERS:
        raise ValueError(f"unsupported engine: {engine}, available: {sorted(READERS)}")

    reader = READERS[str(engine)].get(suffix)
    if reader is None:
        raise ValueError(f"engine '{engine}' does not support file format: {suffix or '(none)'}")
    return reader(str(path), **kwargs)


def read_file(
    path: PathLike, engine: Engine | str = "polars", **kwargs: Any
) -> pl.DataFrame | pd.DataFrame:
    """读单个文件，文件不存在时抛 ``FileNotFoundError``。

    Args:
        path: 文件路径。
        engine: 见 :func:`load_data`。
        **kwargs: 透传给底层 reader。

    Returns:
        DataFrame。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 引擎或后缀不支持。
        RuntimeError: 底层 reader 抛错。
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"file not found: {path}")

    try:
        return load_data(path, engine=engine, **kwargs)
    except ValueError:
        raise
    except Exception as exc:
        # 统一包成 RuntimeError，把路径和引擎写进消息里，便于定位。
        raise RuntimeError(f"failed to read {path} with engine {engine}: {exc}") from exc


def cast_all_utf8(df: pl.DataFrame | pd.DataFrame) -> pl.DataFrame | pd.DataFrame:
    """把 DataFrame 所有列转成字符串列。

    用于「先当文本读进来，再由业务层显式解析」的导入路径：类型推断
    在证券代码（``000001``）、交易所后缀、日期这些列上都会出错，
    而错误是静默的。
    """
    if isinstance(df, pl.DataFrame):
        return df.with_columns(pl.all().cast(pl.Utf8))
    return df.astype("string")


def read_frame(
    path: PathLike,
    *,
    engine: Engine = "polars",
    all_string: bool = False,
    **kwargs: Any,
) -> pl.DataFrame | pd.DataFrame:
    """读一个表格文件（csv / parquet / excel / feather）。

    Args:
        path: 文件路径。
        engine: ``polars``（默认）或 ``pandas``。
        all_string: True 时全列按字符串读入 —— CSV 直接关掉类型推断，
            其余格式读完再统一 cast。**读用户提供的代码 / 日期文件时
            必须传 True**，否则 ``000001`` 会变成 ``1``。
        **kwargs: 透传给底层 reader。

    Returns:
        DataFrame。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 后缀不是表格格式，或引擎不支持。
    """
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in FRAME_SUFFIXES:
        raise ValueError(
            f"not a tabular file: {target.name}; expected one of {sorted(FRAME_SUFFIXES)}"
        )
    if engine not in ("polars", "pandas"):
        raise ValueError(f"read_frame engine must be 'polars' or 'pandas', got {engine!r}")

    if all_string and suffix in (".csv", ".txt"):
        if engine == "polars":
            kwargs.setdefault("infer_schema_length", 0)
        else:
            kwargs.setdefault("dtype", str)
            kwargs.setdefault("keep_default_na", False)

    df = read_file(target, engine=engine, **kwargs)
    if not isinstance(df, pl.DataFrame | pd.DataFrame):
        raise ValueError(f"reader returned {type(df).__name__}, not a DataFrame: {target}")
    return cast_all_utf8(df) if all_string else df


def _to_date(value: DateLike) -> date:
    """把四种日期写法归一成 ``date``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int):
        text = str(value)
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(str(value))


def _date_range(start: DateLike, end: DateLike) -> list[date]:
    first, last = _to_date(start), _to_date(end)
    if last < first:
        raise ValueError(f"end date {last} is earlier than start date {first}")
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _formatted_files(
    sdt: DateLike,
    edt: DateLike,
    path: PathLike,
    file_pattern: str,
    date_format: str,
    trading_dates: Sequence[DateLike] | None,
) -> list[Path]:
    """按日期模板列出实际存在的文件。"""
    if trading_dates is not None:
        dates = [_to_date(d) for d in trading_dates]
    else:
        dates = _date_range(sdt, edt)

    base_path = Path(path)
    if not base_path.exists():
        raise FileNotFoundError(f"directory not found: {path}")

    expected = [file_pattern.format(date=d.strftime(date_format)) for d in dates]
    existing = [base_path / name for name in expected if (base_path / name).exists()]

    missing = len(expected) - len(existing)
    if missing:
        logger.warning("read_directory: %d/%d files missing under %s", missing, len(expected), path)
    if not existing:
        raise FileNotFoundError(
            f"no files matching '{file_pattern}' found in {path} between {sdt} and {edt}"
        )
    logger.info("read_directory: found %d/%d files in %s", len(existing), len(dates), path)
    return existing


def read_directory(
    path: PathLike,
    *,
    engine: Engine = "polars",
    sdt: DateLike | None = None,
    edt: DateLike | None = None,
    file_pattern: str = "{date}.csv",
    date_format: str = "%Y-%m-%d",
    trading_dates: Sequence[DateLike] | None = None,
    threads: int = 10,
    all_string: bool = False,
    **kwargs: Any,
) -> pl.DataFrame | pd.DataFrame:
    """并行读取目录下的多个表格文件并纵向拼接。

    给了 ``sdt`` / ``edt``（或 ``trading_dates``）就按日期模板取文件，
    否则读目录下全部文件。

    Args:
        path: 目录路径。
        engine: ``polars``（默认）或 ``pandas``。
        sdt: 起始日期（含），需与 ``edt`` 同时给。
        edt: 结束日期（含）。
        file_pattern: 文件名模板，``{date}`` 为占位符。
        date_format: 模板里日期的 ``strftime`` 格式。
        trading_dates: 显式给定的日期列表；给了就不按自然日展开。
        threads: 并行读取线程数。
        all_string: 全列按字符串读，见 :func:`read_frame`。
        **kwargs: 透传给底层 reader。

    Returns:
        拼接后的 DataFrame；目录为空时返回空 DataFrame。

    Raises:
        FileNotFoundError: 目录不存在，或按模板一个文件都没匹配上。
        ValueError: 引擎不支持，或 ``sdt`` / ``edt`` 只给了一个。
        RuntimeError: 拼接失败（各文件 schema 不兼容）。

    Time Complexity:
        O(n·m)，n 为文件数、m 为单文件行数。
    Space Complexity:
        O(n·m)，全部数据进内存。
    """
    if engine not in ("polars", "pandas"):
        raise ValueError(f"engine must be 'polars' or 'pandas', got {engine!r}")
    if (sdt is None) != (edt is None):
        raise ValueError("sdt and edt must be provided together")

    base_path = Path(path)
    if not base_path.exists():
        raise FileNotFoundError(f"directory not found: {path}")

    empty: pl.DataFrame | pd.DataFrame = pl.DataFrame() if engine == "polars" else pd.DataFrame()

    if sdt is not None and edt is not None:
        files = _formatted_files(sdt, edt, base_path, file_pattern, date_format, trading_dates)
    else:
        files = [f for f in get_files(base_path) if f.suffix.lower() in FRAME_SUFFIXES]
        if not files:
            logger.warning("read_directory: no tabular file found in %s", base_path)
            return empty

    def _read_one(target: Path) -> pl.DataFrame | pd.DataFrame | None:
        try:
            return read_frame(target, engine=engine, all_string=all_string, **kwargs)
        except (OSError, ValueError, RuntimeError) as exc:
            # 单个文件坏掉不该让整批读取失败：记下来，继续读其它文件。
            logger.error("read_directory: failed to read %s: %s", target.name, exc)
            return None

    with ThreadPoolExecutor(max_workers=max(1, threads)) as executor:
        results = [df for df in executor.map(_read_one, files) if df is not None and len(df) > 0]

    if not results:
        logger.warning("read_directory: no valid data read from %d file(s)", len(files))
        return empty

    try:
        if engine == "polars":
            return pl.concat(results, how="vertical_relaxed")  # type: ignore[type-var]
        return pd.concat(results, ignore_index=True)  # type: ignore[arg-type]
    except Exception as exc:
        # 各文件 schema 不兼容时给出可定位的报错，而不是底层的裸异常。
        raise RuntimeError(f"failed to concatenate {len(results)} frame(s): {exc}") from exc


__all__ = [
    "FRAME_SUFFIXES",
    "READERS",
    "DateLike",
    "Engine",
    "cast_all_utf8",
    "load_data",
    "read_directory",
    "read_file",
    "read_frame",
]
