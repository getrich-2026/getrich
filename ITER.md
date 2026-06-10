# 迭代日志 (ITER.md)

本仓库的迭代记录。**每次迭代必须追加一条**，最新在上。

标题格式（精确到分钟，本地时间 Asia/Shanghai）：
`## YYYY-MM-DD HH:MM — <事件标题>`

---

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
