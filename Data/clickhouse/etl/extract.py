from __future__ import annotations

from datetime import datetime

import hdb
import pandas as pd


def read_hdb_to_df(
    hdb_file,
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


def process_data_to_df(
    data_type_def, data, items
) -> pd.DataFrame:
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
    for col in ["symbol", "trading_day", "local_time"]:
        if col in items.dtype.names:
            df[col] = items[col]

    # symbol 字段解码
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].apply(lambda x: x.decode("utf-8"))

    return df


def read_day_bar_from_local(
    db_path: str, year: int, symbols: list[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    从本地 HDB 文件中读取日线数据和代码信息。

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/BaiduNetdiskDownload/data/bar")。
        year (int): 年份 (例如 2005)。
        symbols (list[str], optional): 要读取的标的代码列表

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: 包含日线数据和代码信息的两个 DataFrame。
    """
    db = hdb.DB(db_path)  # type: ignore
    file_path = f"day_bar_{year}"
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else ["*"]  # ["*"]，表示所有代码。

    # 1. 读取日 K 线数据
    df = read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")
    # 2. 读取代码信息
    codeinfo_df = _read_codeinfo_from_hdb_file(hdb_file)
    hdb_file.close()
    return df, codeinfo_df


def _read_codeinfo_from_hdb_file(hdb_file) -> pd.DataFrame:
    """从 HDB 文件中提取代码信息。"""
    codeinfo_df = pd.DataFrame()
    if hdb_file.codetable.data is not None and len(hdb_file.codetable.data) > 0:
        ci_data = hdb_file.ci_type.items_data(hdb_file.codetable.data)
        codeinfo_df = pd.DataFrame(ci_data)
        # 解码 sec_name
        if "sec_name" in codeinfo_df.columns:
            try:
                codeinfo_df["sec_name"] = codeinfo_df["sec_name"].apply(
                    lambda x: x.decode("gbk")
                )
            except (UnicodeDecodeError, AttributeError):
                codeinfo_df["sec_name"] = codeinfo_df["sec_name"].apply(
                    lambda x: x.decode("utf-8", errors="ignore")
                    if isinstance(x, bytes)
                    else x
                )
        # 添加 symbol
        # codeinfo_df["symbol"] = [
        #     s.decode("utf-8") for s in hdb_file.codetable.symbols
        # ]
        codeinfo_df["symbol"] = hdb_file.codetable.symbols
    return codeinfo_df


def read_min_bar_from_local(
    db_path: str, file_path: str, symbols: list[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    从本地 HDB 文件中读取指定日期的分钟线数据和代码信息。

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/BaiduNetdiskDownload/data/min_bar")。
        trade_date (datetime): 要读取的交易日期。
        symbols (list[str], optional): 要读取的标的代码列表。默认为 None, 表示所有代码。

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: 包含分钟线数据和代码信息的两个 DataFrame。
    """
    db = hdb.DB(db_path)  # type: ignore
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else ["*"]

    # 1. 读取分钟 K 线数据
    df = read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    # 2. 读取代码信息
    codeinfo_df = _read_codeinfo_from_hdb_file(hdb_file)

    hdb_file.close()
    return df, codeinfo_df


if __name__ == "__main__":
    # 使用示例
    # 请根据您的实际路径修改
    from lntools import Logger
    log = Logger("extract_main")
    HDB_DATA_PATH = "E:\\BaiduNetdiskDownload\\data\\bar\\bar\\min_bar\\2025"
    #
    # 1. 读取 2025 年所有 A 股的日 K 线数据
    log.info("正在读取 2025 年日 K 线数据...")
    min_bar_df, codeinfo_df = read_min_bar_from_local(
        db_path=HDB_DATA_PATH, file_path="min_bar_20250919", symbols=["SH.*", "SZ.*"]
    )

    if not min_bar_df.empty:
        log.info("\n--- 日 K 线数据读取成功！ ---")
        log.info("数据结构：")
        # print(day_bar_2025_df.head())
        # print(f"\n总计读取 {len(day_bar_2025_df)} 条日 K 线数据。")
        print(min_bar_df.info())
    else:
        log.info("未能读取到日 K 线数据，请检查路径和文件是否正确。")

    if not codeinfo_df.empty:
        log.info("\n--- 代码信息 (CodeInfo) 读取成功！ ---")
        log.info("数据结构：")
        print(codeinfo_df.head())
        log.info(f"\n总计读取 {len(codeinfo_df)} 条代码信息。")
        print(codeinfo_df.info())
    else:
        log.info("未能读取到代码信息。")
