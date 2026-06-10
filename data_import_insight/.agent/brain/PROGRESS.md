# PROGRESS

更新时间：2026-06-09

本文件是 AI 首读入口。后续接手时先读这里，再按“阅读顺序”进入稳定事实、任务和项目文档。

## 当前版本

| 项目 | 当前状态 |
|---|---|
| 文档版本 | v0.1.8 |
| 阶段 | INSIGHT P1 本地验证后；RiceQuant provider API 适配器已迁入并通过相关测试 |
| 数据库环境 | PostgreSQL 17 + TimescaleDB；ClickHouse 25 |
| Python 环境 | Python 3.10+，使用 `uv` 管理 |
| 当前提交参考 | `2451fe7 docs: 拆分 agent brain 文档` |

## 最新状态

- INSIGHT 数据路径采用 `SDK -> local Parquet -> PostgreSQL/TimescaleDB`。
- 需要长期权威保存的数据进入 PostgreSQL + TimescaleDB；临时验证、源对比、快照和宽表分析进入 DuckDB。
- ClickHouse 25 已作为后续高频数据目标环境，当前尚未实现 tick/逐笔落库 schema。
- INSIGHT P1 ready 数据集包括：`stock_adj_factor`、`stock_daily_basic`、`stock_valuation`、`index_component`、`etf_daily`、`etf_nav`、`fund_daily`、`fund_nav`、`etf_basket`。
- RiceQuant provider 适配器已迁入 `data_import_insight`，并覆盖 `id_convert`、`get_trading_periods`、market 配置传递和 license env 初始化等测试。当前处于试用期，INSIGHT 仍是主要行情来源，RiceQuant 优先验证 instruments、trading calendar/trading day 和少量行情补充样本。
- 最近验证通过：复权因子宽日期、ETF daily/nav/basket、期货/期权日线和分钟线小样本，以及 RiceQuant 适配器的单元测试覆盖。

## 文档地图

| 文档 | 用途 |
|---|---|
| `.agent/brain/PROGRESS.md` | AI 首读入口：当前状态、版本表、文档地图、阅读顺序。 |
| `.agent/brain/INFO.md` | 稳定事实：技术栈、目录、约定、架构决策、数据策略。 |
| `.agent/brain/TODO.md` | 后续任务：P0-P3、code-review findings 和当前风险。 |
| `README.md` | 面向人的快速开始和常用命令。 |
| `CHANGELOG.md` | 版本日志，最新版本为 v0.1.8。 |
| `docs/PRD.md` | 项目级 PRD 入口。 |
| `docs/ARCHITECTURE.md` | 项目级架构入口。 |
| `docs/insight_import_product_requirements.md` | INSIGHT 导入产品需求详细版。 |
| `docs/insight_import_architecture.md` | INSIGHT 导入架构详细版。 |
| `docs/ricequant_import_architecture.md` | RiceQuant provider 架构详细版。 |
| `docs/insight_p1_schema_review.md` | INSIGHT P1 schema 和样本评审。 |
| `docs/华泰INSIGHT_数据封装_开发文档.md` | INSIGHT 上游资料摘录和 API 参考。 |

## 阅读顺序

1. `.agent/brain/PROGRESS.md`
2. `.agent/brain/INFO.md`
3. `.agent/brain/TODO.md`
4. `README.md`
5. `CHANGELOG.md`
6. `docs/PRD.md`
7. `docs/ARCHITECTURE.md`
8. 需要细节时再读 `docs/insight_import_product_requirements.md`、`docs/insight_import_architecture.md`、`docs/ricequant_import_architecture.md`、`docs/insight_p1_schema_review.md`

## 最近验证

- `.venv/bin/ruff check src tests`：全部通过。
- `.venv/bin/pytest tests -q`：包含 3 个新 RiceQuant 测试用例，全部通过。
- RiceQuant 真实 license smoke：`tcp_license` 初始化通过；`id_convert('000001.SZ')` 返回 `000001.XSHE`；`instrument_frame` 返回 240350 行；calendar 8 个交易所帧；`000001.XSHE` 日线样本 1 行；`get_trading_periods` 样本 1 行。账号提示约 11 天后到期。
- `verify-schema`：通过，无 missing tables、hypertables、migrations、views。
- `stock_adj_factor`：`000001.SZ`，`2020-01-01` 到 `2026-06-04`，fetch 8 行，load 8 行。
- ETF：`510300.SH`，`2026-06-04`，`etf_daily` 1 行、`etf_nav` 1 行、`etf_basket` 300 行。
- 期货：`CU00.SHF`，`2026-06-04`，`future_bar_1d` 1 行、`future_bar_1m` 224 行。
- 期权：`10010317.SH`，`2026-06-04`，`option_bar_1d` 1 行、`option_bar_1m` 242 行。
