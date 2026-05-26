# pyright: reportMissingParameterType=false
"""
从AKShare获取债券数据
Author: QiuZiHua
Date: 2025/08/01
"""

import akshare as ak
import pandas as pd


# 1. 获取国债及其他债券收益率曲线
def get_bond_yield_curve(start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取国债及其他债券收益率曲线
    start_date="20190204", 指定开始日期; start_date 到 end_date 需要小于一年
    end_date="20200204", 指定结束日期; start_date 到 end_date 需要小于一年
    """
    df: pd.DataFrame = ak.bond_china_yield(start_date=start_date, end_date=end_date)
    return df


# 2. 获取指定可转债详情资料
def get_convertible_bond_info(symbol: str) -> pd.DataFrame:
    """
    获取可转债详情资料
    symbol = "sz128039"
    """
    df: pd.DataFrame = ak.bond_cb_profile_sina(symbol=symbol)
    return df


# 3. 获取可转债债券概况
def get_convertible_bond_profile(symbol: str) -> pd.DataFrame:
    """
    获取可转债债券概况
    symbol="sh155255"; 带市场标识的转债代码
    """
    df: pd.DataFrame = ak.bond_cb_summary_sina(symbol=symbol)
    return df


# 4. 获取可转债的实时行情数据
def get_convertible_bond_realtime() -> pd.DataFrame:
    """
    获取可转债的实时行情数据
    """
    df: pd.DataFrame = ak.bond_zh_hs_cov_spot()
    return df


# 5. 获取可转债历史行情数据
def get_convertible_bond_history(symbol: str) -> pd.DataFrame:
    """
    获取可转债历史行情数据
    symbol="sh113542"; 带市场标识的转债代码
    """
    df: pd.DataFrame = ak.bond_zh_hs_cov_daily(symbol=symbol)
    return df


# 6. 获取可转债历史行情数据-分时
def get_convertible_bond_history_minute(
    symbol: str, period: str, adjust: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """
    获取可转债历史行情数据-分时
    symbol	str	symbol='sz123106'; 转债代码
    period	str	period='5'; choice of {'1', '5', '15', '30', '60'}; 其中 1 分钟数据返回近 1 个交易日数据且不复权
    adjust	str	adjust=''; choice of {'', 'qfq', 'hfq'}; '': 不复权, 'qfq': 前复权, 'hfq': 后复权, 其中 1 分钟数据返回近 1 个交易日数据且不复权
    start_date	str	start_date="1979-09-01 09:32:00"; 日期时间; 默认返回所有数据
    end_date	str	end_date="2222-01-01 09:32:00"; 日期时间; 默认返回所有数据
    """
    df: pd.DataFrame = ak.bond_zh_hs_cov_min(
        symbol=symbol,
        period=period,
        adjust=adjust,
        start_date=start_date,
        end_date=end_date,
    )
    return df


# 7. 获取可转债历史行情数据-分时+盘前-东财
def get_convertible_bond_history_minute_em(symbol: str) -> pd.DataFrame:
    """
    获取可转债历史行情数据-分时+盘前-东财
    symbol    str    symbol='sz123106'; 转债代码
    """
    df: pd.DataFrame = ak.bond_zh_hs_cov_pre_min(symbol=symbol)
    return df


# 8. 可转债数据一览表
def get_convertible_bond_list() -> pd.DataFrame:
    """
    可转债数据一览表
    """
    df: pd.DataFrame = ak.bond_zh_cov()
    return df


# 9. 可转债详情-同花顺
def get_convertible_bond_info_ths() -> pd.DataFrame:
    """
    可转债详情-同花顺
    返货回一个DataFrame，所有的可转债信息
    """
    df: pd.DataFrame = ak.bond_zh_cov_info_ths()
    return df


# 10. 可转债比价表
def get_convertible_bond_price_comparison() -> pd.DataFrame:
    """
    可转债比价表
    """
    df: pd.DataFrame = ak.bond_cov_comparison()
    return df


# 11. 可转债价值分析-东财
def get_convertible_bond_value_analysis_em(symbol: str) -> pd.DataFrame:
    """
    可转债价值分析-东财
    symbol    str    symbol='113542'; 代码
    """
    df: pd.DataFrame = ak.bond_zh_cov_value_analysis(symbol=symbol)
    return df


# 12. 可转债溢价率分析-东财
def get_convertible_bond_ytm_analysis_em(symbol: str) -> pd.DataFrame:
    """
    可转债溢价率分析-东财
    symbol    str    symbol='113542'; 代码
    """
    df: pd.DataFrame = ak.bond_zh_cov_value_analysis(symbol=symbol)
    return df


# 13. 上海质押式国债回购利率-东财-当天
def get_bond_repo_sh_em() -> pd.DataFrame:
    """
    上海质押式国债回购利率-东财
    """
    df: pd.DataFrame = ak.bond_sh_buy_back_em()
    return df


# 14. 深交所质押式国债回购利率-东财-当天
def get_bond_repo_sz_em() -> pd.DataFrame:
    """
    深交所质押式国债回购利率-东财
    """
    df: pd.DataFrame = ak.bond_sz_buy_back_em()
    return df


# 15. 质押式回购历史数据-东财
def get_bond_repo_history_em(symbol: str) -> pd.DataFrame:
    """
    质押式回购历史数据-东财
    symbol    str    symbol='204001'; 代码
    """
    df: pd.DataFrame = ak.bond_buy_back_hist_em(symbol=symbol)
    return df


# 16. 中美国债收益率
def get_bond_yield_china_usa(start_date: str) -> pd.DataFrame:
    """
    中美国债收益率
    start_date    str    start_date="20190204"; 开始日期
    """
    df: pd.DataFrame = ak.bond_zh_us_rate(start_date=start_date)
    return df


# if __name__ == '__main__':
# print("GetRich_BondData_AK.py")
# print("1. 获取国债及其他债券收益率曲线")
# print(get_bond_yield_curve(start_date="20190204", end_date="20200204"))
# print("2. 获取指定可转债详情资料")
# print(get_convertible_bond_info(symbol="sz128039"))
# print("3. 获取可转债债券概况")
# print(get_convertible_bond_profile(symbol="sh155255"))
# print("4. 获取可转债的实时行情数据")
# print(get_convertible_bond_realtime())
# print("5. 获取可转债历史行情数据")
# print(get_convertible_bond_history(symbol="sh113542"))
# print("6. 获取可转债历史行情数据-分时")
# print(get_convertible_bond_history_minute(symbol='sz123124', period='5', adjust='', start_date='2025-08-01 09:32:00',
#       end_date='2025-08-01 15:00:00'))
# print("7. 获取可转债历史行情数据-分时+盘前-东财")
# print(get_convertible_bond_history_minute_em(symbol='sz123124'))
# print("8. 可转债数据一览表")
# # print(get_convertible_bond_list())
# print("9. 可转债详情-同花顺")
# print(get_convertible_bond_info_ths())
# print("10. 可转债比价表")
# print(get_convertible_bond_price_comparison())
# print("11. 可转债价值分析-东财")
# print(get_convertible_bond_value_analysis_em(symbol='113542'))
# print("12. 可转债溢价率分析-东财")
# print(get_convertible_bond_ytm_analysis_em(symbol='113542'))
# print("13. 上海质押式国债回购利率-东财")
# print(get_bond_repo_sh_em())
# print("14. 深交所质押式国债回购利率-东财")
# print(get_bond_repo_sz_em())
# print("15. 质押式回购历史数据-东财")
# print(get_bond_repo_history_em(symbol='204001'))
# print("16. 中美国债收益率")
# print(get_bond_yield_china_usa(start_date="20190204"))
