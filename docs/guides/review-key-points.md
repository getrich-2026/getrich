# 工程与业务关键点备忘

读者：项目审核与维护者（仅涵盖项目工程与业务口径关键点，不含商业、团队与环境敏感信息）。

用途：沉淀人工审核与架构讨论中发现的核心业务逻辑、版本锁约束与生产运维铁律；只记关键结论，不记流水账。

状态：现行（2026-11-17 建立，2026-11-19 按云端现状与门禁复核）。

---

## 1. 持仓诊断 V1：版本锁、变更影响与生产更新规范

> 记录时间：2026-11-17
>
> 相关实现：[risk_receipts.py](../../packages/gr-data/src/gr_data/db/postgres/risk_receipts.py)、[diagnosis_daily](../../packages/gr-data/src/gr_data/diagnosis_daily/__init__.py)、[diagnostic_publication.py](../../packages/gr-data/src/gr_data/diagnostic_publication.py)、[054_diag_publications.sql](../../packages/gr-db/src/gr_db/ddl/postgres/054_diag_publications.sql)、[056_diag_enhanced_metrics.sql](../../packages/gr-db/src/gr_db/ddl/postgres/056_diag_enhanced_metrics.sql)、[diagnosis_publication.py](../../packages/gr-api/src/gr_api/services/diagnosis_publication.py)、[diagnosis.py](../../packages/gr-api/src/gr_api/services/diagnosis.py)

### 1.1 两类“版本”的区别

| 维度 | 源码版本（`importer_version`） | 数据发布版本（`data_version_id`） |
|---|---|---|
| **锁定机制** | `get_importer_version(require_clean=True)` 仅读取影响 `packages/gr-data/src/gr_data` 与 `packages/gr-db/src/gr_db/ddl` 的最新 Git 提交号，并校验这两个目录无未提交或未跟踪改动 | 日更 `prepare` 生成 `diag-v3-<YYYYMMDD>-daily-<artifact_hash[:16]>`；`artifact_hash` 打包目标日期、历史起点、采集完成时间、`importer_version`、前序版本、表归属、写入前基线指纹、全部 raw/canonical Parquet 哈希与米筐观察 ID |
| **不影响范围** | 修改 `packages/gr-api`、前端 `apps/web` 或 `docs/` **不会**改变 `importer_version` | 底层表无受保护写入时保持不变；API 通过自增列 `publication_seq DESC LIMIT 1` 取最新一条，不依赖字符串排序 |

因此，“固定版本导入 V1”指的是**每次正式采集/发布前固定到一个干净的 Git 提交（或干净 `git worktree`）**，而非把数据停留在某个静态日期。

### 1.2 版本变更或标脏后的业务影响

| 操作入口 | 当版本推进或旧版被标脏（`invalidated`）时 | 设计原因 |
|---|---|---|
| **读取受支持格式的历史结果/报告/分享**<br>（`GET /result`、`/report`、`/data-quality`、`GET /share/{token}/report`） | **正常可读、数值不变**；失效发布的响应中 `publication.status` 标为 `"invalidated"`，`recomputable=false` | 诊断终态产物已固化在 `diag.diagnosis_run.payload` 与 `data_quality`；模型载体必须已记录 `coverage_basis=full_input` |
| **基于旧快照调参重算**<br>（`POST /snapshots/{id}/recompute`） | **拒绝并返回 `409`** | PG 行情与主表按当前状态 `UPSERT` 覆盖，不保留全量历史行版本；拒绝用新数据冒充旧版本重算（[D-022](../../.agents/brain/DECISIONS.md#d-022)） |
| **发起新诊断**<br>（`POST /snapshots`） | 若最新版本有效且滞后 `<= 1` 个已收盘交易日，正常用新版创建；**若最新版本被标脏未重签，全员返回 `503`** | `require_publication` 严格校验最新一条 `data_publication`，**刻意不回退到旧版本** |

早期缺少 `coverage_basis=full_input` 或模型覆盖率的开发载体不在受支持格式内，须基于最新有效版本新建诊断。不得修改旧 run 补标记、默认覆盖率为 1，或恢复已删除的子集折算来伪装兼容。

### 1.3 什么会触发旧版标脏（共享表触发器边界）

以下 12 张表与风险表受输入、风险或归属守卫保护。写入命中已登记的输入头／分区／风险范围时，会将对应头标为 `dirty=true`，并记录发布失效；具体范围以冻结版本的触发器与发布组成记录为准：

- 共享主数据与日历：`meta.instruments`、`meta.symbol_map`、`meta.trading_calendar`、`classify.instrument_category`
- 股票与基本面：`market.stock_bar_1d`、`market.stock_suspend_event`、`market.stock_suspend_coverage`、`fundamental.valuation_1d`、`fundamental.indicator_q`
- 申万行业：`classify.scheme`、`classify.industry_node`、`classify.instrument_industry`
- 风险表与归属：`factor.*`（含 `model_run` / `exposure` / `specific_risk` / `covariance` / `factor_return` / `specific_return` / `model_run_coverage` 等）、`ops.table_ownership`

**关键隐患**：在全品种共库的情况下，ETF、期货、期权或米筐 `v1` / `v2trd` 的更新也可能通过共享主数据或受保护范围使当前 V1 失效。不能仅凭品种或模型名称认定互不影响；`diagnosis-daily` 又要求最新发布有效，因此不能无序裸跑各导入命令。

### 1.4 生产环境更新导数规则的操作准则（如只改 Tushare、米筐未变）

1. **米筐不因 Tushare 改规则而重采或改动**：
   - 历史已入库的米筐 `factor.import_receipt` 仅约束“不得用变更后的源码去重放同一份旧 raw”；
   - 新交易日采集使用新提交的 `importer_version` 正常生成新收据，无需回溯重采米筐；
   - 重签 V1 收口时，`accept_risk_input` 仅校验数据库函数 `diag.risk_run_is_publishable(...)`，可以直接绑定当天已入库的米筐 `v2` `run_id` 与 `receipt_id`。
2. **当前更新范围与未来隔离建议**：
   - 当前云端保留已迁入的完整工作库存量；后续按产品 V1 → V2 的实际需要更新，不因本建议删表、拆库或启动全品种历史回补。V1 日更仅更新沪深 A 股所需基础数据与米筐 `v2`；其他数据新增须单独安排并评估共享表影响。
   - 未来可评估将 V1 服务最小集与研究更新隔离；具体拓扑和迁移方案须另行审核，此项建议不代表已经实施或获准改变数据库边界。
3. **仅改 V1 自身 Tushare 规则时的发布方式**：
   - 提交改动至 Git（保证 `gr-data` 与 `gr-db/ddl` 目录干净）；
   - **用于今天及以后**：下一个交易日正常跑 `gr-data diagnosis-daily run` 即可切换生效；
   - **尚未发布且晚于最新发布日的产物**：源码身份变化后，旧 `prepared.json` 不可继续导入；保留旧产物，在新目录用批准源码重新准备并验收。
   - **已经发布的日期或最新发布已失效**：原生 `prepare` 拒绝目标日不晚于最新发布日，也不能绕过最新发布有效性检查。须另走已审核的同日再验／恢复／重签流程；不得删收据、改日期或改 `prepared.json` 来绕过门禁。
4. **全品种共库环境下的增量更新与收口顺序**：
   - **先采 Raw 预检定截止日 `D`**：先在零写库前提下检查当日（尤其是米筐 `v2`）是否推齐，未齐则退守上一个全齐日，绝不填零或跨日拼接；
   - **先封存后写入**：动库前先留存当前有效 V1 的逻辑备份与 12 表股票指纹；趁当前 V1 `valid=true` 先跑 `diagnosis-daily` 将 V1（含米筐 `v2`）推进至 `D`，再按 `指数/ETF/期货 → Tushare 期权 → 米筐期权 Greeks/历史参数 → 米筐 v2trd/v1` 依赖顺序写入（其中 Tushare 期权须在米筐期权之前，先建合约身份；米筐期权历史按每批 `<= 10,000` 合约日分批）；
   - **先完成受控再验**：冻结原批准源码、原 raw／canonical 及原验收记录，重新核对 12 项基础输入；当日风险五件套和完整 coverage 必须与原件重算值／原验收二进制逐值一致，并核对模型、日期、因子轴、单位及 run／receipt／variant／观察／准入链。缺原件、数值漂移或身份不一致即停，不扩大原证券或指标范围。`accept_risk_input` 的准入检查不能替代这项数值验证。
   - **同屏障重签收口**：仅在上述再验通过后，在 `BARRIER_KEY`（`7342061105`）排他锁与同一外层事务内重查基线及预期 head revision，以 CAS 登记本轮收据与显式新批次／数据版本；逐项调用 `accept_input`、`accept_risk_input` 后再 `publish_version`，提交前核对有效性。受控流程要求新 partition 时显式登记，不能只改 evidence／验收 JSON 或调用 `accept_*` 清 `dirty` 来制造通过；原版本和失败记录保留。
   - **超表写库附加保护**：`diag.publication_is_valid` 会检查 `_timescaledb_internal` 下全部 chunk 是否都带 `diag_chunk_truncate` 触发器；非受保护超表写库事务应开启 `SET LOCAL timescaledb.enable_event_triggers = 'on'`，防止新建 chunk 漏挂触发器导致发布失效。
