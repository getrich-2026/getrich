# GetRich 当前状态

**这个文件是状态快照，可以整体覆写。** 不要在这里追加施工流水账 —— 历史沿革查 `git log`，长期决策和踩坑写 `DECISIONS.md`。

最后更新：2026-08-17 · 分支 `claude/getrich-strategy-signal-api-9496df`（worktree）

---

## 刚完成：选股信号（个股推荐）导入 + 展示 API

按 `getrich-design/strategy-signal/` 的 P0 设计落地，**导入只有函数接口与 CLI，不做前端**。

- **新 schema `pick`**（迁移 `034_pick.sql`）：`pick.batch` 上传批次 + `pick.item` 每日
  全量标的池快照。期货期权字段（`asset_class`/`direction`/`option_type`/`product_code`/
  `product_entry_date`）已建好，解析分支未写。
- **`app.strategies` 加 `strategy_kind`**（`035_*.sql`，可空）：选股接口只认 `'pick'`，
  存量策略不回填就不会误入选股列表。选型理由见 D-024。
- **导入**：`gr_api.services.pick_import.import_picks()`（async）/ `import_picks_sync()`，
  入参可以是 `.csv` / `.parquet` 路径，或直接给 polars / pandas DataFrame；
  CLI 是 `uv run gr-picks import ...`（薄壳，无业务逻辑）。
- **7 个只读接口**：`/v1/pick-strategies`（列表 / 详情 / picks / trading-days）、
  `/v1/picks/latest`、`/v1/picks/by-symbol/{symbol}`、`/v1/admin/pick-batches`。
  严格对齐 `选股展示模块.openapi.json`：不返业绩数字、不返 `score`/`suggest_weight`、
  三种空态（`updated`/`empty`/`not_updated`）可区分且全部 HTTP 200。
- **新包 `packages/gr-tools`**：从外部仓 `lntools` 移植文件系统 / 多格式表格读取 /
  人性化格式化，**无一方依赖的叶子**（D-025）。导入路径靠它的
  `read_frame(all_string=True)` 保住证券代码的前导零。
- **模拟数据**：`packages/gr-api/tests/fixture_picks.py` 生成 30 个交易日 × 20 只的
  全量快照，落成 `tests/fixtures/picks/strategy_picks_30d.{csv,parquet}`（确定性，
  可重新生成）。`test_pick_pg_integration.py` 用它打真库，默认跳过，
  `GETRICH_TEST_PG=1` 时才跑。
- **入池日推算改走快路径**：连续上传时只读上一交易日那一期（O(池子大小)），
  只有漏传 / 日历缺失才回退到扫全量历史。实测 0.07 ms vs 39.8 ms，
  且不再随历史增长（D-024）。

三处刻意偏离设计文档（`strategy_id` 用 UUID、`import_job_id` 不建外键、
`uploaded_by` 可空）的理由写在 `DECISIONS.md` D-024，不要当成实现错误去「修正」。

## 顺带修掉的既有缺陷（都是「静默不干活」型，没有任何报错）

- **Black-Litterman 观点符号被抹掉**（D-027）：先验与观点分别做了互不自洽的
  归一化，先验压过观点五个数量级，`score=-1` 的标的拿到正权重。已去掉归一化，
  并把「协方差退化时退回按方向等权」的判据从异常改成条件数。
  **遗留两个待决口径**：`tau` 目前在后验里精确约掉（无效参数），
  以及 score 直接当预期收益用的量纲标定 —— 都记在 D-027，等定方案再动。
  注意：`BlackLitterman` 全仓只在 `gr_backtest/__init__.py` 被导出，**没有任何
  调用方**，所以这两个口径不阻塞任何在跑的东西。
- **ClickHouse 迁移记账一直是空的**（D-028）：`command()` 拼的 INSERT 没有占位符，
  参数绑不上，静默插 0 行；DDL 是 `CREATE TABLE IF NOT EXISTS`，重放看起来完全
  正常，把记账失效盖住了。已改用 `client.insert()`。
- **`RAW_PARQUET_ROOT` 是死配置**（D-030）：文档写它是 raw 落地根目录的真源，
  代码却只读 `config.yaml`。已改成环境变量优先。
- **`_docker_available()` 被自己的探测命令挡住**（D-030）：`docker info` 实测
  9.75 s，卡在 `timeout=10` 上，5 个集成用例长期静默跳过。换成 `docker version`。
- **数据库容器数据目录改用 named volume**（D-029）：bind mount 在 macOS 上会丢
  POSIX 语义，PG 在 autovacuum 里报 `could not open file`。已改并重建容器。

## 当前基线（2026-08-17 实测）

| 项 | 状态 |
|---|---|
| `GETRICH_TEST_PG=1 uv run pytest` | **2350 passed, 1 skipped, 0 failed** |
| `uv run ruff check` / `format --check` | 通过 |
| `scripts/lint_migrations.py --db pg` / `--db ch` | 通过（35 + 1 个迁移） |
| `gr-db migrate --target all` | 全新库上建成，重跑两边都报 already applied |

唯一的 skip 是 `test_main_loop.py` 里 Windows-only 的 ProactorEventLoop 守卫，
POSIX 上本就不适用。

**这个基线里有 27 个用例是「本来就该跑但从没跑过的」**，不是新写的：5 个 docker
集成（探测命令挡住）+ 11 个 tushare 真实接口（缺凭证）+ 5 个 job 持久化（缺 anyio
marker）+ 选股集成。改动前是 2323 passed / 25 skipped / 1 failed。
**看基线时 skip 数和 failed 数一样重要**（D-030）。

## 已验证（真实环境，非 mock）

- 35 个迁移在空库上建出 `pick` schema 两张表 + `app.strategies.strategy_kind`，重跑幂等。
- 30 天模拟池子经 `import_picks` 落库：漏传一天、空仓一天，入池日继承 / 重置 / 沿用三分支正确。
- `gr-picks import` 的 CSV、Parquet、`--dry-run`、`--overwrite` 四条路径都跑通。
- `uvicorn` 起服务后 7 个接口全部 200，三种空态可区分，4 个安全头齐全，
  管理端未登录 401。
- 造到年度量级（10 策略 × 250 天 × 30 只 ≈ 7.9 万条）后，各接口 P50 仍在 17–36 ms。
- **`holding_trading_days` 首次用真实日历验证**：`entry_date=2026-07-29` →
  `trading_day=2026-08-11` 接口返回 **10**，与 `meta.trading_calendar`（`XSHG`）
  的口径精确一致（自然日是 14），服务日志零 WARN —— 退化路径没走。

## 当前部署（仓库外 `/Volumes/myssd/getrich-docker/`）

- PG 17 + TimescaleDB 2.28.3 / ClickHouse 26.3 / Redis 8.2.8，全部 healthy。
- 三个数据目录是 **named volume**（`getrich_pg_data` / `getrich_ch_data` /
  `getrich_redis_data`），日志与配置仍是 bind mount。理由与代价见 D-029。
  **备份只能走逻辑导出，不要拷数据目录文件。**
- `RAW_PARQUET_ROOT=/Volumes/myssd/data/raw_parquet`（已写进根 `.env`）。
- `meta.trading_calendar` 已灌真实数据：`XSHG`/`XSHE` 各 5342 天
  （3553 个交易日），覆盖 2013-01-01 → 2027-08-17。

旧的 bind 数据目录 `/Volumes/myssd/getrich-docker/.docker/{postgres,clickhouse,redis}/`
（约 7 GB，其中 6.9 GB 是 ClickHouse 自己的 `system.*` 日志表）**还留在盘上没删**，
确认新库无误后可以自行清理。

## P0

（空）

已完成（2026-08-17）：RiceQuant license key 已轮换；`TUSHARE_TOKEN` 已配置，
11 条真实接口契约用例由 skip 转为全部通过；`RAW_PARQUET_ROOT` 已定；
ClickHouse 迁移已验证；bind mount 一致性问题已按 D-029 根治。

## P1

- [ ] **`import_jobs` / `import_job_errors` 两张表全仓没有 DDL**，
      `services/admin_import.py` 却在用 —— 全新库上 `/v1/admin/imports` 必然报错。
      同一模块的 `upsert_strategy()` 还往 `strategies.type` 写值，那列也不存在。
      选股模块因此绕开了导入通道（走函数 / CLI），但这两张表迟早要补。
- [ ] `pick.item.instrument_id` 的回填定时任务还没写。P0 允许为 NULL 不阻断，
      但效果跟踪上线前必须补，否则大量历史记录关联不上行情。
- [ ] **Black-Litterman 的两个待决建模口径**（符号已修好，见 D-027）：
      ① `tau` 在后验里精确约掉，是个无效参数，要生效必须改 Ω 的取法；
      ② score 直接当预期收益（Q）用，量纲上等于把观点置信度隐式拉满，
      是否加标定系数需要先定策略口径。两条都**先定方案再动**。
- [ ] `gr-factor` 至今没有测试；`NPY002` 因此暂时豁免。
- [ ] `market` 表缺 `oi`（持仓量）列，期货策略用不了。
- [ ] gr-data schema 里没有公司行为（分红送转）表，`load_corp_actions()` 显式报错。
- [ ] `apps/backtest-web` 暂停维护：缺 `src/lib/utils`、`src/lib/sanitize`。
- [ ] `apps/web` 45 个既有 ESLint 错误、`tsconfig.app.json` 的 `ignoreDeprecations`
      导致 `npm run build` 失败（`npm run dev` 不受影响）。
- [ ] `polars==1.41.0` 与 `polars-runtime-32==1.41.0` 已被 yanked，需评估升级。
- [ ] 评估 `archive/root-web-scaffold/` 与 `packages/gr-db/archive/legacy-sql/` 的保留期限
      —— 删除前必须明确确认（D-010）。
- [ ] `gr-agent` 仍是空占位包。
- [ ] CI（`.github/workflows/`）仍按旧包名与旧路径写，且还不认识 `gr-tools`。
