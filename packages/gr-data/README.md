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

### 米筐风险模型五件套

DataYes 试用到期后的接替入口为 `rq_risk_model`，独立于 R1–R10 补充数据。
支持米筐标准 `v1/v2/v2trd`、`sws_2021/citics_2019`，期限固定 `daily`，
因子收益固定 `whole_market + implicit`。SDK 按日取暴露、因子收益、协方差、
特异收益和特异波动率；不需要额外 SDK，也不修改现有 DDL。

先填写 `providers.ricequant.risk_model`：显式起止日期、沪深股票代码清单、
模型／行业体系、确认的模块权限及四项源单位和核对依据，再设置 `selected: true`。
本地官方文档未明确全部数值单位，因此样例保持空值，不能照抄其他供应商的系数。
`order_book_ids` 是本次完整采集范围；不会用当前股票名单回填历史，不自动跳过
尚未上市、停牌或模型不覆盖的股票。范围内任一股票缺失时整日失败，应核对覆盖后
分段配置。北交所、港股与需要额外包的定制风险模型暂不支持。
raw 需要 `RICEQUANT_ENABLED=true` 和 `RICEQUANT_API_KEY`；离线 ingest 不需要密钥。

```bash
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_risk_model --mode init
uv run gr-data --config /path/to/config.yaml ingest ricequant --only rq_risk_model --months 2024-01
```

`init` 跳过已完整采集日，`update` 重抓显式日期范围。每轮保存恢复进度，失败后
同范围、同模式续跑只处理未完成日；日内尚未完成的批次重新请求。
请求按 `batch_size` 分批，配额触及共享 `supplements.quota_reserve_fraction`
（默认剩余 10%）时暂停。观察位于
`$RAW_PARQUET_ROOT/ricequant/rq_risk_model/v1/<variant>/<YYYY-MM-DD>/<observation_id>/`。
Parquet 使用 zstd，五份全部通过轴、完整性、有限值、行业哑变量、协方差对称与
半正定检查后才发布 manifest；读取时复核哈希。未完成日不会入库，已完成日可以先入库。

ingest 依赖已存在的 canonical 股票 `meta.instruments`，按 `.XSHG→.SH`、
`.XSHE→.SZ` 严格关联并写入独立 `ricequant` 代码映射。五张数据表、模型元数据、
映射和 ETL 流水在同一日事务内提交；映射缺失或写入失败则该日全部回滚。
单位统一到现有契约：协方差与特异方差为年化 `%²`（日频按 252 换算，σ 先平方），
因子收益为日频小数，特异收益为日频百分比。源单位和依据保存在 `model_run.units`。
米筐使用独立模型身份；每次日度观察生成不可变 run，重复导入同一观察幂等。
`available_at` 使用实际采集时间，历史回填不会伪装为当时已可得；全区间校准前
始终 `calibrated=false`，不代表已经通过真实市场五表自洽验收。

切换到米筐前需显式处理以下 8 张表的归属：`factor.model`、`factor.definition`、
`factor.model_run`、`factor.exposure`、`factor.covariance`、`factor.factor_return`、
`factor.specific_risk`、`factor.specific_return`。先查看 `gr-data own list`，
确定切换后逐表执行 `gr-data own set <table> ricequant ingest`，并停止 DataYes 写入任务。
风险 importer 不接受 `--force-ownership`，也不自动转移或删除旧数据。
旧 CNE6 历史保留其 model/run 身份，下游需显式选择米筐模型，不能拼接为同一条模型历史。
本次开发仅用 Fake SDK 和隔离 PG 验证；真实账号权限、单位与数据覆盖还需验收。

### 米筐特色指数补充（R1–R3，待真实样本准入）

已实现 `rq_index_daily`、`rq_index_components`、`rq_index_weights` 的离线契约、
分片采集、观察版本存储和严格读取。它们是独立 `.RI` 数据集，保持原单位，不进入
普通指数行情表或 `meta.instruments`。当前只验证 Fake SDK 链路；**新的 PostgreSQL
表、代码映射及 importer 尚未实现**，补充 ingest 命令会在连接 PG 前明确拒绝。
正式启用按设计的 P0 逐项确认权限、与 Tushare／Datayes 的差异、样本形态及日期区间，
再推进对应 DDL／writer；R4–R10 保持未实现的条件候选。

示例配置的 `providers.ricequant.supplements.datasets` 全部 `selected: false`。
每个启用项要求 `tushare_overlap/datayes_overlap=distinct`、`rq_permission=confirmed`、
`contract_status=verified`、证据引用和核对日期，且显式填写起止日期和代码白名单。
这些值应来自实际核验，不能照抄测试 fixture。SDK 边界已按本地 3.2.5 核对，未升级依赖。
成员接口须显式填写经样本确认的 `enable_bjse`；同批任务该值须一致，不一致时分批运行。
raw 还要求入口环境快照中 `RICEQUANT_ENABLED=true` 和非空 `RICEQUANT_API_KEY`，
密钥不写 YAML 或 manifest。连接／请求超时默认 5／60 秒。

准入完成后只运行明确选中的补充数据，例如：

```bash
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_index_daily --mode init
# 三项分别选定且通过准入后才可用组名
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_indices --mode update
```

旧任务默认列表及 `all` 的范围保持不变。`--only ''` 或配置空列表执行零任务；
未知、未选定、未准入或尚未实现的名称令整批预检失败，不会偷偷回退到旧行情任务。
只做补充采集的配置可将 `enabled.raw.ricequant`、`enabled.ingest.ricequant` 都设为空，
使用显式 `--only`；不要为了启用补充任务转移普通行情表的 owner。

采集依赖现有 `tushare/calendar/SSE.parquet` 覆盖所选自然日区间，记录其哈希，不联网
另造交易日历。日值按代码批×自然月，成分／权重按单指数单交易日切片；VX 成员接口
标记不适用且不发请求。update 补缺片并回扫末月和最近 5 个交易日。请求重试后仍超时或响应超过内存预算时先二分日期、再二分代码；
单代码单日仍失败则保留失败状态。父片仅在所有子片完成后计为覆盖。

观察文件位于 `$RAW_PARQUET_ROOT/ricequant/<dataset>/v1/<variant>/<YYYY-MM>/<observation_id>/`，
对应计划和 manifest 放在同一 variant 下的 `observations/<YYYY-MM>/<observation_id>/`。
单主机文件锁保证一个 writer，Parquet 使用 zstd／原子发布，manifest 最后发布。
已完成观察不可覆盖，A→B→A 修订保留三次观察；崩溃遗留文件不作为成功覆盖。
配额触及 10% 安全余量时暂停并以非零码退出，保留计划和成功片。同范围续跑先补缺片，
沿用 `rounds/` 下原子保存的本轮计划，并按观察序号区分历史覆盖与本轮完成片；恢复
拆分任务时直接接续子片，成功片不重复下载。若在最后一片发布后暂停，下次运行仅
确认本轮完成；再下一次运行才开启新一轮回扫。默认有限重试只针对
暂态故障，认证／权限／契约错误不伪装成功。日值缺交易日、空响应、缺失收盘价
（含 nullable 数值类型）或异常价格均阻塞；
成分空列表只有带可信返回形态及 `create_tm` 才作为完整空快照。`create_tm` 保留原义，
PIT 状态为未核实；权重只记查询日，不猜生效日、不自动归一到 1。

`ingest.ricequant.supplement_adapter.iter_observations` 提供离线逐片读取和月份筛选，
先校验 manifest、文件哈希、schema 和当前证据，再复核返回契约；它不会初始化 SDK
或写库，不能替代尚待开发的 importer。

离线回归命令（不读取真实账号、不访问业务库）：

```bash
uv run pytest packages/gr-data/tests/ricequant -v
```

### 供应商 SDK

Tushare 与 rqdatac 已列入包依赖。银河和华泰的 SDK 按厂商方式安装：

| provider | 包名 | 凭证环境变量 |
|---|---|---|
| tushare | `tushare`（已随包安装） | `TUSHARE_TOKEN` |
| yinhe（银河） | `AmazingData`（厂商提供 wheel） | `YINHE_USER` / `YINHE_PASSWORD` / `YINHE_HOST` |
| ricequant（米筐） | `rqdatac`（已随包安装） | `RICEQUANT_API_KEY` |
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
