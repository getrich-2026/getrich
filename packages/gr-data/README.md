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
uv run gr-db migrate --target pg

# 3. 抓取 + 入库（以 tushare 为例）
uv run gr-data raw tushare --mode update    # 增量抓取落 parquet
uv run gr-data ingest tushare               # 归一化入库
```

`raw update` 之后接 `ingest`，多 provider 各自一条链，适合放进 cron。

### Tushare 已实现范围与导入顺序

当前覆盖 11 个接口：`stock_basic`、`index_basic`、`fut_basic`、`trade_cal`、
`daily`、`adj_factor`、`stk_limit`、`suspend_d`、`index_daily`、`daily_basic`、`fut_daily`。
财报、宏观和 ETF／期权扩展不在这一批接口范围内。

| ingest 组别 | importer → 目标表 |
|---|---|
| `reference` | `instruments` → `meta.instruments`；`symbol_map` → `meta.symbol_map`；`calendar` → `meta.trading_calendar` |
| `bars_1d` | `stock_bar_1d`／`index_bar_1d`／`future_bar_1d` → 对应 `market.*_bar_1d` |
| `market_ext` | `daily_basic` → `market.stock_daily_basic`；`adj_factor_ts` → `market.adj_factor_ts` |
| `fundamental` | `valuation_1d` → `fundamental.valuation_1d` |
| `classify` | `instrument_category` → `classify.instrument_category` |

raw 先抓日历，再按 `trade_date` 逐日请求全市场，按自然月落盘。
每页请求（包含末尾空页探测与失败后的重试）都遵守
`providers.tushare.rate_limit.sleep_between_requests_sec`；遇到 offset 硬上限直接失败，
不把同一超大查询重试数遍。

`update` 补缺失月份并重抓最新已有月份。`start_date` 落在月中时，重抓保留月内
未请求日期，只替换本次已请求的日期。空 `suspend_d` 响应会清除对应日期的旧事件；
其他逐日数据集若在已有数据的日期返回空响应，会拒绝覆盖，避免把历史行情擦掉。
任意一天请求失败时不替换该月文件。

月内合并时，`trade_date` 的整数／字符串表示统一保存为 `YYYYMMDD` 字符串，
日期含义与行情单位保持不变。损坏的月文件可通过覆盖完整自然月的 `--mode init`
重建；该月起点须为月初，且已到月末。非稀疏数据存在空响应时不以不完整结果
重建损坏文件。月中起抓、尚未到月末或 `update` 仍需读出旧文件，读取失败时
明确报错并保留原文件，以免丢掉未请求日期。

```bash
uv run gr-data raw tushare --only instruments,calendar --mode update
uv run gr-data raw tushare --only daily,adj_factor,stk_limit,suspend_d,index_daily,daily_basic,fut_daily --mode update
uv run gr-data own list
uv run gr-data ingest tushare --only reference
uv run gr-data ingest tushare --only bars_1d,market_ext,fundamental,classify --months 2024-01
```

选中的数据集按依赖顺序执行，即使 `--only` 顺序相反也先处理依赖；未选中的依赖
不会自动启用。历史数据建议逐月导入，避免一次加载全部月份。
`daily_basic` 和 `valuation_1d` 共用原始文件，各自在目标金额列做万元→元转换；
未提升字段在 `raw_payload` 中保持供应商原单位。缺复权因子或股票 OHLC 会中断；
缺涨跌停价保留 NULL；未知标的告警后跳过。股票辅助表关联前统一 int8／字符串日期
及代码首尾空格，再按键去重；期货成交量与持仓量保持「手」。

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
示例配置已列出 Tushare 的五个 ingest 组别。启用列表只决定执行哪些 importer，
实际 owner 以 `gr-data own list` 为准；归属冲突时失败，不会自动切主源。
`meta.symbol_map` 是唯一例外：按包含 `source` 的主键隔离多源记录，见 D-012。

---

## 排障

| 现象 | 原因 |
|---|---|
| `缺少 Tushare token` | 没设 `TUSHARE_TOKEN`，或 `config.yaml` 的 `token_env` 指向了别的变量名 |
| `未安装 AmazingData SDK` | 银河 SDK 不在 PyPI，需厂商 wheel 手动安装 |
| `schema "meta" does not exist` | 没建库，先跑 `uv run gr-db migrate --target pg` |
| ingest 报归属冲突 | 目标表归属别的 provider，见上一节 |
| 读不到根 `.env` | 确认在 workspace 内运行；可用 `GETRICH_ROOT` 显式指定根目录 |

数据接入的口径约定（时区语义、symbol 归一化、parquet 布局、日志、命名）见
`AGENTS.md` §3.4；各供应商的接口设计文档在 `getrich-design/data-platform/`。


## 配置与日志

配置按使用者组装：数据连接与供应商模型在 `gr_data.config`，API／worker 模型在 `gr_api.config`；公共环境加载、路径与日志模型在 `gr_tools.config`。模型导入不加载 `.env`，不会创建用户目录配置文件。
日志输出工具在 `gr_tools.logging`；模块直接用标准库 logger，由启动入口调用 `gr_tools.config.setup_logging(logging_config)`。

| 来源 | 内容 | 示例 |
|---|---|---|
| 环境变量／本地 `.env` | 环境差异、连接、凭证、机器路径、输出选项 | PG_*、TUSHARE_TOKEN、RAW_PARQUET_ROOT、LOG_LEVEL／LOG_FMT／LOG_FILE／LOG_JSON |
| Python config | 类型、校验、默认值与应用组装 | LoggingConfig、PostgresConfig、ApiSettings／WorkerSettings |
| `config.yaml` | 结构化采集参数 | provider、dataset 启用列表、抓取范围、重试与限频 |

`load_environment()` 显式读取一个环境快照，默认不修改 `os.environ`。真实环境变量优先于文件；显式传 `env_file` 时只使用该文件，否则依次选择 workspace `.env`、`~/.config/getrich/.env`。自动候选都不存在时仅使用进程环境；显式文件不存在则报错，不自动创建文件。首次运行仍执行 `cp .env.example .env`。

YAML 不复制数据库与日志配置；`load_config(environment=env)` 的占位符、`*_env` 凭证字段、raw 路径与连接配置共用同一快照。数据／信号 CLI 在启动时显式安装环境，兼容直接读进程环境的 SDK；模型和库导入不做此操作。

只加载当前命令需要的模型：raw 抓取不强制 PG，`gr-db status` 不校验连接，PG 命令不校验 CH／Web。默认使用 PostgreSQL 和 inproc 作业路径，
Redis 仅在 Celery 模式需要，ClickHouse 仅在使用因子输出相关能力时需要。

CLI／API／worker 启动入口统一配置日志，库模块导入不创建 handler 或日志文件。
LOG_FILE 使用完整文件名，相对路径以 workspace 根解析；LOG_JSON=true 输出单行 JSON，
否则使用 LOG_FMT。结构化字段使用 `extra` 或 `extra={"context": {...}}`，不得记录凭证或完整请求／供应商 payload。
CLI 的 `--verbose` 优先于 LOG_LEVEL，Celery 显式 `--loglevel`／`--logfile` 优先于环境选项。
重配只关闭本项目管理的 handler，保留测试／宿主框架的 handler；框架自身的访问日志配置仍由框架管理。

### Python 调用迁移

旧 `gr_data.config.Settings`、全量 `load_settings()`／`settings` 单例和 `gr_data.config.setup_logging` 已移除。数据模型与 `find_project_root` 仍可从 gr-data 配置入口导入；WebConfig、WorkerConfig、BacktestStorageConfig 改从 `gr_api.config` 导入。数据库连接池改为 `await pg_pool.init(postgres_config)`，ClickHouse 构造器可传 `config=clickhouse_config`。

```python
from gr_data.config import load_postgres
from gr_data.config.pipeline import load_config
from gr_tools.config import LoggingConfig, load_environment, setup_logging

env = load_environment()  # 或显式指定 env_file
setup_logging(LoggingConfig.from_env(env.root, env.values))
pipeline = load_config(environment=env)
postgres = load_postgres(env)  # 只在需要 PG 的通路中调用
```

API 由 `load_api_settings(env)` 组装，`create_app(config)` 将配置绑定到应用实例；请求依赖与后台任务使用该配置。原 `uvicorn gr_api.main:app` 命令保持可用，默认应用在访问 ASGI 入口时创建，单独导入工厂不加载配置。Celery 工厂接收 `WorkerSettings`，CLI 入口加载一次并绑定到 Celery 应用；exec 后在新进程配置日志。

配置对象的 repr 隐藏凭证字段，旧全量 `to_dict()` 已删除；不要自行对环境快照或配置做全量序列化输出。
