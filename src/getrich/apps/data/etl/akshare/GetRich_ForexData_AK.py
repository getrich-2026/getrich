# pyright: reportMissingParameterType=false
"""
从akshare获取外汇数据
Author: QiuZiHua
Date: 2025/08/01
"""

import warnings

import akshare as ak
import pandas as pd

warnings.filterwarnings("ignore")


# 1. 获取外汇实时报价
def get_forex_spot_em() -> pd.DataFrame:
    """
    获取外汇实时报价
    """
    df: pd.DataFrame = ak.forex_spot_em()
    return df


# 2. 获取外汇历史报价
def get_forex_hist(symbol: str) -> pd.DataFrame:
    """
    symbol="USDCNH"; 品种代码；可以通过 ak.forex_spot_em() 来获取所有可获取历史行情数据的品种代码
    """
    df: pd.DataFrame = ak.forex_hist_em(symbol=symbol)
    return df
