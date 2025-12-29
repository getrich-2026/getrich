# pylint: disable=no-member
# pylint: disable=w0719, E0401
# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
from __future__ import annotations

from datetime import datetime

import hdb
import pandas as pd
from lntools import Logger

log = Logger(module_name="HdbEtl")


def read_hdb_to_df(
    hdb_file,  # type: ignore
    symbols: list[str],
    data_type: str,
    begin: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """
    从 HDB 文件中读取指定数据并转换为 Pandas DataFrame。

    Args:
        hdb_file (hdb.File): 已打开的 HDB 文件对象。
        symbols (list[str]): 要读取的标的代码列表，支持通配符 (如 "SH.600*")。
        data_type (str): 要读取的数据类型 (如 "SecurityTick", "SecurityKdata")。
        begin (datetime, optional): 开始时间。默认为 None。
        end (datetime, optional): 结束时间。默认为 None。

    Returns:
        pd.DataFrame: 包含所读取数据的 DataFrame,  如果无数据则返回空的 DataFrame。
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
    df = process_data_to_df(data_type_def, data, items)

    return df


def process_data_to_df(data_type_def, data, items) -> pd.DataFrame:  # type: ignore
    df = pd.DataFrame()

    # 将 hdb 数据结构扁平化到 dataframe
    for name in data_type_def.dtype.fields:
        field_type = data.dtype.fields[name][0]
        if field_type.ndim == 0:
            df[name] = data[name]
        elif field_type.ndim == 1:
            for idx in range(field_type.shape[0]):
                df[f"{name}{idx}"] = data[name][:, idx]

    # 添加公共字段
    for col in ["symbol", "local_time"]:
        if col in items.dtype.names:
            df[col] = pd.Series(items[col])

    # symbol 字段解码
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].apply(lambda x: x.decode("utf-8"))

    # local_time 字段转换为 datetime
    if "local_time" in df.columns:
        df["local_time"] = (
            pd.to_datetime(df["local_time"], unit="ms", utc=True)
            .dt.tz_convert("Asia/Shanghai")
            .dt.tz_localize(None)
        )

    return df


def read_day_bar_from_local(
    db_path: str, year: int, symbols: list[str] | None = None
) -> pd.DataFrame:
    """
    从本地 HDB 文件中读取日线数据和代码信息。

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/data/bar/day_bar")。
        year (int): 年份 (例如 2005)。
        symbols (list[str], optional): 要读取的标的代码列表

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: 包含日线数据和代码信息的两个 DataFrame。
    """
    db = hdb.DB(db_path)
    file_path = f"day_bar_{year}"
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else []  # []，表示所有代码。

    # 1. 读取日 K 线数据
    df = read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    hdb_file.close()
    return df


def read_day_bar_from_csv(csv_path: str, date: datetime | str | int) -> pd.DataFrame:
    """
    从本地 CSV 文件中读取日线数据。

    Args:
        csv_path (str): CSV 文件根目录 (例如 "E:/data/bar/day_bar")。
        date (datetime | str | int): 日期，支持多种格式:
            - datetime 对象
            - 字符串格式 (如 "2024-01-01" 或 "20240101")
            - 整数格式 (如 20240101)

    Returns:
        pd.DataFrame: 包含日线数据的 DataFrame
    """
    # 统一转换为文件名格式：day_bar_YYYYMMDD.csv
    if isinstance(date, datetime):
        date_str = date.strftime("%Y%m%d")
    elif isinstance(date, int):
        date_str = str(date)
    else:
        # 移除可能的分隔符
        date_str = str(date).replace("-", "").replace("/", "")

    file_path = f"{csv_path}/day_bar_{date_str}.csv"

    try:
        # 读取 CSV 文件
        df = pd.read_csv(file_path)

        # 处理 local_time 字段（如果存在）
        if "local_time" in df.columns:
            # 如果是时间戳格式
            if pd.api.types.is_integer_dtype(df["local_time"]):
                df["local_time"] = (
                    pd.to_datetime(df["local_time"], unit="ms", utc=True)
                    .dt.tz_convert("Asia/Shanghai")
                    .dt.tz_localize(None)
                )
            # 如果是字符串格式
            elif pd.api.types.is_string_dtype(df["local_time"]):
                df["local_time"] = pd.to_datetime(df["local_time"])

        return df

    except FileNotFoundError as e:
        raise FileNotFoundError(f"CSV file not found: {file_path}") from e
    except Exception as e:
        raise Exception(f"Failed to read CSV file {file_path}: {e}") from e


def read_day_bar_from_parquet(parquet_path: str, date: datetime | str | int) -> pd.DataFrame:
    """
    从本地 Parquet 文件中读取日线数据。

    Args:
        parquet_path (str): Parquet 文件根目录 (例如 "E:/data/bar/day_bar")。
        date (datetime | str | int): 日期，支持多种格式:
            - datetime 对象
            - 字符串格式 (如 "2024-01-01" 或 "20240101")
            - 整数格式 (如 20240101)

    Returns:
        pd.DataFrame: 包含日线数据的 DataFrame
    """
    # 统一转换为文件名格式：day_bar_YYYYMMDD.parquet
    if isinstance(date, datetime):
        date_str = date.strftime("%Y%m%d")
    elif isinstance(date, int):
        date_str = str(date)
    else:
        # 移除可能的分隔符
        date_str = str(date).replace("-", "").replace("/", "")

    file_path = f"{parquet_path}/day_bar_{date_str}.parquet"

    try:
        # 读取 Parquet 文件
        df = pd.read_parquet(file_path)

        # 处理 local_time 字段（如果存在）
        if "local_time" in df.columns:
            # 如果是时间戳格式
            if pd.api.types.is_integer_dtype(df["local_time"]):
                df["local_time"] = (
                    pd.to_datetime(df["local_time"], unit="ms", utc=True)
                    .dt.tz_convert("Asia/Shanghai")
                    .dt.tz_localize(None)
                )
            # 如果是字符串格式
            elif pd.api.types.is_string_dtype(df["local_time"]):
                df["local_time"] = pd.to_datetime(df["local_time"])

        return df

    except FileNotFoundError as e:
        raise FileNotFoundError(f"Parquet file not found: {file_path}") from e
    except Exception as e:
        raise Exception(f"Failed to read Parquet file {file_path}: {e}") from e


def _read_codeinfo_from_hdb_file(hdb_file) -> pd.DataFrame:  # type: ignore
    """从 HDB 文件中提取代码信息。"""
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
        # 添加 symbol
        codeinfo_df["symbol"] = hdb_file.codetable.symbols
    return codeinfo_df


def read_min_bar_from_local(
    db_path: str, trade_date: datetime | str, symbols: list[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    从本地 HDB 文件中读取指定日期的分钟线数据和代码信息。

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/data/bar/min_bar")。
        trade_date (datetime | str): 要读取的交易日期，支持 datetime 对象或字符串格式 (如 "2005-01-04" 或 "20050104")。
        symbols (list[str], optional): 要读取的标的代码列表。默认为 None, 表示所有代码。

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: 包含分钟线数据和代码信息的两个 DataFrame。
    """
    # 统一转换为文件名格式：min_bar_YYYYMMDD
    if isinstance(trade_date, datetime):
        date_str = trade_date.strftime("%Y%m%d")
    else:
        # 移除可能的分隔符
        date_str = str(trade_date).replace("-", "").replace("/", "")

    file_path = f"min_bar_{date_str}"

    db = hdb.DB(db_path)
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else []

    # 1. 读取分钟 K 线数据
    df = read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    # 2. 读取代码信息
    codeinfo_df = _read_codeinfo_from_hdb_file(hdb_file)

    hdb_file.close()
    return df, codeinfo_df


def read_baseinfo_from_local_all(db_path: str = r"Z:\hdb_data\baseinfo") -> pd.DataFrame:
    """
    读取所有历史的基础信息，并保留每个 symbol 最新的记录。
    """
    try:
        db = hdb.DB(db_path)
        files = db.get_file_names(sub_folder="")
    except Exception as e:
        log.error(f"Failed to open baseinfo DB at {db_path}: {e}")
        return pd.DataFrame()

    # 按时间倒序排列，这样最新的数据在前面
    files = sorted(files, reverse=True)

    try:
        tick_db = hdb.DB(r"Z:\hdb_data\marketdata")
    except Exception as e:
        log.error(f"Failed to open tick DB: {e}")
        return pd.DataFrame()

    all_dfs = []

    for f in files:
        log.info(f"Processing {f}...")
        date_str = f[-8:]

        secinfo_file = None
        tick_file = None

        try:
            secinfo_file = db.open_file(f, mode="r")
            secinfo_df = _read_secinfo_from_hdb_file(secinfo_file)

            if secinfo_df.empty:
                continue

            # 筛选需要的列
            required_cols = {
                "EXCHMARKET_ANN_CODE": "symbol_raw",
                "INFO_EXCHANGE_ENG": "exchange",
                "INFO_FULLNAME": "name",
                "SECURITYTYPE": "type",
                "CRNCY_CODE": "currency",
                "INFO_LISTDATE": "listed_date",
                "INFO_DELISTDATE": "delisted_date",
            }

            # 检查列是否存在
            available_cols = [c for c in required_cols if c in secinfo_df.columns]
            if not available_cols:
                continue

            secinfo_df = secinfo_df[["symbol"] + available_cols].rename(columns=required_cols)

            # 读取 tick 库中的补充信息
            try:
                tick_file = tick_db.open_file(f"tick_{date_str}", mode="r")
                codeinfo_df = _read_codeinfo_from_hdb_file(tick_file)

                if not codeinfo_df.empty:
                    tick_cols = {
                        "multiplier": "multiplier",
                        "margin_ratio": "margin_ratio",
                        "price_tick": "min_movement",
                        "margin_ratio_param1": "margin_ratio_param1",
                        "margin_ratio_param2": "margin_ratio_param2",
                    }

                    available_tick_cols = [c for c in tick_cols if c in codeinfo_df.columns]
                    if available_tick_cols:
                        codeinfo_df = codeinfo_df[["symbol"] + available_tick_cols].rename(
                            columns=tick_cols
                        )
                        # Inner merge: 只有两者都有的 symbol 才保留
                        secinfo_df = pd.merge(secinfo_df, codeinfo_df, on="symbol", how="inner")
            except Exception as e:
                log.warning(f"Failed to read tick info for {date_str}: {e}")
                # 如果读取 tick 失败，跳过这一天的合并
                continue

            if not secinfo_df.empty:
                all_dfs.append(secinfo_df)

        except Exception as e:
            log.error(f"Error processing file {f}: {e}")
            continue
        finally:
            if secinfo_file:
                secinfo_file.close()
            if tick_file:
                tick_file.close()

    if not all_dfs:
        return pd.DataFrame()

    log.info(f"Concatenating {len(all_dfs)} dataframes...")
    full_df = pd.concat(all_dfs, ignore_index=True)

    # 保留每个 symbol 的第一条记录（因为是按时间倒序读取的，所以第一条就是最新的）
    final_df = full_df.drop_duplicates(subset=["symbol"], keep="first")

    log.info(f"Finished processing baseinfo. Total symbols: {len(final_df)}")
    return final_df


def _read_secinfo_from_hdb_file(hdb_file) -> pd.DataFrame:  # type: ignore
    """从 HDB 文件中提取代码信息。"""
    secinfo_df = pd.DataFrame()
    try:
        if hdb_file.codetable.data is not None and len(hdb_file.codetable.data) > 0:
            ci_data = hdb_file.ci_type.items_data(hdb_file.codetable.data)
            secinfo_df = pd.DataFrame(ci_data)
            # 只对 object 类型的列进行解码
            for col in secinfo_df.select_dtypes(include=["object"]).columns:
                secinfo_df[col] = secinfo_df[col].apply(
                    lambda x: x.decode("gbk", errors="ignore") if isinstance(x, bytes) else x
                )
            secinfo_df["symbol"] = hdb_file.codetable.symbols
    except Exception as e:
        log.error(f"Error reading secinfo from hdb file: {e}")
        return pd.DataFrame()

    return secinfo_df


if __name__ == "__main__":
    # 使用示例
    log = Logger("extract_main")
    #
    HDB_DATA_PATH = "E:\\data\\bar\\min_bar\\2023"
    log.info("Reading minute K-line data for 2023-01-04...")
    min_bar_df, codeinfo_df = read_min_bar_from_local(
        db_path=HDB_DATA_PATH, trade_date="20230104", symbols=None
    )

    if not min_bar_df.empty:
        log.info("\n--- Minute K-line data (MinBar) read successfully! ---")
        log.info("Data structure:")
        print(min_bar_df.head())
        log.info(f"\nTotal read {len(min_bar_df)} minute K-line records.")
        print(min_bar_df.info())
    else:
        log.info("Failed to read minute K-line data. Please check the path and file.")

    if not codeinfo_df.empty:
        log.info("\n--- Code information (CodeInfo) read successfully! ---")
        log.info("Data structure:")
        print(codeinfo_df.head())
        log.info(f"\nTotal read {len(codeinfo_df)} code info records.")
        print(codeinfo_df.info())
    else:
        log.info("Failed to read code information.")

    # HDB_DATA_PATH = "E:/data/bar/day_bar"
    # log.info("Reading daily K-line data for 2005...")
    # day_bar_df = read_day_bar_from_local(db_path=HDB_DATA_PATH, year=2024, symbols=None)
    # if not day_bar_df.empty:
    #     log.info("\n--- Daily K-line data read successfully! ---")
    #     log.info("Data structure：")
    #     print(day_bar_df.head())
    #     log.info(f"\nTotal daily K-line records read: {len(day_bar_df)}")
    #     print(day_bar_df.info())
    # else:
    #     log.info("Failed to read daily K-line data. Please check the path and files.")
