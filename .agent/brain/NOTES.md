# GetRich 当前状态

**这个文件是状态快照，可以整体覆写。** 不要在这里追加施工流水账 —— 历史沿革查 `git log`，长期决策和踩坑写 `DECISIONS.md`。

最后更新：2026-08-30 · 分支 `feat/data-ingest-tushare-datayes`（未合回 `dev`）

---

## 刚完成：数据字典生成器与 DDL 注释门禁

- `gr-db docs --target pg|ch|all` 生成活库数据字典；`--fail-on-drift` 校验 PG 契约与归属。
- 注释门禁检查新增建表及 `ALTER TABLE ... ADD COLUMN`；真库 85 张表、1,048 个字段注释完整。
- 只覆盖 gr-db 的 11 个业务 schema，排除 TimescaleDB 内部表与仓外 `diag`；`ch` 模式不执行 PG 漂移校验。
- 匿名快照：`http://45.142.166.254:3000/data-dictionary.html`；更新命令：
  `uv run gr-db docs --target pg --out apps/web/public/data-dictionary.html --fail-on-drift`。后续迁入登录态页面。

---

## 进行中：tushare 全域 + datayes CNE6 数据接入（P0–P2 已完成）

目标是把 `getrich-design/portfolio-analysis/`（持仓诊断）从「无数据可算」推到
「主要指标可出数」。方案分 P0–P6，**已完成 P0、P1、P2**，四个 commit 在
`feat/data-ingest-tushare-datayes` 上。

已关闭的缺口：**G2**（因子模型，最大阻塞）、**G3**（估值快照）、**G5**（资产类别）、
**G1 的一级部分**（申万 2021 一级行业，从 datayes 暴露表派生）。

新增三个 schema，DDL 在 `gr-db` 的 `036`–`039`：

| 迁移 | 内容 |
|---|---|
| `036_market_ext.sql` | `market.adj_factor_ts`（复权因子明细，可独立回补对账） |
| `037_factor.sql` | 8 张表：model / definition / model_run / exposure / covariance / factor_return / specific_risk / specific_return |
| `038_fundamental.sql` | `valuation_1d`（估值快照）+ `indicator_q`（季度指标，PIT） |
| `039_classify.sql` | scheme / industry_node / instrument_industry / instrument_category |

**四处刻意偏离设计文档**（不是实现错误，理由见 D-035）：`cov_flat` 用
`DOUBLE PRECISION[]` 而非 `REAL[]`；`model_run` 加 `units JSONB` / `calibrated` /
`factor_set_hash` 三列。

### 已实测落库（真库，非 mock）

| 表 | 行数 | 备注 |
|---|---|---|
| `fundamental.valuation_1d` | 1,433,283 | 2025-08-01 → 2026-08-28；`total_mv` 中位数 65.25 亿元；`pe_ttm` 亏损股 NULL 39.8 万行 |
| `market.stock_daily_basic` | 1,433,283 | 未提升的字段进 `raw_payload` JSONB |
| `market.adj_factor_ts` | 1,437,673 | |
| `classify.instrument_category` | 5,890 | 5,551 当前有效；15 个标的缺 `list_date` 已跳过并记 dq |
| `meta.instruments` | 27,654 | |

### 全量数据已导入（2026-08-31 实测）

`DATAYES_TOKEN` 已配置，两个源的全量历史都已落库。**下面的行数是真库实测值。**

| 表 | 行数 | 区间 |
|---|---|---|
| `market.stock_bar_1d` | 12,800,645 | 2013-01-04 → 2026-08-28 |
| `market.index_bar_1d` | 25,927,848 | 同上 |
| `market.future_bar_1d` | 2,426,406 | 同上 |
| `market.stock_daily_basic` | 12,709,865 | 同上 |
| `market.adj_factor_ts` | 13,389,771 | 同上 |
| `fundamental.valuation_1d` | 12,709,865 | 同上 |
| `factor.exposure` | 6,132,348 | **2021-11-01** → 2026-08-28 |
| `factor.specific_risk` | 6,031,475 | 2021-12-01 → 2026-08-28 |
| `factor.specific_return` | 6,030,370 | 同上 |
| `factor.covariance` / `factor_return` | 各 1,151 | 同上 |
| `classify.instrument_industry` | 6,191 | 5,743 个标的 |
| `classify.instrument_category` | 5,890 | 5,551 当前有效 |
| `meta.trading_calendar` | 10,710 | 2013-01-01 → 2027-08-30 |

不变量全部通过：数组长度（exposure=52 / cov_flat=1378 / ret_vector=52）零违例、
`specific_var` 非负、`high<low` 零行、`adj_factor` 无缺失、行业区间零重叠。
量纲抽查：`specific_var` P50 = 733.7 → SRISK ≈ 27.1% 年化波动率（预期 20–45）；
`total_mv` P50 = 56.96 亿元。归属：tushare 9 张表、datayes 9 张表。

**datayes 的真实数据起点是 2021-08-02**（2021-07 及更早全空，见 D-044）。

### ⚠️ 三个已知缺口，都需要人来决定

1. **`factor.*` 的窗口从 2021-12 起，不是 2021-08**（见 D-045）。
   通联在 **2021-11 换了行业体系**（申万 2014 的 49 因子 → 申万 2021 的 52 因子），
   且五张表的切换不在同一天：exposure 在 11-01 已切换，而 factor_ret / covariance
   的 11-01 仍是旧体系。同一个 `model_run` 内因子集合必须恒定、五张表必须逐日
   一致，所以 2021-08~11 共 4 个月（约 5%）暂未入库。
   要补齐得先决定 `factor.definition` 怎么容纳两套体系（它按 `model_id` 建、
   `UNIQUE(model_id, ordinal)`），那是 `持仓诊断_表与接口设计.md` §5.2 的范围。

2. **`factor.exposure` 有 100,873 行孤儿数据**（2021-11-01 → 11-30）。
   来自定窗口之前的一次试跑：exposure 已提交、`factor_return` 才报错。
   后果是 2021-11 那个月**只有 X，没有 F / D / f**，对该月做诊断会拿到不完整的
   `DataPack`。清理命令（**需要人确认后执行，属对业务主库的删除**）：
   ```sql
   DELETE FROM factor.exposure WHERE trading_day < DATE '2021-12-01';  -- 100873 行
   ```

3. **`calibrated` 仍是 false**，下游必须据此标 `degraded`。解除它的唯一门槛是
   P6 的 `r = 100·X·f + u` 五表自洽校验。

### 运维要点（下次全量重跑必看）

- **必须按月分批**：`gr-data ingest <provider> --months 2021-12..2026-08`。
  不分批会被 OOM killer **静默**杀掉 —— 无输出、无落库、退出码 0（D-046）。
- datayes exposure 串行抓要 10 小时，瓶颈是服务端响应时间而非限流；
  4 并发可压到 1.5 小时（D-047）。并发抓取**没有进仓库代码**，需要先讨论。
- `config.yaml`（gitignore 内）已建好，`providers.datayes.start_date = 20210802`。

### 剩余分期

- **P3** `finance` 10 张财报表（`_PeriodFetcher`）
- **P4** `reference` / `macro` / `sentiment`
- **P5** etf / option 行情扩容
- **P6** 巡检：`r = 100·X·f + u` 五表自洽校验。这是把 `model_run.calibrated`
  置真、下游解除 `degraded` 的**唯一门槛**，建议插到 P3 前面（只要 6 天，
  投产价值高于 P3 的 15 天）。

`G1 的正解`仍是 tushare 的 `index_classify` + `index_member_all`（三级树、官方码、
真实生效日期），但这两个接口在 `getrich-design` 里**没有字段目录**，已记为待补文档。

---

## 前端工具链与结构整顿已完成

`apps/web` 现在是 **Vite 8.2.1（Rolldown）+ Tailwind 4.3.3（CSS-first）+
TypeScript 6.0.3 + React 19.2.8**。`npm run lint` 与 `npm run build` 全绿，
dev / preview / HMR / `/v1` 代理均实测通过。
CI `.github/workflows/web.yml` 的 Node 已从 20 钉到 24。

决策与踩坑分别见 **D-031**（Vite 8 = Rolldown）、**D-032**（`any` 掩盖的契约错位）、
**D-033**（Tailwind v4 迁移）、**D-034**（两套 API 层合并）。

结构上的两处整顿：

- **Tailwind v4**：删掉 `tailwind.config.js` 与 `postcss.config.js`，主题写在
  `src/index.css` 的 `@theme` 块里，构建走官方 `@tailwindcss/vite` 插件。
  `autoprefixer` / `postcss` / `tailwindcss-animate` 三个直接依赖已移除
  （v4 内置前缀处理；动画换成 v4 原生的 `tw-animate-css`）。
- **API 层合并**：`src/lib/api.ts` 已删除，全部统一到 `src/api/`（AGENTS.md §5）。
  两层原本 9 个函数完全重复，且**哪一边都不完全对**——细节见 D-034。

顺带修好的存量断裂（这些在 `dev` 上早就是坏的）：`tsconfig` 里非法的
`"ignoreDeprecations": "6.0"` 让 `tsc -b` 长期失败；`src/components/ui/` 里 4 处
Tailwind v4 的 `--spacing()` 语法在 v3 项目下输出成非法 CSS、规则从未生效
（**升到 v4 后已按 shadcn 原样恢复成 v4 写法，产物确认为合法 CSS**）；
`src/lib/api.ts` 不发 `X-User-Id` 头导致首页「我的策略」板块恒为空。

---

# ⚠️ 待讨论：前后端接口契约的系统性错位

**这一章是给团队讨论用的，不是已完成事项。** 下面每一条都已对着
`packages/gr-api/src/gr_api/services/` 的源码 **和真库实测响应**逐字段核对过，
不是猜测。前端侧已做了能做的订正，但**根因在于前端类型是照设计稿写的、
没有一份双方共同认可的契约真源**，这个问题不解决还会继续复发。

## 背景：问题是怎么暴露出来的

`src/lib/api.ts` 过去所有接口都写 `request<any>`。把 `any` 换成 `src/types/` 里
已有的真实类型后，**一次性炸出 83 个类型错误**。逐条核查后发现：类型没写错的地方，
是**页面在读后端从来不返回的字段**。也就是说，`any` 不是「还没来得及写类型」，
而是**关掉了前后端契约的唯一一道自动检查**——这些错位全都不会报错，
只会在页面上渲染成空值、`undefined` 或 0，看起来像「数据还没灌」。

## A. 前端类型写错 / 写漏（已按后端订正，仅供复核）

| 位置 | 前端原来的写法 | 后端实际返回 |
|---|---|---|
| `TradeRecord` | 「开平配对回合」：`entry_price`/`exit_price`/`holding_days`/`direction` | **单笔成交**：`action`/`price`/`quantity`/`realized_pnl`/`executed_at`/`fee`/`slippage` |
| `Strategy`（列表项） | 有 `category` | **没有** `category`（只有详情接口 join 了分类）；反而漏了确实会返的 `description`、`cover_image` |
| `SignalDetail.tsx` | `s.is_executed` | 实际在 `s.user_state.is_executed` |
| `SignalDetail.tsx` | `market_snapshot.ma5` / `rsi14` | 实际在 `market_snapshot.indicators` 下，且是 **`rsi_14`** 不是 `rsi14` |

`TradeRecord` 这条最值得注意：**前端按「回合」建模、后端按「成交」建模**，
这不是字段名笔误，是双方对同一个业务对象的粒度理解不一致。成交表格已按后端
改成「成交价 / 数量 / 已实现盈亏」，但**产品上到底要不要展示配对后的回合，
需要产品与后端一起定**。若要，得后端补一个回合聚合接口。

## B. 后端缺字段：前端已按设计稿做了 UI，后端没实现

`/v1/signals/{id}` 缺以下 5 个字段，涉及 4 块 UI。前端已改成占位符并留
`TODO(后端)` 注释保留布局，**补齐后按注释恢复即可**：

| 字段 | 前端用途 |
|---|---|
| `reason_detail.spread_std` | 「触发原因」四格里的「标准差」 |
| `market_snapshot.basis` | 「触发时刻行情」里的「基差」卡片 |
| `historical_performance.best_return` / `worst_return` | 「最佳收益 / 最差收益」两条进度条（整块已隐藏） |
| `related_signals`（顶层） | 「同策略近期信号」整个 Section（已隐藏） |

**需要决策**：这些是当初设计稿画了但后端没做，还是产品上已经砍掉？
如果要做，`related_signals` 建议不要塞进详情接口，改由
`/v1/signals?strategy_id=` 单独拉，避免详情接口越长越胖。

## C. 枚举取值域对不上（**尚未修，风险最高**）

真库实测返回的值**超出**前端类型声明的联合类型：

| 字段 | 前端类型声明 | 真库实测值 |
|---|---|---|
| `signal_type` | `'entry' \| 'exit' \| 'adjust' \| 'alert'` | **`'stock'`** |
| `urgency` | `'critical' \| 'high' \| 'medium' \| 'low'` | **`'normal'`** |

TypeScript **拦不住这个**（类型是编译期的，后端返什么是运行时的）。后果是页面
静默走进兜底分支：信号类型显示成「预警」、紧急度显示成「普通」，**不报错，
但显示的是错的**。

**需要后端确认** `signals.type` 与 `signals.urgency` 两列的真实取值域，再决定是
改前端类型还是在后端做归一化。**在确认之前不要擅自改前端的联合类型**——
现在的类型至少还标记着「设计意图」，改成实测值就把问题永久掩埋了。

## D. 根因与建议（**这条最需要讨论**）

前端 `src/types/` 是照设计稿 / openapi 草案写的，不是照后端实现写的。
证据：类型文件里带「tips: 文档未给出枚举值，根据 response 示例推断」这类注释的
字段，基本都是本次出错的重灾区。

而后端这一侧同样没有可机读的契约：**55 条路由无一声明 `response_model`**，
全部直接返 `dict`，`/openapi.json` 的响应 schema 是空的。也就是说
**当前双方都没有契约真源**，只有各自的一份口头理解。

可选方案（择一，需要团队定）：

1. **后端出 OpenAPI，前端脚本生成类型**。FastAPI 自带 `/openapi.json`，
   前端用 `openapi-typescript` 生成 `src/types/generated.ts` 并纳入 CI 检查。
   一劳永逸，但要求后端的 response_model 认真写全（目前多数接口直接返 `dict`，
   **schema 是空的，得先补**）。
2. **维持手写类型，但加一道契约测试**：前端存一组真实响应样本，用
   zod/valibot 在 CI 里校验样本与类型一致。成本低，但样本会过期。
3. 维持现状，靠人工同步。**不推荐**——本次 83 个错误就是这么攒出来的。

倾向方案 1，但前置条件是后端先补 `response_model`。

---

## 本地开发环境已跑起来（2026-08-18）

前后端都在跑，本地 `getrich` 库已从零建好并灌入模拟数据：

- **建库**：本地 PG 之前是空库，`uv run gr-db migrate --target pg` 一次建成 35 个迁移。
  ClickHouse 与 Redis 当前没在监听，API 本身不依赖它们能起（Celery worker 需要）。
- **服务**：`uv run uvicorn gr_api.main:app --reload --port 8001`（端口取根 `.env` 的
  `WEB_PORT=8001`，**不是** AGENTS.md 示例里的 8000）+ `cd apps/web && npm run dev`（3000）。
  `apps/web/node_modules` 原本不存在，已 `npm install`。
- **前端走同源代理**：`vite.config.ts` 加了 `server.host='0.0.0.0'` +
  `proxy: { '/v1': 'http://127.0.0.1:8001' }`，`apps/web/.env.local`（gitignore 内）里
  `VITE_API_BASE_URL=/v1` 用相对路径。本机与外网 IP 访问都不必改这个值，也不触发 CORS，
  因此根 `.env` 的 `WEB_CORS_ORIGINS` 不用为外网访问加条目。
  `VITE_DEMO_USER_ID` 填 `demo@getrich.io` 的 id。
- **模拟数据**：3 条 `STR_DEMO_*` 策略（1 选股 + 2 择时），选股那条挂着
  `tests/fixtures/picks/` 的 30 天池子（29 批 / 560 条，漏传 07-14、空仓 07-28），
  三条都有一年净值曲线 / 业绩快照 / 月度收益 / 成交流水 / 信号。
  `meta.instruments` 已登记 fixture 的全部代码，`instrument_id` 映射 560/560 成功。
  灌数据的脚本是一次性的，没进仓库；重灌按 `STR_DEMO_` 前缀清理后重跑即可。
- **实测**：`/v1/strategies*` 的 9 个 GET + `/v1/pick-strategies*`、`/v1/picks*` 的
  9 个 GET 全部 200，CORS 预检与 4 个安全头齐全。

顺带修掉：`get_strategy_detail` 的 creator 只 `SELECT id FROM users`，`creator.name`
恒为空串（`users.name` 明明存在，注释里写的「字段未知」在 011 建表后已过期）。
`avatar` / `bio` 全仓无处可取，仍是空串占位。

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

## 当前基线（2026-08-30 实测）

| 项 | 状态 |
|---|---|
| `uv run pytest` | **2395 passed, 24 skipped, 0 failed** |
| `uv run ruff check` / `format --check` | 通过 |
| `scripts/lint_migrations.py` | 通过（39 pg + 1 ch） |
| `gr-db migrate --target pg` | 39 个迁移全部 applied，重跑幂等 |

24 个 skip 里：6 个是缺 `DATAYES_TOKEN` 的 live 契约用例（见上文），
其余是缺 `GETRICH_TEST_PG` 的选股集成、缺凭证的其它 live 用例，
以及 `test_main_loop.py` 里 Windows-only 的 ProactorEventLoop 守卫。

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

- [ ] **前后端接口契约错位 —— 详见上方「⚠️ 待讨论」整章**，此处只列待办：
      C 类枚举取值域（`signal_type` 实测 `stock`、`urgency` 实测 `normal`）**尚未修**，
      需后端先确认取值域；B 类 5 个缺失字段待后端补；D 类契约真源方案待team定
      （倾向让后端补 `response_model` 后由 OpenAPI 生成前端类型）。
- [ ] **gr-api 的 55 条路由无一声明 `response_model`**（实测
      `grep -rc response_model packages/gr-api/src/gr_api/routers/*.py` 全为 0），
      全部直接返 `dict`，因此 `/openapi.json` 里响应 schema 是空的 ——
      这是上面 D 类方案 1 的前置条件。
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
