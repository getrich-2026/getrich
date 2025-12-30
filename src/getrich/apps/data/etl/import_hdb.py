from __future__ import annotations

from datetime import datetime

import hdb
import pandas as pd
from lntools import Logger

from getrich.apps.data.etl.transforms import normalize_date_string, normalize_datetime_column

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

    # local_time 字段转换为 datetime (复用 transforms 中的标准化函数)
    df = normalize_datetime_column(df, column="local_time", inplace=True)
    df.rename(columns={"symbol": "hdb_symbol"}, inplace=True)

    # 转换 hdb_symbol 格式: "xx.yyyyyy" -> "yyyyyy.xx"
    if "hdb_symbol" in df.columns:
        parts = df["hdb_symbol"].str.split(".", n=1, expand=True)
        # df["hdb_symbol"] = parts[1] + "." + parts[0]
        df["hdb_symbol"] = parts[1].str.cat(parts[0], sep=".")

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
    date_str = normalize_date_string(date)
    file_path = f"{parquet_path}/day_bar_{date_str}.parquet"

    try:
        # 使用 engine='pyarrow' 以获得更好的性能
        df = pd.read_parquet(file_path, engine="pyarrow")

        # 标准化时间列 (支持任何数据源: HDB, Wind, RiceQuant 等)
        df = normalize_datetime_column(df, column="local_time", inplace=True)

        return df

    except FileNotFoundError as e:
        raise FileNotFoundError(f"Parquet file not found: {file_path}") from e
    except Exception as e:
        raise Exception(f"Failed to read Parquet file {file_path}: {e}") from e  # pylint: disable=W0719


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
        # 添加 hdb_symbol
        codeinfo_df["hdb_symbol"] = hdb_file.codetable.symbols
    return codeinfo_df


def read_min_bar_from_local(
    db_path: str, trade_date: datetime | str, symbols: list[str] | None = None
) -> pd.DataFrame:
    """
    从本地 HDB 文件中读取指定日期的分钟线数据和代码信息。

    Args:
        db_path (str): HDB 数据库的根目录 (例如 "E:/data/bar/min_bar")。
        trade_date (datetime | str): 要读取的交易日期，支持 datetime 对象或字符串格式 (如 "2005-01-04" 或 "20050104")。
        symbols (list[str], optional): 要读取的标的代码列表。默认为 None, 表示所有代码。

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: 包含分钟线数据和代码信息的两个 DataFrame。
    """
    # 使用通用函数统一转换日期格式
    date_str = normalize_date_string(trade_date)
    file_path = f"min_bar_{date_str}"

    db = hdb.DB(db_path)
    hdb_file = db.open_file(file_path, mode="r")
    symbols = symbols if symbols is not None else []

    # 1. 读取分钟 K 线数据
    df = read_hdb_to_df(hdb_file, symbols=symbols, data_type="SecurityKdata")

    # 2. 读取代码信息
    # codeinfo_df = _read_codeinfo_from_hdb_file(hdb_file)

    hdb_file.close()
    return df


def read_baseinfo_from_local_all(db_path: str = r"Z:\hdb_data\baseinfo") -> pd.DataFrame:
    """
    读取所有历史的基础信息，并保留每个 hdb_symbol 最新的记录。
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

            secinfo_df = secinfo_df[["hdb_symbol"] + available_cols].rename(columns=required_cols)

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
                        codeinfo_df = codeinfo_df[["hdb_symbol"] + available_tick_cols].rename(
                            columns=tick_cols
                        )
                        # Inner merge: 只有两者都有的 hdb_symbol 才保留
                        secinfo_df = pd.merge(secinfo_df, codeinfo_df, on="hdb_symbol", how="inner")
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

    # 保留每个 hdb_symbol 的第一条记录（因为是按时间倒序读取的，所以第一条就是最新的）
    final_df = full_df.drop_duplicates(subset=["hdb_symbol"], keep="first")

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
            secinfo_df["hdb_symbol"] = hdb_file.codetable.symbols
    except Exception as e:
        log.error(f"Error reading secinfo from hdb file: {e}")
        return pd.DataFrame()

    return secinfo_df


# 全局缓存：用于存储 hdb_symbol 到 symbol 的映射关系，避免循环处理时重复调用转换接口
_SYMBOL_CACHE = {}


def process_hdb_df(df: pd.DataFrame):
    """
    处理原始 DataFrame 以符合 ClickHouse 存储要求。

    参数:
    df: 原始 pandas.DataFrame
    """
    try:
        import rqdatac as rq

        from getrich.apps.data.etl.ricequant import init_rq

        init_rq()
        rq_convert_func = rq.id_convert  # pylint: disable=E1101
    except ImportError:
        log.error("rqdatac is not installed; Please install the 'rqdatac' package.")
        raise

    # 深度拷贝一份数据以免修改原始 df
    processed_df = df.copy()

    # 1. hdb_symbol 转换成 symbol (增加批量缓存机制)
    # global _SYMBOL_CACHE
    unique_symbols = processed_df["hdb_symbol"].unique()

    # 找出当前 df 中尚未进入缓存的 symbol
    missing_symbols = [s for s in unique_symbols if s not in _SYMBOL_CACHE]

    if missing_symbols:
        try:
            # 使用列表输入进行批量转换
            converted_list = rq_convert_func(missing_symbols)
            # 将结果更新至全局缓存
            for original, converted in zip(missing_symbols, converted_list, strict=True):
                _SYMBOL_CACHE[original] = converted
        except Exception as e:
            log.warning(
                f"Failed to convert symbols in bulk: {e}. Falling back to iterative conversion."
            )
            # 如果批量转换失败，尝试逐个转换作为兜底
            for s in missing_symbols:
                try:
                    _SYMBOL_CACHE[s] = rq_convert_func(s)
                except Exception:
                    _SYMBOL_CACHE[s] = s

    # 使用全局缓存进行映射
    processed_df["symbol"] = processed_df["hdb_symbol"].map(_SYMBOL_CACHE)

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

    # 3. volume 和 turnover 缩放 (除以 100000000)
    processed_df["volume"] = processed_df["volume"].astype(float) / 100000000.0
    processed_df["turnover"] = processed_df["turnover"].astype(float) / 100000000.0

    # 4. 重命名列
    processed_df = processed_df.rename(
        columns={
            "date": "dt",
            "time": "ts",
            "turnover": "amount",
            "settle_price": "settle",
            "pre_settle_price": "pre_settle",
        }
    )

    # 5. 增加 source 字段
    processed_df["source"] = "gtja"

    # 6. 处理 date 字段
    processed_df["dt"] = pd.to_datetime(processed_df["dt"].astype(str)).dt.date

    # 7. 整理最终列顺序
    final_columns = [
        "dt",
        "ts",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "open_interest",
        "pre_close",
        "pre_settle",
        "settle",
        "local_time",
        "source",
    ]

    # 只保留需要的列
    processed_df = processed_df[final_columns]

    return processed_df


if __name__ == "__main__":
    df = read_min_bar_from_local(db_path=r"E:\data\hdb", trade_date="20251229")
    df = process_hdb_df(df)
    print(df.info())
