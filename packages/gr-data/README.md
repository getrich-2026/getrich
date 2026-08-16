# gr-data — 数据层

配置、数据库连接，以及外部行情数据的接入（下载 → 归一化 → 入库）。

import 名 `gr_data`，命令行 `gr-data`。**建库与迁移不在本包**，DDL 的唯一真源是
`gr-db`（`gr-db migrate`）。

---

## 分层

| 层 | 职责 | 输入 → 输出 | 是否归一化 |
|---|---|---|---|
| `config` | env 型配置（`settings`）+ 采集矩阵（`pipeline`） | — | — |
| `db` | PostgreSQL／ClickHouse／DuckDB 连接与批量写 | — | — |
| `raw` | 下载 | 供应商 SDK → `$RAW_PARQUET_ROOT` 的 parquet | 否（保留源语义） |
| `ingest` | 入库 | parquet → 归一化 → PostgreSQL | 是（canonical） |
| `stream` | 实时 | 行情流 → `realtime.tick_buffer` | 是 |

**层优先、源其次**：顶层按职责分层，每层内部再按 provider 切分。新增数据源 =
在 `raw`／`ingest` 各加一个纵切片；改某层逻辑 = 只动一个横切片。

```
AmazingData(银河)  → raw/yinhe     → parquet → ingest/yinhe     → PostgreSQL
Tushare Pro        → raw/tushare   → parquet → ingest/tushare   → PostgreSQL
rqdatac(米筐)      → raw/ricequant → parquet → ingest/ricequant → PostgreSQL
INSIGHT(华泰)      → raw/insight   → parquet → ingest/insight   → PostgreSQL
银河／INSIGHT 实时  → stream/<provider> ───────────────────→ realtime.tick_buffer
```

`raw` 与 `ingest` 解耦：`raw` 只把数据原样落地，`ingest` 只消费 parquet，
便于回放与审计。

**边界**：本包只做数据接入。因子、回测、策略、交易决策分别属于 `gr-factor`、
`gr-backtest`、`gr-signal`。

---

## 跑起来

```bash
# 1. 配置：凭证只写环境变量名，明文不落配置文件
cp .env.example .env                                   # 仓库根，填 PG 与各 provider 凭证
cp packages/gr-data/config.example.yaml config.yaml    # 填抓取范围与限频

# 2. 建库（DDL 归 gr-db）
uv run gr-db migrate --target all

# 3. 抓取 + 入库（以 tushare 为例）
uv run gr-data raw tushare --mode update    # 增量抓取落 parquet
uv run gr-data ingest tushare               # 归一化入库
```

`raw update` 之后接 `ingest`，多 provider 各自一条链，适合放进 cron。

### 供应商 SDK

只有 Tushare 在 PyPI 上，已列入主依赖。其余三家需要凭证与专用 wheel，手动安装：

| provider | 包名 | 凭证环境变量 |
|---|---|---|
| tushare | `tushare`（已随包安装） | `TUSHARE_TOKEN` |
| yinhe（银河） | `AmazingData`（厂商提供 wheel） | `YINHE_USER` / `YINHE_PASSWORD` / `YINHE_HOST` |
| ricequant（米筐） | `rqdatac` | `RQ_LICENSE` |
| insight（华泰） | `insight_python` | `INSIGHT_USER` / `INSIGHT_PASSWORD` |

装好 SDK 且配好凭证后，用真实接口验证：

```bash
uv run gr-data raw tushare --only calendar     # 落 parquet
uv run gr-data ingest tushare --only calendar  # 写 meta.trading_calendar
uv run pytest packages/gr-data/tests/live -v   # 真实接口契约用例（无凭证时自动 skip）
```

缺凭证或缺 SDK 时命令会**立刻**失败并给出该设哪个变量，不重试、不静默降级。

---

## 表归属：单表单一来源

数据库里同一张目标表只能由一个 provider 写入，登记在 `ops.table_ownership`。
`ingest`／`stream` 写库前会校验，归属不符直接拒绝。

```bash
uv run gr-data own list                                  # 查看当前归属
uv run gr-data own set market.stock_bar_1d tushare ingest  # 转移归属
uv run gr-data own release market.stock_bar_1d           # 解除
```

**切主源是高风险操作**：不同源的单位口径、复权规则、停牌处理都可能不同，
混写会让同一张表里出现两套口径且事后无法分辨。转移前先逐表核对数据一致性。
`config.yaml` 里 `enabled.ingest.tushare` 默认为空就是这个原因 —— 那些目标表
当前归 yinhe，打开即等于切主源。

---

## 排障

| 现象 | 原因 |
|---|---|
| `缺少 Tushare token` | 没设 `TUSHARE_TOKEN`，或 `config.yaml` 的 `token_env` 指向了别的变量名 |
| `未安装 AmazingData SDK` | 银河 SDK 不在 PyPI，需厂商 wheel 手动安装 |
| `schema "meta" does not exist` | 没建库，先跑 `uv run gr-db migrate --target all` |
| ingest 报归属冲突 | 目标表归属别的 provider，见上一节 |
| 读不到根 `.env` | 确认在 workspace 内运行；可用 `GETRICH_ROOT` 显式指定根目录 |

数据接入的口径约定（时区语义、symbol 归一化、parquet 布局、日志、命名）见
`AGENTS.md` §3.4；各供应商的接口设计文档在 `getrich-design/data-platform/`。
