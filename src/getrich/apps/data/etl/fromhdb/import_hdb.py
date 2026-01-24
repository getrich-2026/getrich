# pylint: disable=no-member, invalid-name  # rqdatac uses dynamic API binding
# pyright: reportAttributeAccessIssue=false
# mypy: disable-error-code="import-untyped"
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from lntools.utils import Logger

from getrich.config import settings

from ..ricequant import init_rq
from ..transforms import convert_symbol, normalize_date_string, normalize_datetime_column

# 根据配置决定是否导入 HDB 模块
if settings.hdb.enabled:
    import hdb
else:
    hdb = Any

log = Logger(module_name="HdbEtl")

# ============================================================================
# 全局变量和初始化
# ============================================================================

symbol_cache: dict[str, str] = {}
_rq_convert_func = None  # pylint: disable=C0103

# 根据配置决定是否初始化 RiceQuant
if settings.ricequant.enabled:
    try:
        import rqdatac as rq

        init_rq()
        _rq_convert_func = rq.id_convert  # pylint: disable=E1101
        log.info("RiceQuant initialized successfully")
    except (ImportError, Exception) as e:
        log.error(f"RiceQuant initialization failed: {e}")
else:
    log.info("RiceQuant is disabled in settings, skipping initialization")


# ============================================================================
# 内部工具函数
# ============================================================================


def _read_hdb_to_df(
    hdb_file: Any,
    symbols: list[str],
    data_type: str,
    begin: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """
    从 HDB 文件中读取指定数据并转换为 Pandas DataFrame（内部辅助函数）。

    Args:
        hdb_file: 已打开的 HDB 文件对象
        symbols: 要读取的标的代码列表，支持通配符 (如 "SH.600*")
        data_type: 要读取的数据类型 (如 "SecurityTick", "SecurityKdata")
        begin: 开始时间。默认为 None
        end: 结束时间。默认为 None

    Returns:
        包含所读取数据的 DataFrame, 如果无数据则返回空 DataFrame
    """
    if (begin is None) and (end is None):
        task = hdb_file.open_read_task(symbols=symbols, types=[data_type])
    elif begin is None:
        task = hdb_file.open_read_task(end_time=end, symbols=symbols, types=[data_type])
    elif end is None:
        task = hdb_file.open_read_task(begin_time=begin, symbols=symbols, types=[data_type])
    else:
        task = hdb_file.open_read_task(
            begin_time=begin, end_time=end, symbols=symbols, types=[data_type]
        )

    items = task.read(max_count=0)  # 读取所有数据
    task.close()

    if len(items) == 0:
        return pd.DataFrame()

    # 从返回的数据中获取数据类型定义
    data_type_def = hdb_file.data_types[items["type_id"][0]]
    # 解析具体数据
    data = data_type_def.items_data(items["data"])
    df = _process_data_to_df(data_type_def, data, items)

    return df


def _process_data_to_df(data_type_def: Any, data: np.ndarray, items: np.ndarray) -> pd.DataFrame:
    """将 HDB 原始数据结构转换为 DataFrame（内部辅助函数）。"""
    df = pd.DataFrame()

    # 将 hdb 数据结构扁平化到 dataframe
    if data.dtype.fields is not None:
        for name in data_type_def.dtype.fields:
            field_type = data.dtype.fields[name][0]
            if field_type.ndim == 0:
                df[name] = data[name]
            elif field_type.ndim == 1:
                for idx in range(field_type.shape[0]):
                    df[f"{name}{idx}"] = data[name][:, idx]

    # 添加公共字段
    if items.dtype.names is not None:
        for col in ["symbol", "local_time"]:
            if col in items.dtype.names:
                df[col] = pd.Series(items[col])

    # symbol 字段解码
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].apply(lambda x: x.decode("utf-8"))
        df.rename(columns={"symbol": "hdb_symbol"}, inplace=True)
        parts = df["hdb_symbol"].str.split(".", n=1, expand=True)
        df["hdb_symbol"] = parts[1].str.cat(parts[0], sep=".")

    # local_time 字段转换为 datetime
    df = normalize_datetime_column(df, column="local_time", inplace=True)

    return df


def _convert_symbols(
    df: pd.DataFrame,
    symbol_mapping: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    转换 hdb_symbol 为标准 symbol。

    转换策略根据 settings.ricequant.enabled 配置决定：
    - enabled=True: 使用 RiceQuant API (rqdatac.id_convert) 进行转换
    - enabled=False: 使用通用转换函数 (convert_symbol)

    Args:
        df: 包含 hdb_symbol 列的 DataFrame
        symbol_mapping: 外部提供的 hdb_symbol -> symbol 映射。如果为 None，使用全局 symbol_cache

    Returns:
        添加了 symbol 列的 DataFrame
    """
    processed_df = df.copy()
    unique_symbols = processed_df["hdb_symbol"].unique()

    # 确定使用的映射字典
    mapping = symbol_mapping if symbol_mapping is not None else symbol_cache
    missing_symbols = [s for s in unique_symbols if s not in mapping]

    # 批量转换缺失的 symbols
    if missing_symbols:
        if settings.ricequant.enabled:
            # 方式 1: 使用 RiceQuant API
            if _rq_convert_func is None:
                raise RuntimeError(
                    "RiceQuant converter is not initialized but enabled in settings."
                )

            try:
                converted_list = _rq_convert_func(missing_symbols)
                for original, converted in zip(missing_symbols, converted_list, strict=True):
                    mapping[original] = converted
            except Exception as e:
                log.warning(f"Failed to convert symbols via RiceQuant: {e}. Using original.")
                for s in missing_symbols:
                    mapping[s] = s
        else:
            # 方式 2: 使用通用转换函数 (目前是壳函数)
            log.info("RiceQuant disabled, using convert_symbol for symbol conversion")
            try:
                for symbol in missing_symbols:
                    converted = convert_symbol(
                        source_symbol=symbol,
                        source_provider="gtja",
                        target_provider="standard",
                    )
                    mapping[symbol] = converted
            except Exception as e:
                log.warning(f"Failed to convert symbols via convert_symbol: {e}. Using original.")
                for s in missing_symbols:
                    mapping[s] = s

    current_mapping = {s: mapping[s] for s in unique_symbols if s in mapping}
    processed_df["symbol"] = processed_df["hdb_symbol"].map(current_mapping)
    return processed_df


# ============================================================================
# 日线数据 ETL
# ============================================================================


def read_day_bar_from_local(
    db_path: str, year: int, symbols: list[str] | None = None
) -> pd.DataFrame:
    """
    从本地 HDB 文件中读取日线数据。

    Args:
        db_path: HDB 数据库的根目录 (例如 "E:/data/bar/day_bar")
        year: 年份 (例如 2005)
        symbols: 要读取的标的代码列表，None 表示所有代码

    Returns:
        包含日线数据的 DataFrame
    """
    db = hdb.DB(db_path)
    file_path = f"day_bar_{year}"
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else []  # [] 表示所有代码

    df = _read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    hdb_file.close()
    return df


def read_day_bar_from_parquet(
    parquet_path: str, date: datetime | str | int, symbols: list[str] | None = None
) -> pd.DataFrame:
    """
    从本地 Parquet 文件中读取日线数据。

    Args:
        parquet_path: Parquet 文件根目录 (例如 "E:/data/bar/day_bar")
        date: 日期，支持多种格式 (datetime, "2024-01-01", 20240101)
        symbols: 要筛选的标的代码列表，None 表示不筛选

    Returns:
        包含日线数据的 DataFrame
    """
    date_str = normalize_date_string(date)
    file_path = f"{parquet_path}/day_bar_{date_str}.parquet"

    try:
        df = pd.read_parquet(file_path, engine="pyarrow")
        df = normalize_datetime_column(df, column="local_time", inplace=True)

        # 如果指定了 symbols，进行筛选
        if symbols is not None and "hdb_symbol" in df.columns:
            df = df.loc[df["hdb_symbol"].isin(symbols)]

        return df

    except FileNotFoundError as e:
        raise FileNotFoundError(f"Parquet file not found: {file_path}") from e
    except Exception as e:
        raise Exception(f"Failed to read Parquet file {file_path}: {e}") from e  # pylint: disable=W0719


def prepare_day_bar_for_db(
    df: pd.DataFrame,
    symbol_mapping: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    准备 HDB 日线数据用于导入 ClickHouse bars_1d 表。

    处理流程:
        1. Symbol 转换 (hdb_symbol -> symbol)
        2. 价格字段缩放 (除以 10000)
        3. 字段重命名
        4. 添加 provider 标识
        5. 添加 trading_status (从 is_halt 映射)

    Args:
        df: 原始 HDB 日线 DataFrame (来自 read_day_bar_from_local)
        symbol_mapping: hdb_symbol -> symbol 的映射字典。如果为 None，使用全局 symbol_cache

    Returns:
        符合 bars_1d 表结构的 DataFrame
    """
    # 1. Symbol 转换
    processed_df = _convert_symbols(df, symbol_mapping)

    # 2. 价格字段缩放 (除以 10000)
    price_columns = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "pre_settle_price",
        "settle_price",
        "high_limited",  # 涨停价
        "low_limited",  # 跌停价
    ]
    for col in price_columns:
        if col in processed_df.columns:
            processed_df[col] = processed_df[col].astype(float) / 10000.0

    # 3. 数值字段类型转换
    if "volume" in processed_df.columns:
        processed_df["volume"] = processed_df["volume"].astype(float)
    if "turnover" in processed_df.columns:
        processed_df["turnover"] = processed_df["turnover"].astype(float)
    if "open_interest" in processed_df.columns:
        processed_df["open_interest"] = processed_df["open_interest"].astype(float)

    # 4. 重命名列以匹配 ClickHouse Schema
    processed_df = processed_df.rename(
        columns={
            "date": "dt",
            "turnover": "amount",
            "settle_price": "settle",
            "pre_settle_price": "pre_settle",
        }
    )

    # 5. 日期类型转换
    if "dt" in processed_df.columns:
        processed_df["dt"] = pd.to_datetime(processed_df["dt"].astype(str)).dt.date

    # 6. 添加数据源标识
    processed_df["provider"] = "gtja"

    # 7. 添加 trading_status (从 is_halt 映射)
    if "is_halt" in processed_df.columns:
        processed_df["trading_status"] = (
            processed_df["is_halt"].map({0: "NORMAL", 1: "HALTED"}).fillna("UNKNOWN")
        )
    else:
        processed_df["trading_status"] = "UNKNOWN"

    # 8. 映射 limit_up 和 limit_down
    if "high_limited" in processed_df.columns:
        processed_df["limit_up"] = processed_df["high_limited"]
    else:
        processed_df["limit_up"] = 0.0

    if "low_limited" in processed_df.columns:
        processed_df["limit_down"] = processed_df["low_limited"]
    else:
        processed_df["limit_down"] = 0.0

    # 9. 选择输出列 (与 bars_1d 表结构匹配)
    output_columns = [
        "symbol",
        "dt",
        "pre_close",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "pre_settle",
        "limit_up",
        "limit_down",
        "trading_status",
        "provider",
    ]

    available_cols = [c for c in output_columns if c in processed_df.columns]
    result = processed_df.loc[:, available_cols]
    return result


# ============================================================================
# 分钟线数据 ETL
# ============================================================================


def read_min_bar_from_local(
    db_path: str, trade_date: datetime | str, symbols: list[str] | None = None
) -> pd.DataFrame:
    """
    从本地 HDB 文件中读取指定日期的分钟线数据。

    Args:
        db_path: HDB 数据库的根目录 (例如 "E:/data/bar/min_bar")
        trade_date: 要读取的交易日期，支持 datetime 对象或字符串格式 (如 "2005-01-04" 或 "20050104")
        symbols: 要读取的标的代码列表。默认为 None, 表示所有代码

    Returns:
        包含分钟线数据的 DataFrame
    """
    date_str = normalize_date_string(trade_date)
    file_path = f"min_bar_{date_str}"

    db = hdb.DB(db_path)
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else []

    df = _read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    hdb_file.close()
    return df


def prepare_min_bar_for_db(df: pd.DataFrame) -> pd.DataFrame:
    """
    准备 HDB 分钟线数据用于导入 ClickHouse。

    字段逻辑：
    - dt: Date 类型，用于 ClickHouse 分区
    - bar_time: DateTime 类型，完整的时间戳
    - local_time: DateTime64 类型，高精度时间戳

    Args:
        df: 原始 HDB 分钟线 DataFrame (来自 read_min_bar_from_local)

    Returns:
        符合 ClickHouse 表结构的 DataFrame
    """
    if _rq_convert_func is None:
        raise RuntimeError("RiceQuant converter is not initialized.")

    # 1. Symbol 转换（使用全局 cache）
    processed_df = _convert_symbols(df, symbol_mapping=None)

    # 2. 价格字段缩放 (除以 10000)
    price_columns = [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "pre_settle_price",
        "settle_price",
    ]
    processed_df[price_columns] = processed_df[price_columns].astype(float) / 10000.0

    # 3. volume 和 turnover 类型转换
    processed_df["volume"] = processed_df["volume"].astype(float)
    processed_df["turnover"] = processed_df["turnover"].astype(float)

    # 4. 构建 bar_time (合并 date 和 time)
    if "date" in processed_df.columns and "time" in processed_df.columns:
        date_str = processed_df["date"].astype(str)
        time_str = processed_df["time"].astype(str).str.zfill(4)
        processed_df["bar_time"] = pd.to_datetime(date_str + time_str, format="%Y%m%d%H%M")

    # 5. 时间字段 (time) 处理：将 int (如 900) 转换为标准字符串 "HH:mm:ss"
    if "time" in processed_df.columns:
        processed_df["time"] = (
            processed_df["time"]
            .astype(str)
            .str.zfill(4)
            .str.replace(r"(\d{2})(\d{2})", r"\1:\2:00", regex=True)
        )

    # 6. 重命名列以匹配 ClickHouse Schema
    processed_df = processed_df.rename(
        columns={
            "date": "dt",
            "turnover": "amount",
            "settle_price": "settle",
            "pre_settle_price": "pre_settle",
        }
    )

    # 7. 添加数据源标识
    processed_df["provider"] = "gtja"

    # 8. 处理日期类型
    processed_df["dt"] = pd.to_datetime(processed_df["dt"].astype(str)).dt.date

    # 9. 选择最终输出列
    final_columns = [
        "symbol",
        "dt",
        "bar_time",
        "pre_close",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "pre_settle",
        "local_time",
        "provider",
    ]

    available_cols = [c for c in final_columns if c in processed_df.columns]
    return processed_df.loc[:, available_cols]


# ============================================================================
# 辅助工具
# ============================================================================


def read_codeinfo_from_hdb_file(hdb_file: Any) -> pd.DataFrame:
    """
    从 HDB 文件中提取代码信息。

    Args:
        hdb_file: 已打开的 HDB 文件对象

    Returns:
        包含代码信息的 DataFrame
    """
    codeinfo_df = pd.DataFrame()
    if hdb_file.codetable.data is not None and len(hdb_file.codetable.data) > 0:
        ci_data = hdb_file.ci_type.items_data(hdb_file.codetable.data)
        codeinfo_df = pd.DataFrame(ci_data)

        # 解码 sec_name
        if "sec_name" in codeinfo_df.columns:
            try:
                codeinfo_df["sec_name"] = codeinfo_df["sec_name"].apply(lambda x: x.decode("gbk"))
            except (UnicodeDecodeError, AttributeError):
                codeinfo_df["sec_name"] = codeinfo_df["sec_name"].apply(
                    lambda x: x.decode("utf-8", errors="ignore") if isinstance(x, bytes) else x
                )

        if "sec_name_ext" in codeinfo_df.columns:
            try:
                codeinfo_df["sec_name_ext"] = codeinfo_df["sec_name_ext"].apply(
                    lambda x: x.decode("gbk")
                )
            except (UnicodeDecodeError, AttributeError):
                codeinfo_df["sec_name_ext"] = codeinfo_df["sec_name_ext"].apply(
                    lambda x: x.decode("utf-8", errors="ignore") if isinstance(x, bytes) else x
                )

        # 添加 hdb_symbol
        codeinfo_df["hdb_symbol"] = hdb_file.codetable.symbols

    return codeinfo_df
