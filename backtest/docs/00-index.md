# 回测框架文档索引

> 本目录 (`backtest/docs/`) 是 GetRich 回测引擎的设计与接口文档。所有文档以 **设计契约 (Design Contract)** 形式写作：先描述功能边界与数据契约，再给关键类型签名与最小可运行示例。实现细节落到代码注释与单测。
>
> 阅读顺序：先看 `01-architecture.md` 建立全局认知，再按需深入到分层文档；客户端开发者直接看 `60-client-api.md` 即可上手。

## 文档地图

| 编号 | 文件 | 作用 | 主要读者 |
| --- | --- | --- | --- |
| 00 | [`00-index.md`](./00-index.md) | 全部文档索引、阅读路径 | 全员 |
| 01 | [`01-architecture.md`](./01-architecture.md) | 整体分层架构、模块依赖图、事件循环、关键设计原则、相对原需求的重组说明 | 全员 |
| 10 | [`10-data-layer.md`](./10-data-layer.md) | 行情数据访问层。Polars 长表 Schema、PgSQL 装载、品种/频率覆盖、元数据表、时区与精度约定 | 数据/策略/因子 |
| 11 | [`11-data-quality.md`](./11-data-quality.md) | 数据质量与复权。缺失 bar、停牌、涨跌停、成交量为 0、A股复权口径、分红送转配股、期货主连/次主连/换月 | 数据/策略 |
| 12 | [`12-calendar-tradability.md`](./12-calendar-tradability.md) | 交易日历与可交易性引擎。各交易所交易段、集合竞价、夜盘、临时休市；每根 bar 的下单/成交/估值/结算许可 | 数据/执行 |
| 20 | [`20-strategy-api.md`](./20-strategy-api.md) | 策略 API。信号型/目标仓位型/事件驱动型策略；生命周期钩子；状态持久化；热启动与断点续跑 | 策略 |
| 21 | [`21-portfolio-construction.md`](./21-portfolio-construction.md) | 组合构建与调仓。信号→权重→目标头寸；等权/波动率倒数/风险平价；行业/品种约束；定期/阈值调仓；多策略资金分配 | 策略/投资组合 |
| 30 | [`30-execution-engine.md`](./30-execution-engine.md) | 执行引擎。订单类型、撮合模型、滑点、手续费、容量与流动性、部分成交、决策/执行延迟 | 执行/策略 |
| 31 | [`31-account-margin.md`](./31-account-margin.md) | 账户与保证金。可用资金、保证金（初始/维持）、市值、每日结算、T+1/T+0、期权行权与指派、强平、公司行为对持仓的调整 | 执行/策略 |
| 32 | [`32-risk-control.md`](./32-risk-control.md) | 风险控制。Greeks 暴露（含 Cash Greeks）、单品种/全仓暴露、杠杆率/风险度、事前/事后风控、强平触发 | 风控/策略 |
| 40 | [`40-metrics.md`](./40-metrics.md) | 输出指标。收益（总/年化/日/月，含 bar 级隔夜/日内拆解）、统计（Sharpe/Sortino/Calmar）、分析（胜率/盈亏比/最大回撤/换手/成交笔数） | 分析/产品 |
| 41 | [`41-factor-eval.md`](./41-factor-eval.md) | 因子评估。预处理（去极值/标准化/中性化）、IC/RankIC/IR、衰减、换手、分层回测、多空回测 | 因子研究 |
| 42 | [`42-benchmark-attribution.md`](./42-benchmark-attribution.md) | 基准与归因。基准选择、Alpha/Beta/TE/IR、按品种/行业/策略/因子/日内隔夜/费用的归因，含 Greeks PnL 归因 | 分析 |
| 43 | [`43-stress-test.md`](./43-stress-test.md) | 压力测试与情景。单日跳空、波动率飙升、保证金上调、流动性枯竭、历史情景重演、VaR / ES | 风控 |
| 50 | [`50-param-search.md`](./50-param-search.md) | 参数搜索与样本外验证。网格/随机/贝叶斯、Walk-forward、Train/Val/Test、稳定性热力图、过拟合检测 | 策略研究 |
| 51 | [`51-config-versioning.md`](./51-config-versioning.md) | 配置、版本与可复现。配置 Schema、数据/代码/参数版本快照、随机种子、Run ID、复跑校验 | 平台/MLOps |
| 52 | [`52-report-visualization.md`](./52-report-visualization.md) | 报告与可视化。Tear sheet、权益/回撤曲线、月度收益热力图、持仓/成交点位、风险暴露时间序列、HTML/Parquet/JSON 导出 | 分析/产品 |
| 60 | [`60-client-api.md`](./60-client-api.md) | 客户端接口。Strategy/Backtest/Result 完整签名、上下文对象、CLI、最小可运行示例 | 策略开发者 |

## 文档之间的依赖

```text
01-architecture
   ├── 10/11/12 (数据)
   ├── 20/21    (策略 / 组合)
   ├── 30/31/32 (执行 / 账户 / 风控)
   ├── 40/41/42/43 (分析)
   ├── 50/51/52 (研究 / 基础设施 / 报告)
   └── 60       (客户端汇总)
```

`60-client-api.md` 引用其它所有模块的入口符号，作为读者的"单页快查"入口。

## 文档书写约定

1. **类型签名为准**：所有公开类型用 Python 3.13 风格写。`Decimal` 用于现金/PnL/费率；`Float64` 用于价格/收益率/Greeks。
2. **时区**：全部时间字段统一 `Asia/Shanghai (UTC+8)`，落库前 aware。无 naive datetime。
3. **金额**：现金账户、手续费、保证金、PnL **必须** `decimal.Decimal`；禁止 `float`。
4. **行情数据**：以 Polars 长表为唯一传递载体。列名严格使用 `dt, symbol, asset_class, exchange, open, high, low, close, volume, amount, vwap, oi, settlement, adj_factor` 等标准字段，详见 `10-data-layer.md`。
5. **数值精度**：Greeks 与因子值用 Float64；账户与归因用 Decimal；落 Parquet 时按列指定精度。
6. **示例代码**：每篇文档至少给一个最小可运行片段；放在 `## 最小示例` 节末。
