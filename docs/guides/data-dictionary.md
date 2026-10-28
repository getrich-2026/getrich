# 数据字典与 DDL 注释指南

读者：查看数据结构的数据开发者、维护迁移的后端开发者；Agent 修改 DDL 时参考。
用途：从活库生成结构说明、检查契约漂移。表结构真源仍是 `packages/gr-db/src/gr_db/ddl/`，不在 Markdown 里复制字段目录。
以下命令从仓库根目录执行；需要相应数据库连接，真实凭证保存在仓库外或被忽略的本地配置中。

```bash
# 从活库生成 HTML / JSON；--target 可用 pg、ch、all
uv run gr-db docs --target pg --out /tmp/data-dictionary.html --fail-on-drift
uv run gr-db docs --target ch --format json --out - --fail-on-drift

# CI 中检查新增建表或新增字段是否有 COMMENT ON
uv run python scripts/lint_migrations.py --db pg --comments --base-ref origin/dev
```

## PostgreSQL schema 一览

按职责查新表该放哪里；表和字段以 DDL 与生成的字典为准，本表只到 schema 一级。2026-10-28 对照 DDL 核对，新增 schema 时同步本表。

| schema | 内容 | 写入方 | 建立迁移 |
|---|---|---|---|
| `meta` | 证券、期货／期权合约、代码映射、交易日历 | gr-data | 001 |
| `market` | 行情主存 `<asset>_bar_<freq>`、复权因子、估值、停复牌事件 | gr-data | 001 |
| `fundamental` | 估值与财务快照 | gr-data（gr-api 读） | 038 |
| `classify` | 行业体系、行业归属、资产类别 | gr-data（gr-api 读） | 039 |
| `factor` | 风险模型：定义、run、暴露、协方差、收益、覆盖 | gr-data（gr-api 读） | 037 |
| `realtime` | 实时 tick 缓冲 | gr-data | 001 |
| `staging` | 入库中转 | gr-data | 007 |
| `ops` | ETL 作业、数据质量、表归属、导入收据、迁移记账 | gr-data／gr-db | 001 |
| `app` | 业务主库：用户、策略、信号、订单、订阅 | gr-api | 001 |
| `backtest` | 回测产物：run、指标、权益、参数扫描、walk-forward、作业 | gr-backtest／gr-api | 001 |
| `pick` | 选股：上传批次 `batch` 与每日标的池快照 `item` | gr-api | 034 |
| `diag` | 持仓诊断：快照、方案、计算运行、口径版本、分享凭证 | gr-api（数据版本按 D-022 由 gr-data 发布） | 040 |

连接池 `search_path` 只有 `app,market,meta,public`，其余 schema 不在其中；SQL 一律写 schema 全限定名。

## 如何理解结果

- PostgreSQL 字典从活库 catalog 反射，只覆盖 gr-db 明确管理的业务 schema，包含 `diag`，排除 TimescaleDB 内部 schema。
- `--fail-on-drift` 检查契约列与运行时表归属；多个 provider 声明接入能力不等于生产混写。
- `ch` 模式不连接 PostgreSQL，也不能替代 PostgreSQL 契约／归属验证。
- 注释门禁同时覆盖新增建表和 `ALTER TABLE ... ADD COLUMN`；豁免列与解析规则以 `gr_db/docs/ddl_lint.py` 为准。
- HTML／JSON 是生成产物，按需重建，不提交活库快照。访问地址、表行数和服务健康状态应在运行时确认。

实现：`packages/gr-db/src/gr_db/docs/`；CI：`.github/workflows/ci.yml`。
设计理由见 [决策记录](../../.agents/brain/DECISIONS.md) D-006。
实施过程仅在需要追溯时查 [历史计划](../history/data-dictionary-plan.md)。
