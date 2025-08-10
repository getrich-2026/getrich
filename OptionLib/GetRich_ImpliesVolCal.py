"""
计算期权隐含波动率
Author: QiuZihua
Date: 2025-08-10
"""

import numpy as np
from scipy.stats import norm
from abc import ABC, abstractmethod
import warnings
import py_vollib.black_scholes as bs
from py_vollib.black_scholes.implied_volatility import implied_volatility as py_iv
from py_vollib.black_scholes.greeks.analytical import delta as py_delta, gamma as py_gamma, vega as py_vega
from scipy.optimize import brentq


class Option(ABC):
    """
    期权基类，定义共同接口和属性

    属性:
        S (float): 标的资产当前价格
        K (float): 期权行权价格
        T (float): 到期时间（年）
        r (float): 无风险利率
        option_type (str): 期权类型，'call' 或 'put'
    """

    def __init__(self, S: float, K: float, T: float, r: float, option_type: str = 'call'):
        """
        初始化期权参数
        参数:
            S: 标的资产当前价格
            K: 行权价格
            T: 到期时间（年）
            r: 无风险利率
            option_type: 期权类型，'call'(看涨) 或 'put'(看跌)
        """
        self.S = S
        self.K = K
        self.T = T
        self.r = r
        self.option_type = option_type.lower()
        if self.option_type not in ['call', 'put']:
            raise ValueError("option_type 必须是 'call' 或 'put'")
        self.moneyness = self._calculate_moneyness()  # 计算期权在值程度

    def _calculate_moneyness(self) -> str:
        """
        计算期权的在值程度（实值、平值、虚值）
        返回:
            'deep_itm' - 深度实值
            'itm' - 实值
            'atm' - 平值
            'otm' - 虚值
            'deep_otm' - 深度虚值
        """
        ratio = self.S / self.K
        if self.option_type == 'call':
            if ratio > 1.3:
                return 'deep_itm'
            elif ratio > 1.05:
                return 'itm'
            elif ratio > 0.95:
                return 'atm'
            elif ratio > 0.7:
                return 'otm'
            else:
                return 'deep_otm'
        else:  # put
            if ratio < 0.7:
                return 'deep_itm'
            elif ratio < 0.95:
                return 'itm'
            elif ratio < 1.05:
                return 'atm'
            elif ratio < 1.3:
                return 'otm'
            else:
                return 'deep_otm'

    @abstractmethod
    def price(self, sigma: float) -> float:
        """
        计算期权理论价格（抽象方法）
        参数:
            sigma: 波动率
        返回:
            期权理论价格
        """
        pass

    def implied_volatility(self, market_price: float,
                           method: str = 'bisection',
                           tol: float = 1e-6,
                           max_iter: int = 100,
                           max_volatility: float = 5.0) -> float:
        """
        计算隐含波动率，处理深度实值/虚值期权问题

        参数:
            market_price: 期权市场价格
            method: 计算方法，'bisection'(二分法) 或 'newton'(牛顿法) 或 'py_vollib'(现成库)
            tol: 容差精度
            max_iter: 最大迭代次数
            max_volatility: 最大波动率搜索范围（防止深度实值/虚值期权的发散问题）

        返回:
            隐含波动率（如果无法计算返回np.nan）
        """
        if self.moneyness in ['deep_itm', 'deep_otm']:
            warnings.warn(f"警告：深度{'实值' if 'itm' in self.moneyness else '虚值'}期权({self.moneyness})"
                          f"可能导致隐含波动率计算不稳定")

        try:
            if method == 'bisection':
                return self._bisection(market_price, tol, max_iter, max_volatility)
            elif method == 'newton':
                return self._newton(market_price, tol, max_iter, max_volatility)
            elif method == 'py_vollib':
                return self._py_vollib_iv(market_price)
            else:
                raise ValueError("不支持的method，应为 'bisection'、'newton' 或 'py_vollib'")
        except Exception as e:
            # 处理深度实值/虚值期权的计算失败问题
            warnings.warn(f"无法计算隐含波动率: {str(e)}")
            return np.nan

    def _bisection(self, market_price: float, tol: float, max_iter: int, max_volatility: float) -> float:
        """
        改进的二分法计算隐含波动率，处理深度实值/虚值问题
        参数:
            market_price: 期权市场价格
            tol: 容差精度
            max_iter: 最大迭代次数
            max_volatility: 最大波动率搜索范围
        返回:
            隐含波动率
        """
        low, high = 0.001, max_volatility  # 波动率搜索范围

        # 检查区间是否有效[6](@ref)
        f_low = self.price(low) - market_price
        f_high = self.price(high) - market_price

        # 处理深度实值/虚值期权的符号问题[6](@ref)
        if f_low * f_high > 0:
            # 尝试扩展区间
            for i in range(10):
                high *= 2
                f_high = self.price(high) - market_price
                if f_low * f_high <= 0:
                    break
            else:
                raise ValueError("无法找到有效的波动率区间，深度实值/虚值期权可能无解")

        # 执行二分法
        for i in range(max_iter):
            mid = (low + high) / 2
            f_mid = self.price(mid) - market_price

            if abs(f_mid) <= tol:
                return mid

            # 调整搜索区间
            if f_mid * f_low < 0:
                high = mid
                f_high = f_mid
            else:
                low = mid
                f_low = f_mid

        # 检查最终结果
        if abs(self.price((low + high) / 2) - market_price) > tol:
            raise ValueError(f"二分法未在 {max_iter} 次迭代内收敛")
        return (low + high) / 2

    def _newton(self, market_price: float, tol: float, max_iter: int, max_volatility: float) -> float:
        """
        改进的牛顿法计算隐含波动率，处理Vega接近零的问题

        参数:
            market_price: 期权市场价格
            tol: 容差精度
            max_iter: 最大迭代次数
            max_volatility: 最大波动率搜索范围
        返回:
            隐含波动率
        """
        sigma = 0.3  # 初始猜测值
        min_vega = 1e-6  # Vega最小值阈值

        for i in range(max_iter):
            # 计算价格和Vega
            p = self.price(sigma)
            v = self.vega(sigma)

            # 处理深度实值/虚值期权的Vega接近零问题[6,8](@ref)
            if abs(v) < min_vega:
                # 尝试切换方法或调整初始值
                if sigma < 0.1:
                    sigma = min(sigma * 2, max_volatility)
                else:
                    sigma = max(sigma * 0.5, 0.001)
                v = self.vega(sigma)
                if abs(v) < min_vega:
                    raise ValueError(f"Vega值过小({v:.6f})，牛顿法不适用于深度实值/虚值期权")

            # 更新波动率
            adjustment = (p - market_price) / v
            sigma -= adjustment

            # 确保波动率在合理范围内
            if sigma < 0.001:
                sigma = 0.001
            elif sigma > max_volatility:
                sigma = max_volatility

            # 检查收敛
            if abs(p - market_price) <= tol:
                return sigma

        # 检查最终结果
        if abs(self.price(sigma) - market_price) > tol:
            raise ValueError(f"牛顿法未在 {max_iter} 次迭代内收敛")
        return sigma

    def vega(self, sigma: float, ds: float = 0.01) -> float:
        """
        计算Vega值（价格对波动率的敏感度）

        参数:
            sigma: 波动率
            ds: 数值微分步长

        返回:
            Vega值
        """
        # 中心差分法计算Vega
        price_up = self.price(sigma + ds)
        price_down = self.price(sigma - ds)
        return (price_up - price_down) / (2 * ds)

    def _py_vollib_iv(self, market_price: float) -> float:
        """
        使用py_vollib专业库计算隐含波动率，增加异常处理

        参数:
            market_price: 期权市场价格

        返回:
            隐含波动率

        异常:
            当深度实值/虚值期权无法计算时返回np.nan
        """
        try:
            flag = 'c' if self.option_type == 'call' else 'p'
            return py_iv(market_price, self.S, self.K, self.T, self.r, flag)
        except Exception as e:
            # 处理深度实值/虚值期权的计算失败问题[6](@ref)
            warnings.warn(f"py_vollib无法计算隐含波动率: {str(e)}")
            return np.nan

    def py_vollib_greeks(self, sigma: float) -> dict:
        """
        使用py_vollib专业库计算希腊值

        参数:
            sigma: 波动率

        返回:
            包含希腊值的字典(delta, gamma, vega)
        """
        flag = 'c' if self.option_type == 'call' else 'p'
        return {
            'delta': py_delta(flag, self.S, self.K, self.T, self.r, sigma),
            'gamma': py_gamma(flag, self.S, self.K, self.T, self.r, sigma),
            'vega': py_vega(flag, self.S, self.K, self.T, self.r, sigma)
        }


class EuropeanOption(Option):
    """
    欧式期权类（股指期权， ETF期权等）
    使用Black-Scholes模型定价，支持连续股息率q
    """

    def __init__(self, S: float, K: float, T: float, r: float,
                 option_type: str = 'call', q: float = 0.0):
        """
        初始化欧式期权
        参数:
            q: 连续股息率
        """
        super().__init__(S, K, T, r, option_type)
        self.q = q

    def price(self, sigma: float) -> float:
        """
        计算欧式期权价格（Black-Scholes模型）
        参数:
            sigma: 波动率
        返回:
            期权价格
        """
        if self.T <= 0:
            # 到期时期权价值
            if self.option_type == 'call':
                return max(0, self.S - self.K)
            else:
                return max(0, self.K - self.S)

        d1 = (np.log(self.S / self.K) +
              (self.r - self.q + 0.5 * sigma ** 2) * self.T) / (sigma * np.sqrt(self.T))
        d2 = d1 - sigma * np.sqrt(self.T)

        if self.option_type == 'call':
            return (self.S * np.exp(-self.q * self.T) * norm.cdf(d1) -
                    self.K * np.exp(-self.r * self.T) * norm.cdf(d2))
        else:  # put
            return (self.K * np.exp(-self.r * self.T) * norm.cdf(-d2) -
                    self.S * np.exp(-self.q * self.T) * norm.cdf(-d1))

    def price_py_vollib(self, sigma: float) -> float:
        """
        使用py_vollib专业库计算欧式期权价格
        参数:
            sigma: 波动率

        返回:
            期权价格
        """
        flag = 'c' if self.option_type == 'call' else 'p'
        return bs.black_scholes(flag, self.S, self.K, self.T, self.r, sigma)

    def vega(self, sigma: float) -> float:
        """
        计算Vega值（解析解）
        参数:
            sigma: 波动率
        返回:
            Vega值
        """
        if self.T <= 0:
            return 0.0  # 到期时期权的Vega为零

        d1 = (np.log(self.S / self.K) +
              (self.r - self.q + 0.5 * sigma ** 2) * self.T) / (sigma * np.sqrt(self.T))
        return self.S * np.exp(-self.q * self.T) * np.sqrt(self.T) * norm.pdf(d1)


class AmericanOption(Option):
    """
    美式期权类（商品期货期权）
    支持二叉树模型和BAW近似模型（仅看涨期权）
    """

    def __init__(self, S: float, K: float, T: float, r: float,
                 option_type: str = 'call', steps: int = 100, q: float = 0.0):
        """
        初始化美式期权
        参数:
            steps: 二叉树步数
            q: 连续股息率
        """
        super().__init__(S, K, T, r, option_type)
        self.steps = steps
        self.q = q

    def price(self, sigma: float, method: str = 'tree') -> float:
        """
        计算美式期权价格
        参数:
            sigma: 波动率
            method: 定价方法 - 'tree'(二叉树) 或 'baw'(BAW近似模型)
        返回:
            期权价格
        """
        if method == 'baw':
            if self.option_type == 'call':
                return self._baw_american_call(sigma)
            else:
                # BAW模型不适用于美式看跌期权，自动回退到二叉树
                warnings.warn("BAW模型不适用于美式看跌期权，使用二叉树定价")
                return self._tree_price(sigma)
        else:
            return self._tree_price(sigma)

    def _tree_price(self, sigma: float) -> float:
        """二叉树模型定价"""
        if self.T <= 0:
            # 到期时期权价值
            if self.option_type == 'call':
                return max(0, self.S - self.K)
            else:
                return max(0, self.K - self.S)

        dt = self.T / self.steps
        u = np.exp(sigma * np.sqrt(dt))
        d = 1 / u
        p = (np.exp((self.r - self.q) * dt) - d) / (u - d)

        # 初始化价格树
        prices = np.zeros((self.steps + 1, self.steps + 1))
        for j in range(self.steps + 1):
            ST = self.S * (u ** (self.steps - j)) * (d ** j)
            if self.option_type == 'call':
                prices[j, self.steps] = max(ST - self.K, 0)
            else:  # put
                prices[j, self.steps] = max(self.K - ST, 0)

        # 向后回溯计算
        for t in range(self.steps - 1, -1, -1):
            for j in range(t + 1):
                ST = self.S * (u ** (t - j)) * (d ** j)
                hold = np.exp(-self.r * dt) * (p * prices[j, t + 1] +
                                               (1 - p) * prices[j + 1, t + 1])

                if self.option_type == 'call':
                    exercise = max(ST - self.K, 0)
                else:  # put
                    exercise = max(self.K - ST, 0)

                prices[j, t] = max(hold, exercise)  # 美式期权提前行权判断

        return prices[0, 0]

    def _baw_american_call(self, sigma: float) -> float:
        """
        BAW美式看涨期权定价模型（Barone-Adesi-Whaley）
        参数:
            sigma: 波动率
        返回:
            美式看涨期权价格
        """
        if self.q == 0:
            # 无分红时美式看涨期权等价于欧式看涨期权
            d1 = (np.log(self.S / self.K) +
                  (self.r + 0.5 * sigma ** 2) * self.T) / (sigma * np.sqrt(self.T))
            d2 = d1 - sigma * np.sqrt(self.T)
            return self.S * norm.cdf(d1) - self.K * np.exp(-self.r * self.T) * norm.cdf(d2)

        # 计算临界价格S*
        sigma_sq = sigma ** 2
        M = 2 * self.r / sigma_sq
        N = 2 * (self.r - self.q) / sigma_sq
        k = 1 - np.exp(-self.r * self.T)
        q2 = (1 - N + np.sqrt((N - 1) ** 2 + 4 * M / k)) / 2

        # 计算临界价格S*
        S_star = self.K / (1 - 1 / q2)

        # 计算d1
        d1_star = (np.log(S_star / self.K) +
                   (self.r - self.q + 0.5 * sigma_sq) * self.T) / (sigma * np.sqrt(self.T))

        # 计算A2
        A2 = (S_star / q2) * (1 - np.exp(-self.q * self.T) * norm.cdf(d1_star))

        if self.S < S_star:
            # 计算欧式期权价格
            d1 = (np.log(self.S / self.K) +
                  (self.r - self.q + 0.5 * sigma_sq) * self.T) / (sigma * np.sqrt(self.T))
            d2 = d1 - sigma * np.sqrt(self.T)
            c_bs = (self.S * np.exp(-self.q * self.T) * norm.cdf(d1) -
                    self.K * np.exp(-self.r * self.T) * norm.cdf(d2))
            return c_bs + A2 * (self.S / S_star) ** q2
        else:
            return self.S - self.K


"""
示例部分
"""
if __name__ == "__main__":
    # =====================
    # 欧式期权测试（股指期权）
    # =====================
    print("="*50)
    print("欧式看涨期权测试")
    print("="*50)

    euro_call = EuropeanOption(S=4083.2, K=4100, T=41/365, r=0.03, option_type='call') # 沪深300股指期权，9月合约，平值期权，看涨期权，wind给的iv是14.5%
    market_price = 77.0  # 观察到的市场价格

    # 计算三种方法的隐含波动率
    iv_bisect = euro_call.implied_volatility(market_price, method='bisection')
    iv_newton = euro_call.implied_volatility(market_price, method='newton')
    iv_vollib = euro_call.implied_volatility(market_price, method='py_vollib')

    print(f"欧式看涨期权隐含波动率（二分法）: {iv_bisect:.6f}")
    print(f"欧式看涨期权隐含波动率（牛顿法）: {iv_newton:.6f}")
    print(f"欧式看涨期权隐含波动率（py_vollib）: {iv_vollib:.6f}")

    # =====================
    # 深度实值/虚值期权测试
    # =====================
    print("深度实值看涨期权测试")
    deep_itm_call = EuropeanOption(S=4083.2, K=3800, T=0.5, r=0.03, option_type='call') # wind给出的18%左右
    market_price = 395.0  # 观察到的市场价格
    # 尝试计算隐含波动率
    print("尝试使用py_vollib计算深度实值期权...")
    iv_vollib = deep_itm_call.implied_volatility(market_price, method='py_vollib')
    print(f"py_vollib结果: {iv_vollib}")

    print("\n尝试使用数值方法计算深度实值期权...")
    iv_bisect = deep_itm_call.implied_volatility(market_price, method='bisection', max_volatility=10.0)
    iv_newton = deep_itm_call.implied_volatility(market_price, method='newton', max_volatility=10.0)
    print(f"二分法结果: {iv_bisect:.6f}")
    print(f"牛顿法结果: {iv_newton:.6f}")


    # =====================
    # 商品期货期权 以碳酸锂主力合约2511合约为例
    # =====================
    print("碳酸锂2511合约对应的期权测试")
    american_put = AmericanOption(S=76960, K=77000, T=67/365, r=0.03, option_type='call') # wind给44.56%
    market_price = 5650 # 观察到的市场价格

    # 计算隐含波动率（二叉树模型）
    iv_bisect_tree = american_put.implied_volatility(market_price, method='bisection')
    iv_newton_tree = american_put.implied_volatility(market_price, method='newton')

    print(f"美式看跌期权隐含波动率（二叉树-二分法）: {iv_bisect_tree:.6f}")
    print(f"美式看跌期权隐含波动率（二叉树-牛顿法）: {iv_newton_tree:.6f}")

    # =====================
    # 美式看涨期权BAW模型测试
    # =====================
    print("美式看涨期权测试（BAW模型）")

    american_call = AmericanOption(S=76960, K=77000, T=67/365, r=0.03, option_type='call', q=0)
    market_price = 5650  # 观察到的市场价格

    # 使用BAW模型定价
    baw_price = american_call.price(0.41, method='baw')
    print(f"BAW模型理论价格（波动率=0.41）: {baw_price:.6f}")


    # 计算BAW模型的隐含波动率
    def baw_error(sigma):
        return american_call.price(sigma, method='baw') - market_price


    try:
        iv_baw = brentq(baw_error, 0.01, 5.0)
        print(f"美式看涨期权隐含波动率（BAW模型）: {iv_baw:.6f}")
    except Exception as e:
        print(f"BAW模型计算失败: {str(e)}")

    # 对比二叉树模型
    iv_bisect_tree = american_call.implied_volatility(market_price, method='bisection')
    print(f"美式看涨期权隐含波动率（二叉树-二分法）: {iv_bisect_tree:.6f}")