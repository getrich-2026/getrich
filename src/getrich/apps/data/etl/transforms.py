# pylint: disable=no-member
# pyright: reportAttributeAccessIssue=false
from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd
from lntools.utils import Logger

log = Logger(module_name="ETLTransforms")

# ============================================================================
# Generic Data Utilities (可被任何数据源复用)
# ============================================================================


def normalize_date_string(date: datetime.datetime | str | int) -> str:
    """
    统一日期格式为 YYYYMMDD 字符串。

    适用场景: 任何需要文件名或路径中使用日期的场景 (HDB, CSV, Parquet 等)。

    Args:
        date: 日期，支持 datetime 对象、字符串格式或整数格式

    Returns:
        str: YYYYMMDD 格式的日期字符串

    Example:
        >>> normalize_date_string(datetime.datetime(2024, 1, 15))
        '20240115'
        >>> normalize_date_string("2024-01-15")
        '20240115'
        >>> normalize_date_string(20240115)
        '20240115'
    """
    if isinstance(date, datetime.datetime):
        return date.strftime("%Y%m%d")
    elif isinstance(date, int):
        return str(date)
    else:
        # 移除可能的分隔符
        return str(date).replace("-", "").replace("/", "")


def normalize_datetime_column(
    df: pd.DataFrame,
    column: str = "local_time",
    timezone: str = "Asia/Shanghai",
    inplace: bool = False,
) -> pd.DataFrame:
    """
    标准化 DataFrame 中的时间列，确保其为指定时区的 datetime 类型。

    适用场景: 任何包含时间戳的市场数据 (行情、tick、分钟线等)。

    Args:
        df: 输入的 DataFrame
        column: 时间列名，默认为 'local_time'
        timezone: 目标时区，默认为 'Asia/Shanghai'
        inplace: 是否原地修改，默认 False

    Returns:
        pd.DataFrame: 处理后的 DataFrame

    Example:
        >>> df = pd.DataFrame({'local_time': [1704038400000, 1704124800000]})
        >>> df = normalize_datetime_column(df)
        >>> df['local_time'].dtype
        dtype('<M8[ns]')
    """
    if not inplace:
        df = df.copy()

    if column not in df.columns:
        return df

    # 如果是时间戳格式 (整数类型)
    if pd.api.types.is_integer_dtype(df[column]):
        df[column] = (
            pd.to_datetime(df[column], unit="ms", utc=True)
            .dt.tz_convert(timezone)
            .dt.tz_localize(None)
        )
    # 如果是字符串格式
    elif pd.api.types.is_string_dtype(df[column]):
        df[column] = pd.to_datetime(df[column])
        # 如果已有时区信息，转换到目标时区
        if df[column].dt.tz is not None:
            df[column] = df[column].dt.tz_convert(timezone).dt.tz_localize(None)
    # 如果已是 datetime 但带时区
    elif pd.api.types.is_datetime64_any_dtype(df[column]) and df[column].dt.tz is not None:
        df[column] = df[column].dt.tz_convert(timezone).dt.tz_localize(None)

    return df


def convert_symbol(
    source_symbol: str,
    source_provider: str = "gtja",
    target_provider: str = "ricequant",
) -> str:
    """
    通用 symbol 转换函数（跨数据源代码映射）。

    适用场景: 将不同数据源的 symbol 格式进行标准化转换。
    例如: HDB (国泰君安) 的 "SH600000" 转换为 RiceQuant 的 "600000.XSHG"

    Args:
        source_symbol: 原始 symbol 代码
        source_provider: 源数据提供商 (如 "gtja", "wind", "tushare")
        target_provider: 目标数据提供商 (如 "ricequant", "standard")

    Returns:
        转换后的 symbol 代码

    Note:
        这是一个占位函数，实际转换逻辑需要根据业务需求实现。
        可能的实现方式：
        1. 基于正则表达式的规则转换
        2. 查询数据库中的映射表
        3. 调用第三方 API (如 rqdatac.id_convert)

    Example:
        >>> convert_symbol("600000.SH", source_provider="gtja")
        "600000.XSHG"  # 转换为 RiceQuant 格式
    """
    # TODO: 实现不同数据源的 symbol 转换逻辑
    # 当前返回原 symbol，等待后续补充实现
    log.warning(
        f"Symbol conversion not implemented: {source_symbol} "
        f"({source_provider} -> {target_provider}), returning original"
    )
    return source_symbol


# ============================================================================
# Date & String Cleaning Utilities
# ============================================================================

# ClickHouse Date 类型的默认值（用于无效日期）
DEFAULT_DATE = datetime.date(1970, 1, 1)
# 需要替换为默认值的无效日期字符串
INVALID_DATE_STRINGS = frozenset({"0000-00-00", "None", "NaT", "nan", "null", ""})

# ClickHouse Date 类型的有效范围
CLICKHOUSE_DATE_MIN = pd.Timestamp("1970-01-01")
CLICKHOUSE_DATE_MAX = pd.Timestamp("2149-06-06")


def convert_date_value(
    val: Any,
    default: datetime.date = DEFAULT_DATE,
    warn_on_error: bool = False,
) -> datetime.date:
    """
    将单个日期值转换为 datetime.date 对象。

    支持的输入类型:
        - datetime.date / datetime.datetime
        - pd.Timestamp
        - str (格式: 'YYYY-MM-DD', 'YYYY/MM/DD', 'YYYYMMDD')
        - None / NaN / NaT

    Args:
        val: 待转换的日期值
        default: 无效值返回的默认日期，默认为 1970-01-01
        warn_on_error: 是否在转换失败时打印警告，默认 False

    Returns:
        datetime.date 对象，无效值返回 default

    Example:
        >>> convert_date_value("2024-01-15")
        datetime.date(2024, 1, 15)
        >>> convert_date_value("0000-00-00")
        datetime.date(1970, 1, 1)
        >>> convert_date_value(None)
        datetime.date(1970, 1, 1)
    """
    # None, NaN, NaT 统一处理
    if val is None:
        return default

    # 使用 pd.isna() 统一检查 NaN/NaT (支持 float NaN, pd.NaT, np.nan 等)
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        # 某些类型不支持 pd.isna，继续处理
        pass

    # 已经是 date 类型（排除 datetime）
    if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
        return val

    # datetime 类型
    if isinstance(val, datetime.datetime):
        return val.date()

    # pd.Timestamp 类型
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return default
        return val.date()

    # 字符串类型
    if isinstance(val, str):
        val = val.strip()
        # 无效日期字符串
        if not val or val in INVALID_DATE_STRINGS:
            return default
        # 尝试多种格式
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.datetime.strptime(val, fmt).date()
            except ValueError:
                continue
        if warn_on_error:
            log.warning(f"Cannot parse date string: '{val}', using default")
        return default

    # 未知类型，尝试通过 pd.Timestamp 转换
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return default
        return ts.date()
    except Exception:
        if warn_on_error:
            log.warning(f"Cannot convert value to date: {val} (type={type(val).__name__})")
        return default


def clean_date_columns(
    df: pd.DataFrame,
    date_columns: list[str] | None = None,
    default: datetime.date = DEFAULT_DATE,
    inplace: bool = False,
) -> pd.DataFrame:
    """
    清洗 DataFrame 中的日期列，将其转换为 datetime64[ns] 类型。

    Args:
        df: 原始 DataFrame
        date_columns: 日期列名列表。如果为 None，自动识别列名包含 'date' 的列
        default: 无效值使用的默认日期，默认为 1970-01-01
        inplace: 是否原地修改，默认 False

    Returns:
        清洗后的 DataFrame

    Note:
        - 自动识别规则: 列名包含 'date' 但不包含 'updated_at'
        - 输出列的 dtype 为 datetime64[ns]，而非 object
        - ClickHouse 驱动会自动将 datetime64 转换为 Date 类型
    """
    if not inplace:
        df = df.copy()

    # 自动识别日期列
    if date_columns is None:
        date_columns = [
            c for c in df.columns if "date" in c.lower() and "updated_at" not in c.lower()
        ]

    default_ts = pd.Timestamp(default)

    for col in date_columns:
        if col not in df.columns:
            continue

        # 预处理：将无效字符串替换为 None（pd.to_datetime 会将其转为 NaT）
        # 这样可以处理 '0000-00-00' 等 pd.to_datetime 无法解析的值
        df[col] = df[col].apply(
            lambda x: None if (isinstance(x, str) and x.strip() in INVALID_DATE_STRINGS) else x
        )

        # 使用 pd.to_datetime 批量转换，errors='coerce' 将无效值转为 NaT
        df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")

        # 填充 NaT 为默认日期
        df[col] = df[col].fillna(default_ts)

    return df


def clean_string_columns(
    df: pd.DataFrame,
    exclude_columns: list[str] | None = None,
    fill_value: str = "",
    inplace: bool = False,
) -> pd.DataFrame:
    """
    清洗 DataFrame 中的字符串列，将 NaN 填充为指定值。

    Args:
        df: 原始 DataFrame
        exclude_columns: 需要排除的列名列表（如日期列）
        fill_value: NaN 填充值，默认为空字符串
        inplace: 是否原地修改，默认 False

    Returns:
        清洗后的 DataFrame

    Note:
        - 仅处理 object 类型的列
        - 解决 ClickHouse 插入时 "object of type 'float' has no len()" 错误
    """
    if not inplace:
        df = df.copy()

    exclude_columns = exclude_columns or []
    obj_cols = df.select_dtypes(include=["object"]).columns.tolist()

    for col in obj_cols:
        if col not in exclude_columns:
            df[col] = df[col].fillna(fill_value).astype(str)

    return df


def clean_dataframe_for_clickhouse(
    df: pd.DataFrame,
    date_columns: list[str] | None = None,
    default_date: datetime.date = DEFAULT_DATE,
) -> pd.DataFrame:
    """
    清洗 DataFrame 使其适合插入 ClickHouse。

    处理内容:
        1. 字符串列: 填充 NaN 为空字符串
        2. 日期列: 转换为 datetime64[ns]，无效值使用默认日期
        3. 日期范围: 超出 ClickHouse Date 范围 (1970-01-01 ~ 2149-06-06) 的值替换为默认日期

    Args:
        df: 原始 DataFrame
        date_columns: 日期列名列表。如果为 None，自动识别
        default_date: 无效日期的默认值，默认为 1970-01-01

    Returns:
        清洗后的 DataFrame（副本）
    """
    df = df.copy()

    # 识别日期列
    if date_columns is None:
        date_columns = [
            c for c in df.columns if "date" in c.lower() and "updated_at" not in c.lower()
        ]

    # 清洗字符串列（排除日期列）
    df = clean_string_columns(df, exclude_columns=date_columns, inplace=True)

    # 清洗日期列
    df = clean_date_columns(df, date_columns=date_columns, default=default_date, inplace=True)

    # ClickHouse Date 类型范围限制: 将超出范围的日期替换为默认值
    default_ts = pd.Timestamp(default_date)
    for col in date_columns:
        if col in df.columns:
            df[col] = df[col].where(
                (df[col] >= CLICKHOUSE_DATE_MIN) & (df[col] <= CLICKHOUSE_DATE_MAX),
                default_ts,
            )

    return df


# ============================================================================
# Market Data Transforms
# ============================================================================


def compute_adj_factor(
    df: pd.DataFrame,
    method: str = "forward",
    compute_adj_price: bool = False,
) -> pd.DataFrame:
    """
    计算复权因子，可选生成复权价格。

    原理:
        前复权 (forward): 以最新日期为基准 (adj_factor=1)，向前递推。
        公式: adj_factor[t] = adj_factor[t+1] * (pre_close[t+1] / close[t])
        当 pre_close[t+1] != close[t] 时，说明发生除权事件。

    Args:
        df: 包含 OHLC 数据的 DataFrame，必须包含字段:
            - symbol: 标的代码
            - dt: 日期 (Date 类型)
            - open, high, low, close: 原始价格
            - pre_close: 前收盘价 (用于检测除权)
        method: 复权方式
            - "forward": 前复权 (默认，以最新日为基准)
            - "backward": 后复权 (以最早日为基准)
        compute_adj_price: 是否生成复权价格字段，默认 False
            - True: 额外生成 adj_open, adj_high, adj_low, adj_close
            - False: 只生成 adj_factor，复权价格可在查询时动态计算

    Returns:
        pd.DataFrame: 原始数据 + 新增字段:
            - adj_factor: 复权因子 (始终生成)
            - adj_open, adj_high, adj_low, adj_close: 复权价格 (仅当 compute_adj_price=True)

    Example:
        >>> df = pd.DataFrame({
        ...     "symbol": ["000001.SZ"] * 3,
        ...     "dt": [date(2023,1,1), date(2023,1,2), date(2023,1,3)],
        ...     "open": [10.0, 10.5, 9.0],
        ...     "high": [10.5, 11.0, 9.5],
        ...     "low": [9.5, 10.0, 8.5],
        ...     "close": [10.2, 10.8, 9.2],
        ...     "pre_close": [10.0, 10.2, 9.0],  # 1/3 发生除权: 9.0 != 10.8
        ... })
        >>> result = compute_adj_factor(df, method="forward")  # 只返回 adj_factor
        >>> result = compute_adj_factor(df, compute_adj_price=True)  # 返回 adj_factor + adj_ohlc

    Note:
        - 数据必须按 (symbol, dt) 排序，函数内部会自动排序
        - 对于 pre_close == 0 或 close == 0 的异常数据，adj_factor 设为 1.0
        - 推荐只存储 adj_factor，复权价格在 SQL 查询时动态计算: close * adj_factor
    """
    # 复制以避免修改原始数据
    df = df.copy()

    # 1. 预处理: 确保没有 0 值导致除零错误 (Close 为 0 通常是异常或停牌，设为 NaN 不参与计算)
    # 使用 1e-6 避免浮点数比较问题
    df["close_safe"] = np.where(df["close"] > 1e-6, df["close"], np.nan)
    df["pre_close_safe"] = np.where(df["pre_close"] > 1e-6, df["pre_close"], np.nan)

    if method == "forward":
        # 前复权:
        # 以最新日期为基准 (adj_factor=1)，除权前的价格需要向下调整
        # 1. 按 symbol 分组，日期 降序 (DESC) 排列 (最新日期在最前)
        # 2. 这样 "下一日 PreClose" 就变成了 "上一行 PreClose" (shift(1))
        # 3. 直接 cumprod 累乘，无需 reverse

        df = df.sort_values(["symbol", "dt"], ascending=[True, False])

        # 获取 T+1 日的 PreClose (因为是倒序，所以是 shift(1))
        next_pre_close = df.groupby("symbol")["pre_close_safe"].shift(1)

        # 计算比价因子: Ratio = PreClose(T+1) / Close(T)
        # 当发生除权时 (pre_close[t+1] != close[t])，ratio < 1，使除权前价格向下调整
        # 最新一天的 next_pre_close 是 NaN，fillna(1.0) 保证基准为 1
        ratio = (next_pre_close / df["close_safe"]).fillna(1.0)

        # 累乘计算因子
        df["adj_factor"] = ratio.groupby(df["symbol"]).cumprod()

    elif method == "backward":
        # 后复权：
        # 1. 按 symbol 分组，日期 升序 (ASC) 排列
        # 2. Ratio = Close(T-1) / PreClose(T)

        df = df.sort_values(["symbol", "dt"], ascending=[True, True])

        # 获取 T-1 日的 Close
        prev_close = df.groupby("symbol")["close_safe"].shift(1)

        # Ratio = Close(T-1) / PreClose(T)
        ratio = (prev_close / df["pre_close_safe"]).fillna(1.0)

        # 累乘
        df["adj_factor"] = ratio.groupby(df["symbol"]).cumprod()

    else:
        raise ValueError(f"Invalid method: {method}. Use 'forward' or 'backward'.")

    # 2. 清理临时列并恢复默认排序
    if "close_safe" in df.columns:
        del df["close_safe"]
    if "pre_close_safe" in df.columns:
        del df["pre_close_safe"]

    # 恢复按日期升序
    df = df.sort_values(["symbol", "dt"], ascending=[True, True]).reset_index(drop=True)

    # 3. 可选：计算复权价格 (保留4位小数)
    if compute_adj_price:
        for col in ["open", "high", "low", "close"]:
            df[f"adj_{col}"] = (df[col] * df["adj_factor"]).round(4)

    return df


def compute_pct_chg(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算涨跌幅 (简单收益率和对数收益率)。

    Args:
        df: 包含 close 和 pre_close 字段的 DataFrame

    Returns:
        pd.DataFrame: 原始数据 + 新增字段:
            - pct_chg: 简单涨跌幅 (close / pre_close - 1)
            - pct_chg_log: 对数收益率 ln(close / pre_close)

    Note:
        - pre_close <= 0 时，涨跌幅设为 0
    """
    df = df.copy()

    # 简单涨跌幅
    df["pct_chg"] = np.where(
        df["pre_close"] > 0,
        (df["close"] / df["pre_close"] - 1).round(6),
        0.0,
    )

    # 对数收益率
    df["pct_chg_log"] = np.where(
        (df["pre_close"] > 0) & (df["close"] > 0),
        np.log(df["close"] / df["pre_close"]).round(6),
        0.0,
    )

    return df


def compute_amplitude(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算振幅。

    Args:
        df: 包含 high, low, pre_close 字段的 DataFrame

    Returns:
        pd.DataFrame: 原始数据 + 新增字段:
            - amplitude: 振幅 (high - low) / pre_close * 100

    Note:
        - pre_close <= 0 时，振幅设为 0
    """
    df = df.copy()

    # 计算振幅: (high - low) / pre_close * 100
    df["amplitude"] = np.where(
        df["pre_close"] > 0,
        ((df["high"] - df["low"]) / df["pre_close"] * 100).round(4),
        0.0,
    )

    return df


def transform_day_bar(
    df: pd.DataFrame,
    compute_adj: bool = True,
    adj_method: str = "forward",
) -> pd.DataFrame:
    """
    日线数据 Transform 主函数: 计算复权因子、涨跌幅等衍生字段。

    这是导入日线数据时应调用的主入口函数，封装了所有衍生字段计算逻辑。

    Args:
        df: 原始日线数据，必须包含字段:
            symbol, dt, open, high, low, close, pre_close, volume, amount
        compute_adj: 是否计算复权因子和复权价格，默认 True
        adj_method: 复权方式 ("forward" 或 "backward")

    Returns:
        pd.DataFrame: 包含所有衍生字段的 DataFrame，可直接写入 ClickHouse

    Example:
        >>> # 在导入任务中使用
        >>> from getrich.apps.data.etl.hdb import read_day_bar_from_local
        >>> df_raw = read_day_bar_from_local(...)  # Extract
        >>> df_clean = transform_day_bar(df_raw)   # Transform
        >>> clickhouse.insert("market_data.bars_1d", df_clean)  # Load
    """
    # 1. 计算涨跌幅
    result = compute_pct_chg(df)

    # 2. 计算振幅
    result = compute_amplitude(result)

    # 3. 计算复权因子和复权价格
    if compute_adj:
        result = compute_adj_factor(result, method=adj_method)

    return result


# =============================================================================
# Minimal Reproducible Example (MRE)
# =============================================================================
if __name__ == "__main__":
    from datetime import date

    print("=" * 60)
    print("Testing transforms.py - Adjustment Factor Calculation")
    print("=" * 60)

    # 构造测试数据: 模拟 1/3 发生 10送10 除权 (股价减半)
    test_df = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 5,
            "dt": [
                date(2023, 1, 1),
                date(2023, 1, 2),
                date(2023, 1, 3),
                date(2023, 1, 4),
                date(2023, 1, 5),
            ],
            "open": [10.0, 10.5, 5.2, 5.3, 5.4],
            "high": [10.5, 11.0, 5.5, 5.6, 5.7],
            "low": [9.5, 10.0, 5.0, 5.1, 5.2],
            "close": [10.2, 10.8, 5.3, 5.4, 5.5],
            # 1/3 pre_close=5.4, 但 1/2 close=10.8, 说明 1/3 发生除权
            "pre_close": [10.0, 10.2, 5.4, 5.3, 5.4],
            "volume": [1000.0] * 5,
            "amount": [10000.0] * 5,
        }
    )
    print("\n[Input] Raw test data:")
    print(test_df)

    # 计算复权因子
    result_df = transform_day_bar(test_df, compute_adj=True, adj_method="forward")
    print("\n[Output] After transform (with adj_factor):")
    print(result_df[["symbol", "dt", "close", "pre_close", "pct_chg", "adj_factor"]])

    # 验证
    assert result_df["adj_factor"].iloc[0] < 1.0, "adj_factor before ex-date should be < 1"
    assert abs(result_df["adj_factor"].iloc[4] - 1.0) < 0.001, "Latest adj_factor should be 1.0"

    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
