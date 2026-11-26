# GetRich 当前状态

读者：接续任务的 Claude／Codex／Antigravity；维护者也可用它快速定位当前状态。
最后整理：**2026-11-26**（Asia/Shanghai）。已完成项已移出或归档至 [2026-11 阶段里程碑归档](../../docs/history/2026-11-milestones-archive.md)，关键长期取舍写入 [DECISIONS.md](DECISIONS.md)。

## 开始任务

1. 先读根 `AGENTS.md`，再读本文「当前状态与 V2 进展」。
2. 按任务查 [待决问题](../../docs/plans/backlog.md)、[决策主题索引](DECISIONS.md) 与 [V1 发布切换指南](../../docs/guides/v1-release-cutover.md)。
3. 其余文档从 [文档目录](../../docs/README.md) 定位。

---

## 当前状态与 V2 进展（2026-11-26，Asia/Shanghai）

- **V1 封版与线上稳定运行（`v1.0.0`）**：双仓已打不可变标签 **`v1.0.0`**（`getrich@944a192`、`getrich-design@7f57244`）；云端 `/srv/getrich/current/{app,etl}` 运行隔离副本，运维脚本收口至 `/srv/getrich/ops/`（`deploy-release.sh`、`getrich-api.service`、`run-v1-daily.py`、`run-backup.py`、`run-health.py`），配置拆分为 `api-prod.env`（`APP_ENV=staging`、`STRICT_MODE=true`、`GETRICH_DIAG_PUBLICATIONS_ENABLED=true`、`GETRICH_V1_DIAGNOSIS_ONLY=true`、`GETRICH_ALLOW_MOCK_AUTH=false`）与 `data-prod.env`。晨间 T+1 定时器自动推进最新有效发布（2026-11-25 晨间已推进至 `diag-v3-20261123-daily-ce27ffc2663dd823`，5,224 只沪深 A 股、14 组成 `dirty=false`、`calibrated=false`），滚动逻辑备份与巡检均全绿。**运维提醒**：米筐授权剩余约 14～15 天，须到期前续期。
- **V2 研发进展（`dev`，批次 2A + 2B + 深化批次 A/B2/B3 + C0 补测）**：
  - **本机数据库重命名**：本机 Docker PG 18 已将 `getrich_v2` 重命名为 `getrich`（63/63 迁移，隔离发布 `local-v4-bench-47202035a07c95f3`），保留 `getrich_v1`（57/57 迁移）；本地 V2 API 运行在 `127.0.0.1:8002`（指向 `getrich`），V1 API 运行在 `127.0.0.1:8001`（指向 `getrich_v1`）。
  - **批次 A 已提交（`1bb5170`）**：交付 `holding_risk.py`、`GET /report?detail=holdings`、`HoldingsReport.tsx` 与分享双层白名单；修复独立审核四项高优问题（截断分享原因按 `reason_code` 脱敏防 `instrument_id` 外泄、重复持仓 `[155×3 vs 1071]` 与 `normalize_plan` 逐行顺序对齐、强制 `declared_metrics`/`model_coverage`/`|sum(risk_share)-1|<=1e-4` 守恒核验、表头精确区分负差值与负风险贡献），首版收起无差异“标准/专业”切换按钮。
  - **批次 B2 / B3 实现并完成双隔离库验收（待提交）**：
    - B2：新增 `import_admitted_delistings`（沪深 A 股退市范围筛选与仓外审计 JSON，344 条原件准入 339 条、排除 5 条 B 股/范围外、0 未映射）、补齐已核实非实施分红进度（`股东提议`、`停止实施`、`股东大会未通过`）、`import_total_return` 与日更事务开启 `timescaledb.enable_event_triggers='on'`、新增 `diagnosis_daily/replay_inputs.py`、`GET /options` 白名单投影（回放摘要 $O(1)$）。
    - B3：升级 `PAYLOAD_SCHEMA_VERSION = "7.6"`（向下兼容 `7.5`），新增 `read_benchmark` 结构化状态、`period_comparison`（严格 `S < d <= E`）、单日 `replay_start == as_of` 422 拦截、`recompute_snapshot` 按方案复用 `replay_state`（切基准/裁窗零次调用回放，混合不可用方案不误抛 409）、报告回撤路径解读及前端基准切换。
    - 独立隔离库验收（`getrich_diag_api_contract` + `getrich_diag_b2_b3_acceptance`，均已清理）：11/11 API PG 集成测试通过；同包零写重放、失败注入回滚与 `publication_is_valid` 通过；P1（243 点、末值 `1.045610068`）、P6（`2025-02-06`～`2025-03-24`，31 点，03-21 退市截断）及 5/5 在市示例组合（P1–P5，扩面由 1/5 → P2 阶段 2/5 → 11 股阶段 5/5）全部通过独立复算。
  - **批次 C0 补测完成（C1/C2 保持暂缓）**：沪市 `2026-10-01`～`2026-11-25` 共 35 个开市日（Tushare `index_weight` 命中率 1/35 ≈ 2.86%）；米筐 `index_weights_ex('000300.XSHG')` 日度更新且反映 6 月调样（19 进 19 出），原件与汇总已留存仓外 `/Volumes/myssd/data/getrich-validation/c0-index-weights-20261126/`，但属“米筐估算日权重”口径且账号近期到期，待产品确认口径与授权后再决策 C1/C2。
  - **批次 2A（`057`）**：`057_diag_v4_model_metrics.sql`（12 项模型指标白名单 + L4 最小扭转全方向守恒与条件数舍入预算预检）、`gr-data` `diagnosis-daily` 默认契约升级为 `diag-publication-v4`、`gr-api` 12 项模型指标与 `rebalance_holding` / `rebalance_amount` 客观对比已合入 `dev` 并通过隔离验收。
  - **批次 2B（`058`～`061`，`557d37d`）**：新增 DS06 实施分红（`finance.dividend` / `finance.dividend_coverage`）、DS07 退市截断（`market.stock_delisting`）、DS08 全收益基准（`market.index_total_return_1d`）、PA-11 个股 Beta、PA-12 组合回放及 `/report` 图表读取，`PAYLOAD_SCHEMA_VERSION = "7.5"`。本机 127.0.0.1 运行 V1（`8001` / `getrich_v1`，57/57 迁移）与 V2（`8002` / `getrich_v2`，63/63 迁移，隔离发布 `local-v4-bench-47202035a07c95f3` 有效），启停见仓外 `getrich-local-apps/api-control.py`。
  - **回归修复与旧表清理（`fc8a303` + `062`）**：2A 高条件数截面测试允许最小扭转不收敛或方差不守恒两种拒绝原因（随 BLAS/LAPACK 数值实现而定），API 仍返回 `unavailable/data_not_validated`；修复 Tushare 股票开/收盘价越界、未知上市状态、损坏日历（含期货日历）透传 `CorruptRawError`、`OwnershipManager.claim` 强制换源日志与 `force=False` 冲突只读快速路径（防全局锁 `7342061105` 泄漏）并补齐真 PG 18 集成测试；`PgBarLoader` 复权因子查询已从废弃表 `market.stock_adj_factor` 切换至 `market.adj_factor_ts`；新增幂等迁移 `062_drop_legacy_tables.sql` 清理 `007_insight.sql` 遗留表/视图、`ops.{users,api_keys}`、`app.signal_batches` 与 5 个空日线连续聚合视图，同时移除旧归档 `packages/gr-db/archive/` 与零引用 OpenAPI 草案。
  - **并行边界（[D-032](DECISIONS.md#d-032)）**：线上 `/srv/getrich` 与云端 `getrich` 准生产库保持 `v1.0.0`（57 迁移）原封不动；V2 新 DDL 与实验写入仅在本地或独立隔离库验证，待授权后再安排云端升级与扩大 2B 股票覆盖。
- **存储瘦身备忘：`factor.model_run_coverage`（2026-11-25 本机 `getrich_v1`/`getrich_v2` 实查）**：该表当前占约 **24 GB**（表 22 GB + 索引 2.4 GB，约 4,277 万行 / 11,658 个历史 `model_run`），但日常 `v2` 单模型日更仅增约 **3 MB/天（~0.7 GB/年）**，现阶段按原逻辑保留不改表。后续若服务器磁盘吃紧，全仓读取方仅读 `run_id`/`instrument_id`/`trading_day`/`status` 四列（占行 ~7%），而 `evidence` JSONB 均值约 **350 B/行（占 65%）**；若改为**仅异常行保留 `evidence`、正常 `included` 行存 `{}`**（完整快照已在仓外 raw Parquet 留存），可省约 14～15 GB 且不影响覆盖率与发布门禁。**注意**：该表挂有 054 保护触发器，严禁直接 `DELETE`/`TRUNCATE`，须走受控迁移与重放方案。

---

## 运行环境与检查约定摘要

- **Python / 工具链**：最低 Python 3.11（开发默认 3.12）；依赖统一用 `uv`；类型检查统一用 `basedpyright`（本地 auto、CI 锁定模式 `CI=true uv run --frozen basedpyright`）；默认 `GETRICH_WORKER_BACKEND=inproc`，CI 默认仅启动 PG（手动 `extra_services` 启 CH/Redis），共用真库测试须标 `xdist_group("shared_pg")`。
- **数据路径与本机环境（2026-11-25 清理后）**：正式历史 raw 位于仓外 `$RAW_PARQUET_ROOT`（[D-028](DECISIONS.md#d-028)）；旧本机 `getrich`（049）库及 11 月份历史中间验证/回补目录已清理，本机保留 `getrich_v1`/`getrich_v2`、11-19 全库冷备 `getrich-current.dump` 及最新验收目录 `/Volumes/myssd/data/getrich-validation/v2-regression-20261125/`。
- **未激活/暂停模块**：`apps/web` 在 V1 冻结不部署；`apps/backtest-web` 暂停维护；`packages/gr-agent` 为空占位包。

---

## 最近验证边界（2026-11-25，macOS / Python 3.12）

- **V2 回归全量基线**：离线全仓 `uv run --frozen --no-sync pytest -m 'not live_sdk' -n 4 --dist loadgroup -q` 4,504+ 通过（详细上轮 4,498 离线 + 222 隔离 PG 逐节点覆盖见仓外 `/Volumes/myssd/data/getrich-validation/v2-regression-20261125/acceptance.md`）；审核修复补跑 Docker PG 18 集成测试 167/167 通过（含 `test_ownership_pg.py` 4 项），沪深三股 1,503 条真实样本归一化及 V2 253 点只读回放与 3 条全收益基准 Beta 复算均通过。
- **历史记录注意**：历史文档中的主机路径、服务健康、行数与测试数字均属当时快照，不代表实时状态；执行前按实际配置与活库复核。

---

<a id="rq-three-model-history-20261022"></a>

已入库的米筐 `units_evidence` 引用本锚点，原章节现位于 [米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md#rq-three-model-history-20261022)。

## 文档维护

- `AGENTS.md`：执行规则；本文：当前状态；`DECISIONS.md`：仍有效的取舍与防错理由。
- `docs/guides/`：怎么用；`docs/plans/`：未决问题与实施计划；`docs/history/`：已完成与历史验收材料。
