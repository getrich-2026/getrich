# pyright: reportMissingParameterType=false
"""
# -*- coding: utf-8 -*-
从AKShare获取宏观数据
Author: QiuZihua
Date: 2025/08/01
"""

import akshare as ak
import pandas as pd


# 1. 获取中国宏观杠杆率
def get_macro_leverage() -> pd.DataFrame:
    """
    获取中国宏观杠杆率
    :return:
    """
    df: pd.DataFrame = ak.macro_cnbs()
    return df


# 2. 获取企业商品价格指数
def get_macro_price_index() -> pd.DataFrame:
    """
    获取企业商品价格指数
    :return:
    """
    df: pd.DataFrame = ak.macro_china_qyspjg()
    return df


# 3. 获取LPR利率
def get_macro_lpr() -> pd.DataFrame:
    """
    获取LPR利率
    :return:
    """
    df: pd.DataFrame = ak.macro_china_lpr()
    return df


# 4. 获取调查城镇失业率
def get_macro_unemployment() -> pd.DataFrame:
    """
    获取调查城镇失业率
    :return:
    """
    df: pd.DataFrame = ak.macro_china_urban_unemployment()
    return df


# 5. 获取社会融资规模增量统计
def get_macro_shrz() -> pd.DataFrame:
    """
    获取社会融资规模增量统计
    :return:
    """
    df: pd.DataFrame = ak.macro_china_shrzgm()
    return df


# 6. 获取月度CPI报告
def get_macro_cpi_monthly() -> pd.DataFrame:
    """
    获取月度CPI报告
    :return:
    """
    df: pd.DataFrame = ak.macro_china_cpi_monthly()
    return df


# 7. 能源指数
def get_macro_energy() -> pd.DataFrame:
    """
    获取能源指数
    :return:
    """
    df: pd.DataFrame = ak.macro_china_energy_index()
    return df


# 8. 获取大宗商品价格
def get_macro_commodity() -> pd.DataFrame:
    """
    获取大宗商品价格
    :return:
    """
    df: pd.DataFrame = ak.macro_china_commodity_price_index()
    return df


# 9. 新增信贷数据
def get_macro_credit() -> pd.DataFrame:
    """
    获取新增信贷数据
    :return:
    """
    df: pd.DataFrame = ak.macro_china_new_financial_credit()
    return df


if __name__ == "__main__":
    # print(get_macro_leverage())
    # print(get_macro_price_index())
    # print(get_macro_lpr())
    # print(get_macro_unemployment())
    # print(get_macro_cpi_monthly())
    # print(get_macro_shrz())
    # print(get_macro_energy())
    # print(get_macro_commodity())
    print(get_macro_credit())
