# ====================
# 情景分析引擎类
# Author: QiuZihua
# Date: 2025-08-16
# ====================
from typing import List, Dict
import GetRich_StraAnalysis_pricer as pricer
import GetRich_StraAnalysis_HestonModel as HestonModel
import numpy as np
import pandas as pd

class ScenarioAnalyzer:
    """组合情景分析核心引擎"""
    def __init__(self, opt_positions:List[Dict], und_positions:Dict, market_params:Dict):
        """_summary_
        初始化情景分析引擎
        Args:
            opt_positions (List[Dict]): 期权组合头寸
            und_positions (Dict): 标的资产头寸
            market_params (Dict): 市场参数
        """
        self.opt_positions = opt_positions # 期权组合头寸
        self.und_positions = und_positions # 标的资产头寸
        self.market_params = market_params # 市场参数
        self.pricer = pricer.OptionPricer() # 期权定价器

    def _calculate_position_pnl(self, S:float, sigma:float, T:float) -> Dict:
        """_summary_
        计算组合的盈亏情况
        Args:
            S (float): 标的资产价格
            sigma (float): 波动率
            T (float): 剩余到期时间
        Returns:
            Dict: 期权组合的盈亏情况，以及希腊值的字典
        """
        total_pnl = 0.0 # 组合的盈亏情况
        greeks = {
            "delta_cash": 0.0,
            "gamma_cash": 0.0,
            "vega_cash": 0.0,
            "theta_cash": 0.0,
            } # 总的希腊值的字典
        # 遍历每个期权
        for pos in self.opt_positions:
            # 计算期权的价格
            price = self.pricer.black_scholes(
                S=S,
                K=pos["strike"],
                T=T,
                sigma=sigma,
                r=self.market_params["r"],
                q=self.market_params["q"],
                option_type=pos["position_type"]
            )
            # 计算当个头寸的盈亏（考虑头寸方向）
            pnl = (price - pos["premium"])*pos["quantity"]*pos["multiplier"]
            if pos["direction"] == "short":
                pnl *= -1 # 空头的盈亏为负数
            total_pnl += pnl # 累加总盈亏
            # 计算希腊值并汇总（考虑方向）
            greek, greekscash = self.pricer.calculate_greeks(
                S=S,
                K=pos["strike"],
                T=T,
                sigma=sigma,
                r=self.market_params["r"],
                q=self.market_params["q"],
                option_type=pos["position_type"],
                multiplier=pos["multiplier"]
            )
            direction = 1 if pos["direction"] == "long" else -1 # 多头为1，空头为-1
            for key in greeks:
                greeks[key]+= greekscash[key]*pos["quantity"]*direction
        # 计算标的资产的盈亏（考虑方向）
        und_pnl = (S - self.und_positions["price"])*self.und_positions["quantity"]*self.und_positions["multiplier"]
        if self.und_positions["direction"] == "short":
            und_pnl *= -1 # 空头的盈亏为负数
        total_pnl += und_pnl # 累加总盈亏
        greeks["delta_cash"] += und_pnl # 标的资产的delta为盈亏本身
        return {"pnl": total_pnl, "greeks": greeks}

    def _scenario_analysis(self, n_scenarios:int, days_later:int)->pd.DataFrame:
        """_summary_
        情景分析：n天后的，n个场景
        Args:
            n_scenarios (int): 模拟的场景数
            days_later (int): 几天后
        Returns:
            pd.DataFrame: 情景分析结果的DataFrame
        """
        # 模拟标的资产价格
        # 设置独立的随机种子（避免多进程重复）
        np.random.seed()
        # 生成随机参数变化
        price_changes = np.random.uniform(-0.2, 0.2, n_scenarios) # 未来几天价格变化-20%到20%
        vol_changes = np.random.uniform(-0.5, 1, n_scenarios) # 未来几天波动率变化-50%到翻倍
        # 初始化结果列表
        records = []
        for pc, vc in zip(price_changes, vol_changes):
            # 计算模拟的标的资产价格和波动率
            new_S = self.market_params["S0"] * (1 + pc) # 模拟的标的资产价格
            new_vol = self.market_params["v0"] * (1 + vc) # 模拟的波动率
            # 计算模拟的剩余到期时间
            new_T = max(self.opt_positions[0]["days_to_expiry"]/365 - days_later/365, 1/365) # 模拟的剩余到期时间
            # 计算情景下的总盈亏和希腊值
            result = self._calculate_position_pnl(
                S=new_S,
                sigma=new_vol,
                T=new_T
            )
            # 记录结果
            records.append({
                "price_change": pc,
                "vol_change": vc,
                "pnl": result["pnl"],
                **result["greeks"]
            })
        # 将结果转换为DataFrame
        df = pd.DataFrame(records)
        return df

    def daily_simulation_heston(self, n_paths:int=100, days:int=6)->pd.DataFrame:
        """_summary_
        基于Heston模型的每日模拟情景分析，模拟出7天，100条路径（默认），也就是7*100条路径
        参数：
            n_path (int): 模拟路径数，默认100
            days (int): 模拟天数，默认7天
        """
        # 初始化Heston模型
        heston = HestonModel.HestonModel(self.market_params)
        S_paths, v_paths = heston.simulate(days=days, n_paths=n_paths)
        results=[]
        for path_idx in range(n_paths):
            daily_pnl=[] # 存储每日盈亏
            daily_greeks=[] # 存储每日希腊值
            for day in range(days):
                # 计算剩余时间
                T = max(self.opt_positions[0]["days_to_expiry"]/365 - (day+1)/365, 1/365)
                # 获取当日参数
                current_S = S_paths[path_idx, day+1]
                current_vol = v_paths[path_idx, day+1]
                # 计算当日情况
                result = self._calculate_position_pnl(current_S, current_vol, T)
                daily_pnl.append(result["pnl"])
                daily_greeks.append(result["greeks"])
            # 记录单一路径结果
            results.append({
                "path": path_idx,
                "S_paths": S_paths[path_idx], # 价格路径
                "v_paths": v_paths[path_idx], # 波动率路径
                "cum_pnl": np.cumsum(daily_pnl), # 累积盈亏
                "daily_greeks": daily_greeks
            })
        # 将结果转换为DataFrame
        df = pd.DataFrame(results)
        return df


# import QAnalysis_opt_position as p
# params = p.read_position()
#
# analyzer = ScenarioAnalyzer(
#     opt_positions=params['positions'],
#     und_positions=params['underlying_position'],
#     market_params=params['market_params']
# )
# total_pnl, greeks = analyzer._calculate_position_pnl(
#     S=params['market_params']["S0"],
#     sigma=params['market_params']["v0"],
#     T=params['positions'][0]["days_to_expiry"]/365
# )
# print(total_pnl)
# print(greeks)
# df = analyzer._scenario_analysis(n_scenarios=10, days_later=5)
# print(df)
# df=analyzer.daily_simulation_heston()
# print(df)