# pylint: disable=no-member
# pylint: disable=w0719, E0401
# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
from __future__ import annotations

from datetime import datetime

import hdb
import pandas as pd


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


def read_hdb_baseinfo_from_local(db_path: str, date: str) -> pd.DataFrame:
    """
    从本地 HDB 文件中读取指定日期的证券信息（baseinfo/SecurityInfo_YYYYMMDD）

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/data/base_info")。
        date (str): 要读取的日期，格式为 "YYYYMMDD"
    Returns:
        pd.DataFrame: 包含证券信息的 DataFrame。
    """
    from datetime import datetime
    db = hdb.DB(db_path)
    hdb_file = db.open_file(f"SecurityInfo_{date}", mode="r")
    ci_data = hdb_file.ci_type.items_data(hdb_file.codetable.data)
    df = pd.DataFrame(ci_data)
    df['dt'] = pd.to_datetime(date).strftime('%Y-%m-%d')
    df = df[['dt','EXCHMARKET_ANN_CODE', 'INFO_NAME_NATIONAL', 'INFO_FULLNAME', 'SECURITYTYPE',
             'INFO_EXCHANGE_ENG', 'INFO_EXCHANGE', 'MIN_PRC_CHG_UNIT', 'INFO_UNITPERLOT',
             'INFO_LISTDATE','INFO_DELISTDATE','INFO_LISTPRICE','INFO_LISTBOARDNAME','TRADING_STATUS']]
    for column in df.columns:
        if df[column].apply(lambda x: isinstance(x, bytes)).any():
            df[column] = df[column].apply(lambda x: x.decode('gbk') if isinstance(x, bytes) else x)

    df = df.rename(columns={'EXCHMARKET_ANN_CODE': 'symbol', 'INFO_NAME_NATIONAL': 'asset_name', 'INFO_FULLNAME': 'full_asset_name',
                            'SECURITYTYPE': 'asset_type', 'INFO_EXCHANGE_ENG': 'exchange_eng', 'INFO_EXCHANGE': 'exchange',
                            'MIN_PRC_CHG_UNIT': 'min_price_chg_unit', 'INFO_UNITPERLOT': 'unit_per_lot', 'INFO_LISTDATE': 'list_date',
                            'INFO_DELISTDATE': 'delist_date', 'INFO_LISTPRICE': 'list_price', 'INFO_LISTBOARDNAME': 'list_board_name', 'TRADING_STATUS': 'trading_status'})

    hdb_file.close()
    df=(df[df['trading_status']!=0])
    return df










if __name__ == "__main__":
    # 使用示例
    # 请根据您的实际路径修改
    from lntools import Logger

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
