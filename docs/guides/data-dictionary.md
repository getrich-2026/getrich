# 数据字典与 DDL 注释指南

读者：查看数据结构的数据开发者、维护迁移的后端开发者；Agent 修改 DDL 时参考。
用途：从活库生成结构说明、检查契约漂移。表结构真源仍是 `packages/gr-db/src/gr_db/ddl/`，不在 Markdown 里复制字段目录。
以下命令从仓库根目录执行；需要相应数据库连接，真实凭证保存在仓库外或被忽略的本地配置中。

2026-10-29 按用户确认采用新库初始化基线：字段、最终约束和索引已合入所属 CREATE 文件，历史增量编号保留占位，避免打断连续编号及既有引用。压缩参数仍须在超表创建后设置，风险证据触发器在依赖表就绪后建立。此基线不支持旧库就地升级，迁移改为从 raw 重新入库（[D-006](../../.agents/brain/DECISIONS.md#d-006)）。

`042_complete_catalog_comments.sql` 已将原动态兜底展开为显式 COMMENT，覆盖当前实际受管表，避免仅按相同列名猜测其他表／未来表语义，并允许静态门禁逐字段核对。已确认的代码、用户身份和模型时间错义已修正；存量通用说明不代表真实供应商字段及单位已逐项验收，双向比对仍按 backlog 执行。

风险模型专用的 `factor.dataset_variant`、`factor.import_receipt`、`factor.import_checkpoint` 在 037 中直接建表，其外键、不可变校验及绑定触发器在 049 中完成；不再创建对应的 `ops` 表。`ops.etl_job_run`、`ops.data_quality_check`、`ops.table_ownership`、`ops.schema_migrations` 继续承载通用运维。三张风险证据表按单表单源登记归属，capture 独立提交时保留自身归属，业务失败只回滚业务事务内的新归属。历史备份中的旧 `ops` 表须另行映射，不自动移动旧库。

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
| `factor` | 风险模型：定义、run、五件套、覆盖、配置身份、收据、检查点与绑定 | gr-data（gr-api 读） | 037 |
| `realtime` | 实时 tick 缓冲 | gr-data | 001 |
| `staging` | 入库中转 | gr-data | 007 |
| `ops` | 通用 ETL 作业、数据质量、表归属、迁移记账 | gr-data／gr-db | 001 |
| `app` | 业务主库：用户、策略、信号、订单、订阅 | gr-api | 001 |
| `backtest` | 回测产物：run、指标、权益、参数扫描、walk-forward、作业 | gr-backtest／gr-api | 001 |
| `pick` | 选股：上传批次 `batch` 与每日标的池快照 `item` | gr-api | 034 |
| `diag` | 持仓诊断：快照、方案、计算运行、口径版本、分享凭证 | gr-api（数据版本按 D-022 由 gr-data 发布） | 040 |

连接池 `search_path` 只有 `app,market,meta,public`，其余 schema 不在其中；SQL 一律写 schema 全限定名。

## 如何理解结果

- PostgreSQL 字典从活库 catalog 反射，只覆盖 gr-db 明确管理的业务 schema，包含 `diag`，排除 TimescaleDB 内部 schema。
- `--fail-on-drift` 检查契约列与运行时表归属；多个 provider 声明接入能力不等于生产混写。
- `ch` 模式不连接 PostgreSQL，也不能替代 PostgreSQL 契约／归属验证。
- 注释门禁同时覆盖新增建表和 `ALTER TABLE ... ADD COLUMN`；豁免列（`SELF_EXPLANATORY_COLUMNS`，字典漂移检查共用）与解析规则以 `gr_db/ddl_lint.py` 为准。
- HTML／JSON 是生成产物，按需重建，不提交活库快照。访问地址、表行数和服务健康状态应在运行时确认。

实现：`packages/gr-db/src/gr_db/docs/`；CI：`.github/workflows/ci.yml`。
设计理由见 [决策记录](../../.agents/brain/DECISIONS.md) D-006。
