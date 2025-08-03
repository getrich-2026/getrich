"""
从akshare获取公募基金数据
Author: QiuZiHua
Date: 2025/08/01
"""
import akshare as ak
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# 1. 获取公募基金数据
def get_fund_name_em():
    """
    获取公募基金数据
    """
    df = ak.fund_name_em()
    return df


# 2. ETF基金实时行情-东财
def get_etf_realtime_em():
    """
    获取ETF基金实时行情-东财
    """
    df = ak.fund_etf_spot_em()
    return df

# 3. ETF基金实时行情-同花顺
def get_etf_realtime_ths(date):
    """
    获取ETF基金实时行情-同花顺
    """
    df = ak.fund_etf_spot_ths(date=date )
    return df


# 4. ETF基金分时行情-东财
def get_etf_minute_em(symbol, start_date, end_date, period, adjust):
    """
    获取ETF基金分时行情-东财
    symbol	str	symbol='513500'; ETF 代码可以在 get_etf_realtime_em中获取
    start_date	str	start_date="1979-09-01 09:32:00"; 日期时间; 默认返回所有数据
    end_date	str	end_date="2222-01-01 09:32:00"; 日期时间; 默认返回所有数据
    period	str	period='5'; choice of {'1', '5', '15', '30', '60'}; 其中 1 分钟数据返回近 5 个交易日数据且不复权
    adjust	str	adjust=''; choice of {'', 'qfq', 'hfq'}; '': 不复权, 'qfq': 前复权, 'hfq': 后复权, 其中 1 分钟数据返回近 5 个交易日数据且不复权
    """
    df = ak.fund_etf_hist_min_em(symbol=symbol, period=period, adjust=adjust, start_date=start_date, end_date=end_date)
    return df

# 5. 获取基金历史净值数据-东财
def get_fund_history_em(symbol, start_date, end_date, period, adjust):
    """
    获取基金历史净值数据-东财
    symbol	str	symbol='159707'; ETF 代码可以在 get_etf_realtime_em中获取或查看东财主页
    period	str	period='daily'; choice of {'daily', 'weekly', 'monthly'}
    start_date	str	start_date='20000101'; 开始查询的日期
    end_date	str	end_date='20230104'; 结束查询的日期
    adjust	str	默认返回不复权的数据; qfq: 返回前复权后的数据; hfq: 返回后复权后的数据
    """
    df = ak.fund_etf_hist_em(symbol=symbol, start_date=start_date, end_date=end_date)
    return df

# 6. 获取开放式基金历史数据
def get_fund_open_history(symbol, indicator, period):
    """
    获取开放式基金历史数据
    symbol	str	symbol="710001"; 需要基金代码,通过get_fund_open_realtime()获取
    period    str    period="成立来"; 该参数只对 累计收益率走势 有效, choice of {"1月", "3月", "6月", "1年", "3年", "5年", "今年来", "成立来"}
    indicator	str	indicator="单位净值走势"; 参见 :
    参数名称	备注
    单位净值走势	-
    累计净值走势	-
    累计收益率走势	-
    同类排名走势	-
    同类排名百分比	-
    分红送配详情	-
    拆分详情	-
    period	str	period="成立来"; 该参数只对 累计收益率走势 有效, choice of {"1月", "3月", "6月", "1年", "3年", "5年", "今年来", "成立来"}
    """
    df = ak.fund_open_fund_info_em(symbol=symbol, period=period, indicator=indicator)
    return df

# 7. 获取开放式基金实时数据
def get_fund_open_realtime():
    """
    获取开放式基金实时数据
    symbol    str    symbol="710001"; 需要基金代码
    """
    df = ak.fund_open_fund_daily_em()
    return df


# 8. 获取开放式基金排名
def get_fund_open_rank(symbol):
    """
    获取开放式基金排名
    symbol="全部"; choice of {"全部", "股票型", "混合型", "债券型", "指数型", "QDII", "FOF"}
    """
    df = ak.fund_open_fund_rank_em()
    return df


if __name__ == '__main__':
    # print(get_fund_name_em())
    # print(get_etf_realtime_em())
    # print(get_etf_realtime_ths(date='2021-08-01'))
    # print(get_etf_minute_em(symbol='513500', start_date='2021-08-01', end_date='2021-08-01', period='5', adjust=''))
    # print(get_fund_history_em(symbol='159707', start_date='20000101', end_date='20230104', period='daily', adjust='hfq'))