"""
# -*- coding: utf-8 -*-
读入期权头寸
期权组合情景分析
参数配置模块，这个模块可以修改
# Author: QiuZihua
# Date: 2025-08-16
"""

# 可以用函数读入数据
# 也可以直接在这里修改参数

import pandas as pd


def read_position(filepath=None):
    """
    读入期权头寸
    :param filepath: 期权头寸文件路径
    :return:
    """
    if filepath is not None:
        df = pd.read_excel(filepath)
    else:
        # 期权持仓组合
        positions = [
            {  # 第一个头寸
                "position_type": "call",  # 期权类型：call=认购，put=认沽
                "strike": 50,  # 行权价格
                "premium": 2.5,  # 权利金（期权价格）
                "direction": "short",  # 方向：long=多头，short=空头
                "quantity": 10000,  # 持仓数量（手数）
                "days_to_expiry": 30,  # 剩余到期天数
                "multiplier": 100,  # 期权乘数，用于计算期权价值
            }
            # {   # 第二个头寸：认沽期权空头
            #     "position_type": "put",
            #     "strike": 50,
            #     "premium": 1.8,
            #     "direction": "long",
            #     "quantity": 100,
            #     "days_to_expiry": 30,
            #     "multiplier": 100
            # },
            # {   # 第三个头寸：认购期权多头
            #     "position_type": "call",
            #     "strike": 50,
            #     "premium": 2.5,
            #     "direction": "long",
            #     "quantity": 100,
            #     "days_to_expiry": 30,
            #     "multiplier": 100
            # },
        ]

        # 标的资产头寸
        underlying_position = {
            "direction": "long",  # 方向：long=多头，short=空头
            "quantity": 0,  # 标的资产持仓数量（手数）
            "price": 48.5,  # 标的资产当前价格
            "multiplier": 1,  # 乘数，用于计算名义价值
        }

        # 市场参数配置
        market_params = {
            "S0": 51,  # 标的资产当前价格
            "r": 0.03,  # 无风险利率（年化）
            "q": 0.02,  # 股息率（年化）
            "v0": 0.2,  # 初始波动率（Heston模型参数）
            "kappa": 1.5,  # 均值回归速率（Heston模型）
            "theta": 0.2,  # 长期波动率水平（Heston模型）
            "sigma_v": 0.3,  # 波动率的波动率（Heston模型）
            "rho": -0.6,  # 标的资产价格与波动率的相关系数
        }

        df = {
            "positions": positions,
            "underlying_position": underlying_position,
            "market_params": market_params,
        }

    return df
