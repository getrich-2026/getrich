"""
从AKShare获取指数数据
Author: QiuZihua
Date: 2025/08/04
"""

import akshare as ak
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 1. A股股票指数-实时行情-东财
def get_index_spot_realtime_em(symbol):
    """
    获取A股股票指数-实时行情-东财
    """
    df = ak.index_stock_em()
    return df