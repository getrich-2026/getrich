# ====================
# Heston随机波动率模型类
# Author: QiuZihua
# Date: 2025-08-16
# ====================


import numpy as np


class HestonModel:
    """实现Heston随机波动率模型"""

    def __init__(self, params: dict[str, float]):
        """_summary_
        初始化模型参数
        Args:
            params (Dict[str,float]): 接受第一部分的市场参数
        """
        self.params = params  # 接收市场参数

    def simulate(self, days: int, n_paths: int) -> np.ndarray:
        """_summary_
        模拟标的资产价格和波动率路径
        Args:
            days (int): 模拟天数_
            n_paths (int): 模拟路径数量_

        Returns:
            np.ndarray: 价格路径矩阵，波动率路径矩阵
            S_paths (np.ndarray): 价格路径矩阵(形状：n_paths * days +1)
            v_paths (np.ndarray): 波动率路径矩阵(形状：n_paths * days +1)
        """
        # 生成标准正态随机数（两个独立序列）
        dt = 1 / 252
        rand = np.random.standard_normal((n_paths, days, 2))
        # 初始化路径存储矩阵（包含初始值）
        S_paths = np.zeros((n_paths, days + 1))
        v_paths = np.zeros((n_paths, days + 1))
        # 设置初始值
        S_paths[:, 0] = self.params["S0"]  # 所有路径的初始价格
        v_paths[:, 0] = self.params["v0"]  # 所有路径的初始波动率
        # 按照时间进行模拟
        for t in range(1, days + 1):
            # 获取前一个时间步的值
            S_prev = S_paths[:, t - 1]  # 前一列时间步的价格
            v_prev = v_paths[:, t - 1]  # 前一列时间步的波动率
            lnS_prev = np.log(S_prev)  # 前一列时间步的对数价格
            # 分解当前时间步的随机数
            epsilon1 = rand[:, t - 1, 0]  # 第一个标准正态随机数序列,用于价格过程的随机数
            epsilon2 = rand[:, t - 1, 1]  # 第二个标准正态随机数序列，用于波动率过程的随机数
            # 计算相关的布朗运动增量
            dW1 = epsilon1 * np.sqrt(dt)  # 价格过程的布朗运动增量
            # 通过Choleskey分解计算相关的布朗运动增量
            dW2 = (
                self.params["rho"] * epsilon1 + np.sqrt(1 - self.params["rho"] ** 2) * epsilon2
            ) * np.sqrt(dt)
            # 更新波动率路径（欧拉离散化）
            sqrt_v_prev = np.sqrt(np.maximum(v_prev, 0.01))  # 防止负波动率,设置不小于1%
            v_new = (
                v_prev
                + self.params["kappa"] * (self.params["theta"] - v_prev) * dt
                + self.params["sigma_v"] * sqrt_v_prev * dW2
            )
            v_new = np.maximum(v_new, 0.01)  # 确保波动率始终为正,不小于1%
            v_paths[:, t] = v_new  # 存储更新后的波动率
            # 更新资产价格路径（对数欧拉方法）
            drift = (
                self.params["r"] - self.params["q"] - 0.5 * np.maximum(v_prev, 0.01)
            ) * dt  # 漂移项
            diffusion = sqrt_v_prev * dW1  # 扩散项
            lnS_new = lnS_prev + drift + diffusion  # 新的对数价格
            S_paths[:, t] = np.exp(lnS_new)  # 存储更新后的价格
        return S_paths, v_paths


# 示例用法
# if __name__ == "__main__":
#     # 设置模型参数
#     params = {
#         "S0": 100.0,    # 初始价格
#         "v0": 0.04,     # 初始波动率(方差)
#         "r": 0.05,      # 无风险利率
#         "q": 0.00,      # 分红率
#         "kappa": 2.0,   # 波动率回归速度
#         "theta": 0.04,  # 长期平均波动率
#         "sigma_v": 0.1,   # 波动率的波动率
#         "rho": -0.7,    # 价格与波动的相关系数
#         "days": 252,    # 模拟天数(1年)
#         "num_paths": 5  # 路径数量
#     }
#
#     # 初始化模型实例
#     heston_model = HestonModel(params)
#
#     # 执行模拟
#     price_paths, volatility_paths = heston_model.simulate(params["days"], params["num_paths"])
#
#     # 查看输出形状
#     print("资产价格路径矩阵形状:", price_paths.shape)    # 应输出 (5, 253)
#     print("波动率路径矩阵形状:", volatility_paths.shape) # 应输出 (5, 253)
#
#     # 展示第一条路径的前5个价格
#     print("\n第一条路径前5日价格:", price_paths[0, :5])
#     # 展示第一条路径的前5个波动率
#     print("第一条路径前5日波动率:", volatility_paths[0, :5])
