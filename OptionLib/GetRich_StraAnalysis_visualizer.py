# ================
# 可视化模块
# Author: QiuZihua
# Date: 2025-08-16
# ================
#


from pyecharts.charts import Line, Scatter3D, Bar # 可视化
from pyecharts import options as opts # 图表配置
from pyecharts.faker import Faker # 图表配置
import pandas as pd
import numpy as np
import GetRich_StraAnalysis_riskanalyzer as RiskAnalyzer

class Visualizer:
    """图表可视化"""
    def plot_scenario_analysis(self,df:pd.DataFrame)->Scatter3D:
        """_summary_
        绘制情景分析结果的折线图
        Args:
            df (pd.DataFrame): 情景分析结果DataFrame
        Returns:
            Line: 折线图对象
        """
        data = [(df["price_change"].round(4).tolist()[i], df["vol_change"].round(4).tolist()[i],
                 df["pnl"].round(4).tolist()[i]) for i in range(len(df))]
        scatter = (
            Scatter3D(init_opts=opts.InitOpts(width="1000px", height="800px"))
            .add(
                series_name="组合盈亏(情景分析)",
                data= data,
                xaxis3d_opts=opts.Axis3DOpts(name="价格变化",type_="value"),
                yaxis3d_opts=opts.Axis3DOpts(name="波动率变化",type_="value"),
                zaxis3d_opts=opts.Axis3DOpts(name="总盈亏",type_="value"),
                grid3d_opts=opts.Grid3DOpts(width=100, height=100, depth=100, is_rotate=True),
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(title="期权组合情景分析"),
                visualmap_opts=opts.VisualMapOpts(max_=max(df["pnl"]), min_=min(df["pnl"]),range_color=Faker.visual_color)
            )
        )
        return scatter

    def plot_greek_exposure(self,greeks_df:pd.DataFrame)->Bar:
        """_summary_
        绘制希腊字母暴露的柱状图
        Args:
            greeks_df (pd.DataFrame): 希腊字母暴露DataFrame
        Returns:
            Bar: 柱状图对象
        """
        bar = (
            Bar(init_opts=opts.InitOpts(width="1000px", height="800px"))
            .add_xaxis(greeks_df.columns.tolist())
            .add_yaxis("风险敞口均值", greeks_df.mean().tolist())
           .set_global_opts(
                title_opts=opts.TitleOpts(title="希腊字母风险敞口"),
                yaxis_opts=opts.AxisOpts(name="风险敞口大小"),
                visualmap_opts=opts.VisualMapOpts(max_=max(greeks_df.mean()), min_=min(greeks_df.mean()),range_color=Faker.visual_color)
            )
        )
        return bar

    def plot_var_distribution(self,pnl_series:pd.Series, var:float)->Line:
        """_summary_
        绘制Value at Risk (VaR) 分布的折线图
        Args:
            pnl_series (pd.Series): 盈亏序列
        Returns:
            Line: 包含VaR分布的折线图
        """
        # 计算VaR分布
        hist, bins = np.histogram(pnl_series, bins=50)
        var_95 = RiskAnalyzer.RiskAnalyzer().calculate_var(pnl_series=pnl_series, confidence_level=0.95)
        line = (
            Line(init_opts=opts.InitOpts(width="1000px", height="800px"))
            .add_xaxis([f"{b:.0f}" for b in bins[:-1]])
            .add_yaxis("频数", hist.tolist())
            .set_global_opts(
                title_opts=opts.TitleOpts(title="Value at Risk (VaR) 分布与盈亏分布"),
                xaxis_opts=opts.AxisOpts(name="盈亏区间"),
                yaxis_opts=opts.AxisOpts(name="频数"),
                datazoom_opts=[opts.DataZoomOpts()],
            )
        )
        return line

# import option_position_analysis_params as params
# from option_position_analysis_Scenario import ScenarioAnalyzer
# analyzer = ScenarioAnalyzer(
#     opt_positions=params.positions,
#     und_positions=params.underlying_position,
#     market_params=params.market_params
# )
# total_pnl, greeks = analyzer._calculate_position_pnl(
#     S=params.market_params["S0"],
#     sigma=params.market_params["v0"],
#     T=params.positions[0]["days_to_expiry"]/365
# )
# df = analyzer._scenario_analysis(n_scenarios=100, days_later=5)
# # df=analyzer.daily_simulation_heston()
# print(df)
# Sca = Visualizer.plot_scenario_analysis(df)
# Sca.render('pnl.html')

# greeks_df = df[["delta_cash", "gamma_cash", "theta_cash", "vega_cash"]].round(4)
# bar = Visualizer.plot_greek_exposure(greeks_df)
# bar.render('greeks.html')
# line = Visualizer.plot_var_distribution(df["pnl"], var=RiskAnalyzer.calculate_var(df["pnl"], confidence_level=0.95))
# line.render('var.html')

