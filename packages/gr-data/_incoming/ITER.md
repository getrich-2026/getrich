# 迭代日志 (ITER.md)

本仓库的迭代记录。**每次迭代必须追加一条**，最新在上。

标题格式（精确到分钟，本地时间 Asia/Shanghai）：
`## YYYY-MM-DD HH:MM — <事件标题>`

---

## 2026-07-31 02:35 — 接入 Tushare Pro（raw + ingest 纵切片）

把此前在重构前代码上开发的 Tushare 导入，按本仓库四层架构重新实现：`raw/tushare`（client + 8 个 fetcher，逐交易日调用、按自然月分区落 parquet）与 `ingest/tushare`（6 个 importer，写 `meta.*` 与 `market.{stock,index,future}_bar_1d`），并注册进 `raw`/`ingest`/`cli`/`config.example.yaml`。新增 `docs/providers/tushare.md`，补 `docs/conventions/symbol-mapping.md` 的 tushare 行，`tushare_api_design.md` 补齐 `stk_limit` 章节。

按 `tushare_integration_plan.md` 的既有决策对齐：`BJ→XBSE`（D9）、`tushare` 列为主依赖（D9/§7.1）、token 走 `TUSHARE_TOKEN`（D9）。`enabled.ingest.tushare` 默认置空——这些目标表现属 yinhe，启用等于该方案标为高风险的 P5「切主源」，不能由默认配置隐式打开。

关闭 §6.2 / D8 标记的「实现前必须核对单位」待办：核对三家既有 provider，ricequant（`volume`/`total_turnover`）与 insight（`volume`/`value`）原生即股/元且均原样透传，故 canonical 单位为股/元，Tushare 按 ×100（手→股）/ ×1000（千元→元）换算，`fut_daily` 的 amount 为万元故 ×10000。**yinhe 的单位仍未核实**，是既有问题，另行确认。

真实接口实测发现并修复三个问题：(1) Tushare 的 offset 硬上限为 100000，而全市场一个月约 11.7 万行，原按月区间取数在第 18 页失败、**取不全数据**——改为逐交易日调用（交易日来自 raw calendar），并在 `query_all` 加 offset 上限拦截，把静默截断变成显式报错；(2) 大量指数只发布收盘点位不发布 OHLC（某日 10967 条中 8859 条），原实现要求五价齐全，丢弃了 81% 的有效指数行——改为无效价格写 NULL、保留该行，指数入库量 26211 → 203834；(3) 期货当日无成交时无 OHLC 但有结算价与持仓量（某日 940 条中 154 条），同样改为保留，16869 → 20696。另修 `volume`/`open_interest` 未取整导致 `COPY` 无法写入 BIGINT 的问题。0 视为有效取值原样保留，仅非有限值与负数转 NULL。

验证：`ruff` 通过；`pytest` 56 passed / 11 skipped（live 用例无 token 时跳过）；真实 Tushare 接口 + 真实 PostgreSQL 端到端跑通 2024-01 全月，单位换算按行核对一致（1158366.45 手 → 115836645 股）。新增 `tests/live/` 真实接口用例（契约核对 + 翻页无损），默认 skip。

---

## 2026-06-15 09:15 — 补充 uv 锁文件与 .env 自动加载

为当前 Python 依赖快照补入 `uv.lock`，并在 `src/getrich_data/common/config.py` 中增加对仓库根目录 `.env` 的可选自动加载；同时把 `python-dotenv` 加入 `pyproject.toml`。未运行 lint/test；本次仅更新依赖锁、配置加载与迭代记录，未改数据库或 raw/cache 输出。

## 2026-06-12 00:44 — 移除本地配置中的 provider 明文凭证

发现 `config.yaml` 中银河 provider 仍保留真实账号与密码字段，这是此前真实 SDK 实测遗留，不符合当前“配置文件只写环境变量名、敏感值由环境变量注入”的约定。已改为 `username_env: YINHE_USER` 与 `password_env: YINHE_PASSWORD`。未运行 lint/test；本次仅调整本地配置文件与迭代记录，未改业务代码、数据库或 raw/cache 输出。

## 2026-06-12 00:43 — 确认配置与环境变量边界

确认当前配置约定：结构化、非敏感配置写入 `config.yaml`；密码、license、token 等明文敏感值放在环境变量中，并由 `config.yaml` 通过 `*_env` 或 `${VAR}` 引用。查阅了 `src/getrich_data/common/config.py`、`config.example.yaml`、`.env.example` 与 `docs/runbook.md`。未运行 lint/test；本次仅做配置口径确认，未改业务代码、数据库或 raw/cache 输出。

## 2026-06-10 19:18 — 供应商本地实测（真实 SDK）

在本地 uv 环境实测三个供应商的真实抓取与入库。结论：

| provider | SDK | 凭证 | 网络 | 实测 |
|---|---|---|---|---|
| **yinhe** | ✅ AmazingData 1.1.6 (cp313 wheel @ `~/project/whl/`) | ✅ 旧 config 明文 | ✅ 101.230.159.234:8600 通 | ✅ **全流程跑通** |
| **ricequant** | ✅ rqdatac 可从 PyPI 装 | ❌ 缺 (license/账号未入库) | ✅ rqdatad-pro:16011 通 | ⛔ 缺凭证未跑 |
| **insight** | ❌ 不在 PyPI、本地无 wheel | ❌ 缺 | — | ⛔ 缺 SDK+凭证未跑 |

**yinhe 实测明细** (Python 3.13 venv `.venv313` + `AmazingData-1.1.6`/`tgw` wheel)：
- `raw yinhe`：登录真实服务器 → 8658 交易日历、5207 股票 + 1552 ETF + 624 指数代码、
  K 线按 `<code>/YYYY-MM.parquet` 月分区正确落盘
- `ingest yinhe` → 真实 docker PG：instruments 7383 / symbol_map 7383 /
  trading_calendar 17316 / stock_bar_1d 15977，`source=yinhe`，6 张表归属全部登记
- OHLC 校验无误 (如 600000.SH 2026-06-10 open=9.37 close=9.59)
- 真实 SDK 返回列：`code, open, high, low, close, volume, amount`
  (无 pre_close/limit/trading_status，transform 已按 None 优雅处理)

**凭证现状**：仓库里只有 yinhe 账号 (`yinhe_data_fetcher/config.yaml` 明文)。
ricequant/insight 旧 config 只写环境变量名 (`RQDATAC_LICENSE` / `INSIGHT_USER` 等)，
真实值原在未入库的 `.env`，现机器上搜不到。要实测这两个需补：
- ricequant：license key 或账号密码
- insight：账号密码 + `insight_python` wheel/安装路径

**待办**
- [ ] ricequant 实测 (待凭证)
- [ ] insight 实测 (待 SDK + 凭证)
- [ ] ingest 增量水位 (当前 importer 为全量 upsert；大表可加 watermark)

---

## 2026-06-10 19:00 — 全量重构：四项目合一 + 分层架构

### 背景
仓库原有 4 个职责重叠的项目 (`data_import_insight` / `data_import_yinhe` /
`import_data` / `yinhe_data_fetcher`) 反复重写同一件事 (上游数据 → 落库)，
旧的没删、新的另起，加上散乱的 `sql/`，整体混乱。

### 重构目标
单包 monorepo，**层优先、源其次**，全面用 PostgreSQL/TimescaleDB (移除 ClickHouse)。

### 落地结果
- **新结构** `src/getrich_data/`：
  - `common/` — 共享内核：config / logging / paths(`/opt/raw_parquet`) / parquet(原子写+pandas去重) /
    db(pool+COPY upsert) / contracts(canonical 列) / quality / **ownership** / migrate / retry
  - `raw/` — 下载层 (yinhe / ricequant / insight)，SDK → parquet，不归一化，client 协议依赖注入
  - `ingest/` — 入库层，adapter 读 parquet → transform 归一化 → COPY upsert 进 PG
  - `stream/` — 实时层 (yinhe / insight)，行情流 → `realtime.tick_buffer`
  - `cli.py` — `getrich raw|ingest|stream|db|own`
- **db/**：`ddl/`(00–70，新增 `70_ownership.sql`)、`migrations/`、`archive/`(旧 frontend/legacy 留档)
- **docs/**：架构 + 规范(命名/时区/代码映射/落盘/日志/归属) + 分层 + provider + runbook
- 删除 4 个旧项目、旧 `sql/`、`.agent/`；agent 指南合并为单一 `AGENTS.md`

### 关键设计：单表单一来源 (provider ownership)
数据库内同一张目标表只能由一个 provider 写入，登记在 `ops.table_ownership`，
ingest/stream 写库前强制校验，转移归属需显式 `--force-ownership` / `getrich own`。
见 `docs/conventions/provider-ownership.md`。

### 修复的真实 bug (非测试问题)
1. `db/ddl` 多处 `RAISE NOTICE '...%%', SQLERRM` — `%%` 是字面量，建库直接报错。改 `%`。
2. parquet 追加合并曾用无序 `row_number()` 去重 → **K 线追加静默数据损坏**。
   改为 pandas `keep='last'` 确定性去重 (并借此移除 DuckDB)。

### 移除 DuckDB
原从旧项目照搬 "DuckDB 合并 / pandas 兜底"。月分区单文件很小，pandas 足够；
且与 "全面用 PG、不要 data 目录" 一致。已清理依赖、代码、DDL(`ops.duckdb_artifact`)、文档。

### 测试
- `ruff check` 通过
- `pytest` **12 passed**：raw 抓取(FakeSDK 三源) / common 内核 /
  全流程 ingest 对真实 docker PG / 归属冲突与转移 / stream tick 入库
- 集成测试用一次性 `timescaledb` docker 容器跑真实 PG，供应商 fetch 用 Fake SDK 驱动
