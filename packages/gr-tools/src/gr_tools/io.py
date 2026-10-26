"""按后缀自动分发的表格读取。

一个入口读 csv / parquet / xlsx / json / feather，统一使用 polars，
Excel 读取依赖 fastexcel。**只管表格** —— 读图片、npy、纯文本用 stdlib 就够了，包一层
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
from typing import Any, cast

import polars as pl

from gr_tools.fs import PathLike, get_files


logger = logging.getLogger(__name__)

#: 用于 :func:`read_directory` 的日期入参：``date`` / ``datetime`` /
#: ``YYYY-MM-DD`` 字符串 / ``YYYYMMDD`` 整数。
DateLike = date | datetime | str | int

_READERS: dict[str, Callable[..., pl.DataFrame]] = {
    ".csv": pl.read_csv,
    ".txt": pl.read_csv,
    ".parquet": pl.read_parquet,
    # 默认读取单表；多表选项的实际返回值由 read_frame 的运行时检查拒绝。
    ".xlsx": cast(Callable[..., pl.DataFrame], pl.read_excel),
    ".xls": cast(Callable[..., pl.DataFrame], pl.read_excel),
    ".json": pl.read_json,
    ".ndjson": pl.read_ndjson,
    ".feather": pl.read_ipc,
}

#: 被当作「表格」的后缀，:func:`read_frame` 只认这些。
FRAME_SUFFIXES = frozenset({".csv", ".txt", ".parquet", ".xlsx", ".xls", ".feather"})


def excel_sheet_names(path: PathLike) -> list[str]:
    """读取 Excel 工作表名，按工作簿顺序返回，不读取单元格数据。

    Args:
        path: xlsx / xls 文件路径。

    Raises:
        FileNotFoundError: 文件不存在。
        RuntimeError: 工作簿无法读取，保留底层异常链。
        MemoryError: 内存不足，原样传播。
    """
    import fastexcel

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"file not found: {path}")
    try:
        return fastexcel.read_excel(target).sheet_names
    except MemoryError:
        raise
    except Exception as exc:
        raise RuntimeError(f"failed to read sheet names of {path}: {exc}") from exc


def load_data(file_path: PathLike, **kwargs: Any) -> pl.DataFrame:
    """按后缀选 reader 并读取，不检查文件是否存在。

    Args:
        file_path: 文件路径。
        **kwargs: 透传给底层 reader（如 ``separator``、``columns``）。

    Returns:
        DataFrame。

    Raises:
        ValueError: 后缀不支持。
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    reader = _READERS.get(suffix)
    if reader is None:
        raise ValueError(f"polars does not support file format: {suffix or '(none)'}")
    return reader(str(path), **kwargs)


def read_file(path: PathLike, **kwargs: Any) -> pl.DataFrame:
    """读单个文件，文件不存在时抛 ``FileNotFoundError``。

    Args:
        path: 文件路径。
        **kwargs: 透传给底层 reader。

    Returns:
        DataFrame。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 后缀不支持。
        RuntimeError: 底层 reader 抛错。
        MemoryError: 内存不足，原样传播，不作为坏文件跳过。
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"file not found: {path}")

    suffix = Path(path).suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise ValueError(f"polars does not support file format: {suffix or '(none)'}")

    try:
        return reader(str(path), **kwargs)
    except MemoryError:
        raise
    except Exception as exc:
        # 补充文件上下文，保留底层异常链。
        raise RuntimeError(f"failed to read {path}: {exc}") from exc


def cast_all_utf8(df: pl.DataFrame) -> pl.DataFrame:
    """把 DataFrame 所有列转成字符串列。

    用于「先当文本读进来，再由业务层显式解析」的导入路径：类型推断
    在证券代码（``000001``）、交易所后缀、日期这些列上都会出错，
    而错误是静默的。
    """
    return df.with_columns(pl.all().cast(pl.Utf8))


def read_frame(
    path: PathLike,
    *,
    all_string: bool = False,
    **kwargs: Any,
) -> pl.DataFrame:
    """读一个表格文件（csv / parquet / excel / feather）。

    Args:
        path: 文件路径。
        all_string: True 时全列按字符串读入 —— CSV / Excel 默认关闭类型推断，
            parquet / feather 读完再统一 cast。**读用户提供的代码 / 日期文件时
            必须传 True**，否则 ``000001`` 会变成 ``1``。
            Excel 原本存为数字的单元格无法恢复前导零；fastexcel 将数字 1
            读成 "1"，日期单元格保留日期时间文本（含午夜时间）。
        **kwargs: 透传给底层 reader。

    Returns:
        DataFrame。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 后缀不是表格格式、读取结果不是单个 DataFrame，或无法转为全字符串。
        RuntimeError: 底层 reader 抛错。
    """
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in FRAME_SUFFIXES:
        raise ValueError(
            f"not a tabular file: {target.name}; expected one of {sorted(FRAME_SUFFIXES)}"
        )
    if all_string and suffix in (".csv", ".txt", ".xlsx", ".xls"):
        kwargs.setdefault("infer_schema_length", 0)

    df = read_file(target, **kwargs)
    if not isinstance(df, pl.DataFrame):
        raise ValueError(
            f"reader returned {type(df).__name__}, not a DataFrame: {target}; "
            "Excel supports only a single worksheet"
        )
    if not all_string:
        return df
    try:
        return cast_all_utf8(df)
    except pl.exceptions.PolarsError as exc:
        raise ValueError(f"cannot read {path} as all-string: {exc}") from exc


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
    sdt: DateLike | None,
    edt: DateLike | None,
    path: PathLike,
    file_pattern: str,
    date_format: str,
    trading_dates: Sequence[DateLike] | None,
) -> list[Path]:
    """按日期模板列出实际存在的文件。"""
    bounds: tuple[date, date] | None = None
    if sdt is not None and edt is not None:
        bounds = (_to_date(sdt), _to_date(edt))
        if bounds[1] < bounds[0]:
            raise ValueError(f"end date {bounds[1]} is earlier than start date {bounds[0]}")
    if trading_dates is not None:
        dates = sorted({_to_date(d) for d in trading_dates})
        if bounds is not None:
            selected = [d for d in dates if bounds[0] <= d <= bounds[1]]
            excluded = len(dates) - len(selected)
            if excluded:
                logger.warning(
                    "read_directory: filtered %d trading dates outside [%s, %s]",
                    excluded,
                    *bounds,
                )
            dates = selected
        if not dates:
            raise ValueError("no trading dates remain in the requested range")
    elif bounds is not None:
        dates = _date_range(*bounds)
    else:
        raise ValueError("trading_dates or both sdt and edt must be provided")

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
            f"no files matching '{file_pattern}' found in {path} between {dates[0]} and {dates[-1]}"
        )
    logger.info("read_directory: found %d/%d files in %s", len(existing), len(dates), path)
    return existing


def read_directory(
    path: PathLike,
    *,
    sdt: DateLike | None = None,
    edt: DateLike | None = None,
    file_pattern: str = "{date}.csv",
    date_format: str = "%Y-%m-%d",
    trading_dates: Sequence[DateLike] | None = None,
    threads: int = 10,
    all_string: bool = False,
    **kwargs: Any,
) -> pl.DataFrame:
    """并行读取目录下的多个表格文件并纵向拼接。

    给了 ``sdt`` / ``edt``（或 ``trading_dates``）就按日期模板取文件，
    否则读目录下全部文件。

    Args:
        path: 目录路径。
        sdt: 起始日期（含），需与 ``edt`` 同时给。
        edt: 结束日期（含）。
        file_pattern: 文件名模板，``{date}`` 为占位符。
        date_format: 模板里日期的 ``strftime`` 格式。
        trading_dates: 显式日期列表，去重后升序读取；可单独提供。
            同时提供 sdt / edt 时，过滤闭区间外的日期并告警。
        threads: 并行读取线程数。
        all_string: 全列按字符串读，见 :func:`read_frame`。
        **kwargs: 透传给底层 reader。

    Returns:
        拼接后的 DataFrame；没有表格文件或成功读取的表全为空时返回空 DataFrame。
        部分文件失败时记录并汇总告警，继续拼接成功的文件。

    Raises:
        FileNotFoundError: 目录不存在，或按模板一个文件都没匹配上。
        ValueError: ``sdt`` / ``edt`` 只给了一个、范围颠倒，或没有可用日期。
        RuntimeError: 全部文件读取失败，或拼接失败（各文件 schema 不兼容）。
        MemoryError: 内存不足，原样传播。

    Time Complexity:
        O(n·m)，n 为文件数、m 为单文件行数。
    Space Complexity:
        O(n·m)，全部数据进内存。
    """
    if (sdt is None) != (edt is None):
        raise ValueError("sdt and edt must be provided together")

    base_path = Path(path)
    if not base_path.exists():
        raise FileNotFoundError(f"directory not found: {path}")

    if trading_dates is not None or (sdt is not None and edt is not None):
        files = _formatted_files(sdt, edt, base_path, file_pattern, date_format, trading_dates)
    else:
        files = [f for f in get_files(base_path) if f.suffix.lower() in FRAME_SUFFIXES]
        if not files:
            logger.warning("read_directory: no tabular file found in %s", base_path)
            return pl.DataFrame()

    def _read_one(target: Path) -> pl.DataFrame | None:
        try:
            return read_frame(target, all_string=all_string, **kwargs)
        except (OSError, ValueError, RuntimeError) as exc:
            # 单个文件坏掉不该让整批读取失败：记下来，继续读其它文件。
            logger.error("read_directory: failed to read %s: %s", target.name, exc)
            return None

    results: list[pl.DataFrame] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, threads)) as executor:
        # map 保留输入顺序；在主线程归集失败，避免线程间修改共享列表。
        for target, df in zip(files, executor.map(_read_one, files), strict=True):
            if df is None:
                failures.append(target.name)
            elif not df.is_empty():
                results.append(df)

    if len(failures) == len(files):
        listed = ", ".join(failures[:10])
        summary = f" ({len(failures)} total)" if len(failures) > 10 else ""
        raise RuntimeError(f"failed to read all files in {base_path}: {listed}{summary}")
    if failures:
        logger.warning(
            "read_directory: %d/%d files failed under %s", len(failures), len(files), base_path
        )

    if not results:
        logger.warning("read_directory: no valid data read from %d file(s)", len(files))
        return pl.DataFrame()

    try:
        return pl.concat(results, how="vertical_relaxed")
    except MemoryError:
        raise
    except Exception as exc:
        # 各文件 schema 不兼容时给出可定位的报错，而不是底层的裸异常。
        raise RuntimeError(f"failed to concatenate {len(results)} frame(s): {exc}") from exc


__all__ = [
    "FRAME_SUFFIXES",
    "DateLike",
    "cast_all_utf8",
    "excel_sheet_names",
    "load_data",
    "read_directory",
    "read_file",
    "read_frame",
]
