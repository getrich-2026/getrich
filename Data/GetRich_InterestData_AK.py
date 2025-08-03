"""
从akshare获取利率数据
Author: QiuZiHua
Date: 2025/08/01
"""

import akshare as ak
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 1. 银行间同业拆借利率
def get_bank_interest(marekt, symbol, indicator):
    """
    获取银行间同业拆借利率
    market	str	market="上海银行同业拆借市场"; 参见 市场-品种-指标一览表
    symbol	str	symbol="Shibor人民币"; 参见 市场-品种-指标一览表
    indicator	str	indicator="隔夜"; 参见 市场-品种-指标一览表
    """
    df = ak.rate_interbank(market=marekt, symbol=symbol, indicator=indicator)
    return df


# 2. 回购定盘利率-历史
def get_repo_rate_hist(start_date, end_date):
    """
    获取回购定盘利率-历史, 一年内
    start_date    str    开始日期
    end_date    str    结束日期
    """
    df= ak.repo_rate_hist(start_date=start_date, end_date=end_date)
    return df

# 3. 回购定盘利率-近期
def get_repo_rate(symbol):
    """
    获取回购定盘利率-近期
    symbol    str    symbol="回购定盘利率"; choice of {"回购定盘利率", "银银间回购定盘利率"}
    """
    df = ak.repo_rate_query(symbol=symbol)
    return df