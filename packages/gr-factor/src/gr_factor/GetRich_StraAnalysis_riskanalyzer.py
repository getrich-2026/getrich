# ================
# 风险分析模块
# Author: QiuZihua
# Date: 2025-08-16
# ================


import GetRich_StraAnalysis_scenario as scenario
import numpy as np
import pandas as pd
import scipy.stats as stats


class RiskAnalyzer:
    """风险指标计算类"""

    def calculate_var(self, pnl_series: pd.Series, confidence_level: float = 0.95) -> float:
        """_summary_
        计算Value at Risk (VaR)
        Args:
            pnl_series (pd.Series): 盈亏序列
            confidence_level (float): 置信水平，默认95%
        Returns:
            float: VaR值
        """
        return np.percentile(pnl_series, 100 * (1 - confidence_level))

    def stress_test(self, analyzer: scenario.ScenarioAnalyzer, days: int = 3) -> dict:
        """_summary_

        Args:
            analyzer (scenario.ScenarioAnalyzer): 情景分析引擎
            days (int, optional): 压力测试的天数，也就是几天后的情景，这里默认是3.

        Returns:
            Dict: 包含风险指标结果的字典
        """
        scenarios = {
            "市场崩盘(升波暴跌)": {"price_change": -0.3, "vol_change": 1},  # 市场崩溃,波动率大涨
            "波动率飙升(升波价冷)": {"price_change": 0, "vol_change": 0.6},  # 波动率飙升,价格上涨
            "动物性市场(升波暴涨)": {
                "price_change": 0.3,
                "vol_change": 1.0,
            },  # 情绪性上涨,价格上涨,波动率上涨
            #    'market_recovery': {'price_change': 0.2, 'vol_change': -0.3}, # 市场恢复,波动率下降
            #    'volatility_cliff': {'price_change': 0.1, 'vol_change': 0.8}, # 波动率悬崖,价格上涨
        }
        results = {}
        for name, params in scenarios.items():
            # 计算新参数
            new_S = analyzer.market_params["S0"] * (1 + params["price_change"])  # 新的标的资产价格
            new_vol = analyzer.market_params["v0"] * (1 + params["vol_change"])  # 新的波动率
            T = analyzer.opt_positions[0]["days_to_expiry"] / 365 - days / 365  # 新的剩余到期时间
            result = analyzer._calculate_position_pnl(new_S, new_vol, T)
            # 记录结果
            results[name] = result["pnl"]
        return results

    def calculate_stats(self, df: pd.DataFrame) -> dict:
        """_summary_
        计算风险指标统计信息
        Args:
            df (pd.DataFrame): 情景分析结果DataFrame
        Returns:
            Dict: 包含风险指标统计信息的字典
        """
        return {
            "mean": df["pnl"].mean(),
            "std": df["pnl"].std(),
            "skewness": stats.skew(df["pnl"]),  # 偏度(衡量分布不对称性)
            "kurtosis": stats.kurtosis(df["pnl"]),  # 峰度(衡量分布尖峰程度)
            "var_95": RiskAnalyzer.calculate_var(df["pnl"], 0.95),
            "max_loss": df["pnl"].min(),  # 最大亏损
            "max_gain": df["pnl"].max(),  # 最大盈利
        }


# import QAnalysis_opt_position as p
# params = p.read_position()
# results = RiskAnalyzer.stress_test(
#     analyzer=scenario.ScenarioAnalyzer(
#         params["positions"], params["underlying_position"], params["market_params"]
#     )
# )
