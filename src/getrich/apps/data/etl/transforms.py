# pylint: disable=no-member
# pyright: reportAttributeAccessIssue=false
"""
Transform functions for market data processing.

该模块包含数据转换函数，用于计算衍生字段。

Functions:
    - compute_adj_factor: 计算复权因子和复权价格
    - compute_pct_chg: 计算涨跌幅 (简单收益率 & 对数收益率)
    - transform_day_bar: 日线数据转换主入口

Usage:
    >>> from getrich.apps.data.etl.hdb import read_day_bar_from_local
    >>> from getrich.apps.data.etl.transforms import transform_day_bar
    >>>
    >>> df_raw = read_day_bar_from_local(...)
    >>> df_clean = transform_day_bar(df_raw, compute_adj=True)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


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
        # 1. 按 symbol 分组，日期 降序 (DESC) 排列 (最新日期在最前)
        # 2. 这样 "下一日 PreClose" 就变成了 "上一行 PreClose" (shift(1))
        # 3. 直接 cumprod 累乘，无需 reverse

        df = df.sort_values(["symbol", "dt"], ascending=[True, False])

        # 获取 T+1 日的 PreClose (因为是倒序，所以是 shift(1))
        next_pre_close = df.groupby("symbol")["pre_close_safe"].shift(1)

        # 计算比价因子: Ratio = PreClose(T+1) / Close(T)
        # 最新一天的 next_pre_close 是 NaN，fillna(1.0) 保证基准为 1
        ratio = (next_pre_close / df["close_safe"]).fillna(1.0)

        # 累乘计算因子
        # 注意: groupby().cumprod() 会保留索引，直接赋值即可
        # 如果 ratio 是 Series，需要先 groupby 再 cumprod 以防跨 symbol 累乘
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

    # 2. 计算复权因子和复权价格
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
