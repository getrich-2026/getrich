# 设计契约（原 `backtest/docs/`）

> **本节为原始设计文档的镜像展示**。所有 19 篇设计契约都源自 `backtest/docs/` 目录，通过 `mkdocs-include-markdown-plugin` 自动嵌入；任何对设计文档的修改只需改 `backtest/docs/*.md`，本站自动同步。

## 为什么要分两层？

- `backtest/docs/` —— 19 篇"设计意图"（设计契约），面向项目维护者
- 本节 —— 同样内容，对外暴露；新读者通过左侧 nav 一站式跳转

**修改建议**：所有设计变更必须先在 `backtest/docs/` 改，本节是只读镜像。

---

## 索引

| # | 主题 | 文档 |
|---|---|---|
| 00 | 总索引 | [原文](https://github.com/getrich/getrich/blob/main/backtest/docs/00-index.md) |
| 01 | 整体架构 | [架构](01-architecture.md) |
| 10 | 数据层 | [数据层](10-data-layer.md) |
| 11 | 数据质量 | [数据质量](11-data-quality.md) |
| 12 | 日历与可交易性 | [日历](12-calendar-tradability.md) |
| 20 | 策略 API | [策略 API](20-strategy-api.md) |
| 21 | 组合构建 | [组合构建](21-portfolio-construction.md) |
| 30 | 执行引擎 | [执行引擎](30-execution-engine.md) |
| 31 | 账户与保证金 | [账户保证金](31-account-margin.md) |
| 32 | 风险控制 | [风控](32-risk-control.md) |
| 40 | 指标 | [指标](40-metrics.md) |
| 41 | 因子评估 | [因子评估](41-factor-eval.md) |
| 42 | 基准与归因 | [归因](42-benchmark-attribution.md) |
| 43 | 压力测试 | [压力测试](43-stress-test.md) |
| 50 | 参数搜索 | [参数搜索](50-param-search.md) |
| 51 | 配置与版本 | [配置版本](51-config-versioning.md) |
| 52 | 报告与可视化 | [报告](52-report-visualization.md) |
| 60 | 客户端接口 | [客户端](60-client-api.md) |

---

## 阅读建议

| 你是谁 | 推荐阅读顺序 |
|---|---|
| **第一次接触引擎** | 00 → 01 整体架构 → 20 策略 API → 30 执行引擎 |
| **数据工程师** | 10 数据层 → 11 数据质量 → 12 日历 → 01 |
| **策略开发者** | 20 策略 API → 21 组合构建 → 40 指标 → 50 参数搜索 |
| **风控 / 审计** | 31 账户保证金 → 32 风险控制 → 43 压力测试 |
| **研究者 / Quant** | 40 指标 → 41 因子评估 → 42 归因 → 43 压力测试 |
| **运维 / DevOps** | 51 配置版本 → 52 报告 → 60 客户端 |

---

> **本节所有内容直接来自 `backtest/docs/`**。如果你看到任何过时或不一致，请优先修改源文件。
