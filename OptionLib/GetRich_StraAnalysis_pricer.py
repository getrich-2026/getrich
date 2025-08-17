# ========================
# 核心定价模型类
# Author: QiuZihua
# Date: 2025-08-16
# ========================

import numpy as np
import scipy.stats as stats

class OptionPricer:
    """期权定价及希腊值计算核心类"""
    @staticmethod
    def black_scholes(S: float, K: float, T: float, sigma: float,
                     r: float, q: float, option_type: str) -> float:
        """欧式期权定价（Black-Scholes模型）
        Args:
            S (float): 标的资产价格
            K (float): 行权价
            T (float): 剩余到期期限（年化）
            sigma (float): 波动率
            r (float): 无风险利率
            q (float): 股息率
            option_type (str): 期权类型(call/put)
        Returns:
            float: 期权理论价格
        """
        # 检查是否到期
        if T <= 0:
            return max(S - K, 0) if option_type == "call" else max(K - S, 0)

        # 计算d1和d2参数
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        # 根据期权类型计算理论价格
        if option_type == "call":
            price = S * np.exp(-q * T) * stats.norm.cdf(d1) - K * np.exp(-r * T) * stats.norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * stats.norm.cdf(-d2) - S * np.exp(-q * T) * stats.norm.cdf(-d1)

        return round(price, 4)

    @staticmethod
    def binomial_tree(S: float, K: float, T: float, sigma: float,
                     r: float, q: float, option_type: str, steps: int = 100) -> float:
        """美式期权定价（二叉树模型）
        Args:
            S (float): 标的资产价格
            K (float): 行权价
            T (float): 剩余到期期限（年化）
            sigma (float): 波动率
            r (float): 无风险利率
            q (float): 股息率
            option_type (str): 期权类型(call/put)
            steps (int): 二叉树步数，默认为100
        Returns:
            float: 美式期权理论价格
        """
        # 检查是否到期
        if T <= 0:
            return max(S - K, 0) if option_type == "call" else max(K - S, 0)

        dt = T / steps  # 每步时间长度
        u = np.exp(sigma * np.sqrt(dt))  # 价格上涨因子
        d = 1 / u  # 价格下跌因子
        p = (np.exp((r - q) * dt) - d) / (u - d)  # 风险中性概率
        df = np.exp(-r * dt)  # 贴现因子

        # 初始化到期日价格数组
        prices = np.zeros(steps + 1)
        for j in range(steps + 1):
            st = S * (u ** (steps - j)) * (d ** j)
            prices[j] = max(st - K, 0) if option_type == "call" else max(K - st, 0)

        # 向后递归计算期权价值
        for i in range(steps - 1, -1, -1):
            for j in range(i + 1):
                st = S * (u ** (i - j)) * (d ** j)
                continuation = df * (p * prices[j] + (1 - p) * prices[j + 1])
                exercise = max(st - K, 0) if option_type == "call" else max(K - st, 0)
                prices[j] = max(continuation, exercise)  # 美式期权可以提前行权

        return round(prices[0], 4)

    @staticmethod
    def calculate_greeks(S: float, K: float, T: float, sigma: float,
                        r: float, q: float, option_type: str, multiplier: int,
                        american: bool = False, steps: int = 100) -> tuple:
        """计算期权的希腊值（支持欧式和美式期权）
        Args:
            S (float): 标的资产价格
            K (float): 行权价
            T (float): 剩余到期期限（年化）
            sigma (float): 波动率
            r (float): 无风险利率
            q (float): 股息率
            option_type (str): 期权类型(call/put)
            multiplier (int): 合约乘数
            american (bool): 是否为美式期权，默认为False
            steps (int): 二叉树步数（仅美式期权需要），默认为100
        Returns:
            tuple: (希腊值字典, 现金希腊值字典)
        """
        # 通过扰动法计算希腊值
        h = 0.01  # 扰动因子

        # 计算Delta：标的资产价格变动的影响
        if american:
            price = OptionPricer.binomial_tree(S, K, T, sigma, r, q, option_type, steps)
            price_up = OptionPricer.binomial_tree(S * (1 + h), K, T, sigma, r, q, option_type, steps)
            price_down = OptionPricer.binomial_tree(S * (1 - h), K, T, sigma, r, q, option_type, steps)
        else:
            price = OptionPricer.black_scholes(S, K, T, sigma, r, q, option_type)
            price_up = OptionPricer.black_scholes(S * (1 + h), K, T, sigma, r, q, option_type)
            price_down = OptionPricer.black_scholes(S * (1 - h), K, T, sigma, r, q, option_type)

        delta = (price_up - price_down) / (2 * S * h)

        # 计算Gamma：标的资产价格二阶导数
        gamma = (price_up - 2 * price + price_down) / (S * h) ** 2

        # 计算Vega：波动率变动的影响
        if american:
            price_sigma_up = OptionPricer.binomial_tree(S, K, T, sigma + h, r, q, option_type, steps)
        else:
            price_sigma_up = OptionPricer.black_scholes(S, K, T, sigma + h, r, q, option_type)
        vega = (price_sigma_up - price) / h * 0.01  # 1%波动率变化

        # 计算Theta：时间衰减（减少一天）
        T_small = max(T - 1 / 365, 0)  # 确保时间不为负
        if american:
            price_t = OptionPricer.binomial_tree(S, K, T_small, sigma, r, q, option_type, steps)
        else:
            price_t = OptionPricer.black_scholes(S, K, T_small, sigma, r, q, option_type)
        theta = (price_t - price)  # 一天时间衰减

        # 整理希腊值
        greeks = {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "vega": round(vega, 4),
            "theta": round(theta, 4)
        }

        # 计算现金希腊值
        greekscash = {
            "delta_cash": round(delta * multiplier * S * 0.01, 4),
            "gamma_cash": round(0.01 * 0.01 * gamma * S * S * multiplier, 4),
            "vega_cash": round(vega * multiplier, 4),
            "theta_cash": round(theta * multiplier, 4)
        }

        return greeks, greekscash

"""
# 示例使用
if __name__ == "__main__":
    # 欧式期权示例
    print("欧式看涨期权:")
    greeks_eu, greekscash_eu = OptionPricer.calculate_greeks(
        S=5888, K=5900, T=16 / 365, sigma=0.28, r=0.02, q=0,
        option_type="call", multiplier=100, american=False
    )
    print("希腊值:", greeks_eu)
    print("现金希腊值:", greekscash_eu)

    # 美式期权示例
    print("\n美式看跌期权:")
    greeks_us, greekscash_us = OptionPricer.calculate_greeks(
        S=5888, K=5900, T=16 / 365, sigma=0.28, r=0.02, q=0.01,
        option_type="put", multiplier=100, american=True, steps=100
    )
    print("希腊值:", greeks_us)
    print("现金希腊值:", greekscash_us)

    # 直接计算美式期权价格
    print("\n美式看涨期权价格:")
    us_price = OptionPricer.binomial_tree(
        S=5888, K=5900, T=16 / 365, sigma=0.28, r=0.02, q=0.01,
        option_type="call", steps=100
    )
    print("价格:", us_price)

"""