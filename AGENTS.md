# GetRich — AI 开发指令集

本文件是 GetRich 项目约束的**唯一真源**。项目以 **Codex 为主，Antigravity（Gemini）为辅**，Claude Code 保留兼容入口。文件名固定为 `AGENTS.md`，不另建 `AGENT.md` 或复制规则正文。

各工具的全局约定定义个人默认行为；本文件定义项目约束，更具体的目录级 `AGENTS.md` 定义局部约束。遵守当前用户授权与工具的系统指令、权限限制。

- **Codex**：直接读取根目录 `AGENTS.md`；修改子目录前检查沿途是否有更具体的指令。
- **Antigravity IDE**：`.agents/rules/project.md` 是 Always On 入口，引用本文件；共用编码规则与状态文档。
- **Claude Code**：`CLAUDE.md` 导入本文件；`.claude/settings.json` 只配置 Claude 权限，不作为 Codex 或 Gemini 的规则来源。
- `.agents/brain/` 是本项目约定的状态目录，按第 7 节主动读取；它不是自动发现的规则或技能目录。修改规则只改本文件，兼容入口保持简短。
- 默认由主 Agent 完成工作，不设置固定多 Agent 流水线；子 Agent 的使用遵循当前工具与用户的授权。

---

## 1. 仓库结构与运行环境

```
apps/web              主前端（Vite 8 + React 19 + TypeScript 6 + Tailwind 4）
apps/backtest-web     回测前端（暂停维护，待 API 稳定后重做）
packages/gr-data      配置、数据库连接、外部数据接入（raw → ingest → PG）
packages/gr-db        全部 DDL 与迁移，数据库结构的唯一真源
packages/gr-backtest  回测引擎（纯库，不含 Web / 实盘 / 调度）
packages/gr-signal    实盘信号生产与交易执行
packages/gr-api       FastAPI 应用 + 回测作业队列 + Celery worker
packages/gr-factor    期权与因子分析
packages/gr-tools     通用工具：文件系统、多格式表格读取、人性化格式化（无一方依赖的叶子）
packages/gr-agent     空占位包（只有 pyproject.toml，尚无源码）
deploy/               数据库基础设施部署模板，不在仓库内实例化
scripts/              仅存 lint_migrations.py
docs/                 人类阅读入口：指南、待决问题、历史材料（见 docs/README.md）
archive/              历史脚手架，删除前必须得到明确确认
.agents/brain/        跨会话开发进度（见第 7 节）
```

**命名规则：发行名 = 目录名 = `gr-x`，import 名 = `gr_x`**，连字符与下划线一一对应，
看目录就知道 import 什么。**不要再用 `getrich.*` 命名空间包** —— 它曾导致两个包往同一
目录装文件、单个包装不起来（见 `DECISIONS.md` D-018）。

依赖方向单向，不得出现反向 import：

```
gr-tools（叶子，谁都能依赖，它谁也不依赖）
   ↑
gr-data  ←──  gr-db
   ↑
   └──  gr-backtest  ←──  gr-signal  ←──  gr-api
gr-factor（独立）
```

`packages/gr-backtest/tests/gr_backtest/test_package_boundaries.py` 与
`packages/gr-tools/tests/test_package_boundaries.py` 会用静态扫描守住这条边界，
新增跨包 import 前先确认方向。gr-tools 里出现任何一方包的 import 都会让依赖成环
（gr-data 想用它的读文件能力时会互相 import），后一个测试专门挡这个。

- Python 3.11+，首行 `from __future__ import annotations`；依赖统一用 `uv` 管理，不用 pip。
- 数据处理优先 Polars / DuckDB；pandas 只留给小数据和兼容场景。
- 后端服务用 FastAPI。
- **数据库单独部署，不随应用一起构建**：`deploy/docker-compose.yml` + `deploy/config/` 只定义 PostgreSQL、ClickHouse、Redis 三个基础设施服务，是可复现的部署模板；GetRich 仓库内不创建 Docker 实例。真实 `.env`、数据卷、日志和运维脚本全部放在仓库外的部署目录，不进 git。仓库内不维护应用的 Dockerfile 或 systemd unit。
- 不要在 GetRich 仓库内执行 `docker compose up`、`down` 或 `restart`。改动 `deploy/` 后，需将其中的文件同步到仓库外的部署目录根，不保留外层 `deploy/`，再从部署目录校验和重启容器。
- **三个数据库的数据目录只能用 named volume，绝不 bind mount 宿主机目录。** bind mount 走虚拟机的文件共享层（VirtioFS），在 macOS 上会丢 POSIX 语义 —— PostgreSQL 曾因此在 autovacuum 里报 `could not open file`，整库不可用（见 `DECISIONS.md` D-029）。代价是数据不能从宿主机翻目录看，**备份必须走 `pg_dump` / `clickhouse-client` / `BGSAVE` 这类逻辑导出，不要拷贝数据目录文件**。日志目录可以继续 bind。

## 2. 数据库职责划分（铁律）

| 数据库 | 存储实体 | 约束 |
|---|---|---|
| **PostgreSQL / TimescaleDB**（`getrich` 库） | **行情主存**（OHLCV、复权因子、估值）+ 业务主库（策略、信号、用户、订单、订阅）+ 回测产物 | 唯一权威存储。行情用 TimescaleDB 超表；需要事务、主外键约束或 `ON CONFLICT` UPSERT 的数据只能写这里 |
| **ClickHouse** | **仅因子时序输出**（`factors_long`） | 只做大批量写入和按 factor／symbol／时间范围的分析查询。持久化表必须用 `MergeTree` 系列，强制配置 `PARTITION BY`、`ORDER BY`、`TTL` |
| **DuckDB** | ad-hoc 一次性分析、回测中间数据、本地 Parquet 报表 | 只作内存临时计算层，不做任何业务的终态存储 |
| **Redis** | 消息分发、tick 缓存、跨进程状态、分布式锁、限流 | 永不作为最终存储，关键数据必须周期性落 PG；历史数据和关系数据都不进 Redis |

**行情是 PostgreSQL 不是 ClickHouse。** 早期版本把 K 线放在 ClickHouse
（`md_bars_1m`／`md_bars_1d`），与数据接入层的 `market.*_bar_*` 并存且互相冲突；
现已统一到 PostgreSQL/TimescaleDB，CH 的行情表已删除（见 `DECISIONS.md` D-019）。

### PostgreSQL schema 划分

| schema | 内容 | 归属包 |
|---|---|---|
| `meta` | 合约、代码映射、交易日历 | gr-data |
| `market` | 行情主存：`<asset>_bar_<freq>`、复权因子、估值 | gr-data |
| `realtime` | 实时 tick 缓冲 | gr-data |
| `staging` | 入库中转 | gr-data |
| `ops` | ETL 作业、数据质量、表归属、迁移记账 | gr-data / gr-db |
| `app` | 业务主库：用户、策略、信号、订单、订阅 | gr-api |
| `backtest` | 回测产物：run / metrics / equity / sweep / walk-forward / jobs | gr-backtest / gr-api |
| `pick` | 选股信号：上传批次 `batch` + 每日标的池快照 `item` | gr-api |

- **全部 DDL 的唯一真源是 `packages/gr-db/src/gr_db/ddl/`**，不要在别处建表。
  DDL 必须**幂等**（`CREATE ... IF NOT EXISTS`）且**schema 全限定**（写 `app.users`，
  不要依赖 `search_path`）。迁移按 `file_name + checksum` 记账在 `ops.schema_migrations`。
- 连接池 `search_path = app,market,meta,public`；`backtest` 与 `pick` **不在** search_path 里，
  相关 SQL 一律显式写 `backtest.` / `pick.` 前缀。
- **两套交易所码不要混用**：`pick.item.exchange` 存 `SSE/SZSE/BSE`（前端接口契约定死的取值），
  `meta.*` 用 canonical 码 `XSHG/XSHE/XBSE`。查 `meta.instruments` / `meta.trading_calendar`
  前必须经 `gr_api/services/pick_symbols.py` 转换 —— 写错不报错，只会让
  `instrument_id` 整批为 NULL、交易日历一条都查不到。
- 引用其它表的 id 列，类型必须与被引用主键一致。曾因 `strategies.id` 是 VARCHAR 而
  引用方是 UUID，导致整个策略／信号接口在全新库上恒 500（`DECISIONS.md` D-020）。

**绝对禁止**在 ClickHouse 中执行事务更新或行级频繁删除。

## 3. 量化与时序规范

### 3.1 时区对齐

- 平台主时区 `Asia/Shanghai (UTC+8)`。
- PostgreSQL 在 `pool.py` 初始化时已强制 `SET timezone='Asia/Shanghai'`，所有写入的 timestamp 必须显式处理时区。
- ClickHouse 因子表的时间字段必须用 `DateTime64(3, 'Asia/Shanghai')`。
- PostgreSQL 行情表：分钟线 `dt` 用 `TIMESTAMPTZ`，日线 `dt` 用 `DATE`。**读日线时必须显式钉住时区**（`dt::timestamp AT TIME ZONE 'Asia/Shanghai'`）—— `DATE` 与 `timestamptz` 比较会按会话时区解释，不钉住就随连接配置漂移，边界日期整体错一天。
- 含跨日夜盘（21:00 至次日 02:30）的时序数据必须带时区，**绝对禁止**只用 `Date` 区分。
- datetime 全部 timezone-aware 或全部 naive，不混用。

### 3.2 列名与精度

- OHLCV 字段名固定为 `open, high, low, close, volume, vwap, oi, symbol, dt`，禁止任何缩写或变体。
- 财务金额、PnL、可用资金一律用 `decimal.Decimal`，禁止 `float`，避免累积舍入误差。
- 收益率必须显式区分单利 `simple_return` 与对数 `log_return`，并在函数签名和 docstring 中注明。

### 3.3 回测正确性

- **禁止 look-ahead bias**：$T$ 时刻的决策只能用 $\le T-1$ 可得的数据。用 `shift`／`lag` 时说明滞后期，区分信号生成时间戳与执行时间戳。
- 明确复权方式，区分信号计算用价与成交执行用价。
- 必须计入滑点、手续费、资金约束、保证金与爆仓风险，不假设无限资金零成本。
- 上线顺序：历史回测 → 模拟盘 → 小资金实盘，不跳级。
- 因子公式、复权规则、数据字段、行情商 API 一律不臆造，不确定就要文档。

### 3.4 数据接入约定（gr-data）

**时间语义**：列名必须能区分三类时间，否则下游 join 会引入前视泄漏。
`dt`（bar 事件时间）／`trading_day`（交易日）是 event time；供应商发布时间若有需
显式另行命名；`updated_at` 是写库时间。raw 层保留源字段原义，ingest 层显式映射，
绝不静默改写。供应商常用 int8 日期（`20240102`），统一走 `gr_data.common.retry`
的 `to_int_date` / `int_to_date` 转换。

**代码归一化**：`meta.instruments.symbol` 存带交易所后缀的完整代码（`600000.SH`），
`exchange` 用 canonical 码（`XSHG`/`XSHE`）。跨源对齐通过 `meta.symbol_map`
（`(source, source_symbol) → instrument_id`）。映射规则显式写在
`ingest/<provider>/symbols.py`，不静默改写代码格式。注意 tushare 的
`BJ→XBSE`，以及期货后缀与通行简称不同（`SHF→SHFE`、`ZCE→CZCE`、`CFX→CFFEX`、`GFE→GFEX`）。

**单表单一来源（铁律）**：数据库内同一张目标表只能由一个 provider 写入，登记在
`ops.table_ownership`，ingest／stream 写库前校验。转移归属必须显式走
`gr-data own release/set` —— 不同源的单位口径与复权规则可能不同，混写会让同一张表
出现两套口径且事后无法分辨。
唯一现有例外是 `meta.symbol_map`：按 `(source, source_symbol)` 隔离写入，见 D-037；不得据此放宽其他表的归属。

**parquet 落地**：根目录 `$RAW_PARQUET_ROOT`（仓库外）。布局
`<root>/<provider>/<dataset>/...`，路径解析统一走 `common/paths.py::RawPaths`，
禁止散落硬编码。一律 zstd 压缩；**原子写**（先写 `*.tmp-<uuid>`，再 `os.replace()`）；
追加按时间索引去重（新数据胜出）。

**日志**：模块使用 `logging.getLogger(__name__)`，provider／dataset 的动态 logger 名保留 `gr_data.` 前缀；**禁止 `print()` 做运行日志**。
日志须能还原「处理了哪个 provider / dataset / 范围 / 目标」；**不记录密钥或完整 payload**。

**命名**：行情表 `<asset>_bar_<freq>`（asset ∈ stock/etf/index/future/option，
freq ∈ 1d/1m）；来源列统一 `source`。canonical 列定义集中在 `common/contracts`，
与 `gr-db` 的 DDL 严格对齐，改一边必须同步另一边。

**重试语义**：缺凭证、缺 SDK 这类确定性失败抛 `PermanentError`，`retry_call`
不退避重试 —— 重试注定失败还要白等数十秒，真正原因会被重试日志淹没。

## 4. 后端编码规范

- **不引入 heavy ORM**：用 `psycopg3` 的 `AsyncConnectionPool` 手写原生 SQL。
- 大批量写入优先 COPY 协议或 multi-values UPSERT（`ON CONFLICT DO UPDATE`）。
- **绝对禁止**在没有 `try-except` 隔离的情况下在主线程中发起外部 API 调用或网络请求。

### 4.1 类型与说明

- 新增或修改的公开 API、跨模块调用边界必须有参数与返回值类型标注。
- 公开类与核心函数使用 Google 风格 docstring，说明单位、时间语义、输入前提及异常；性能敏感算法注明复杂度或峰值内存依据，不为简单函数机械补写。
- 最小复现优先放在对应包的测试中；不要求库模块逐文件添加 dummy data 或 `__main__`，不得覆盖真实 CLI／服务入口。

### 4.2 数据完整性与性能

- 对空数据、缺失值、`NaN`、`Inf`、除零显式定义行为。拒绝、保留、过滤或填充值须符合业务契约并说明原因，不静默改变样本或数值口径。
- 标的代码保持字符串，保留前导零；数值 dtype 遵循 canonical contracts 与 DDL，不统一强转 `float64`，金额仍按第 3.2 节使用 `Decimal`。
- 滚动、滞后、时序 join 前验证分组内时间排序与业务键重复情况；按明确规则排序／去重，不能把多标的时间序列当成一条全局序列。
- 优先 Polars 表达式、DuckDB SQL 或 NumPy 向量化，避免大表 `.iterrows()`、逐行 Python 回调和可向量化的 `apply`；有状态的回测执行循环允许保留，正确性优先。
- 大批量任务评估峰值内存并按可独立处理的分区分批；跨分区的 rolling／区间压缩必须保留必要上下文（见 D-056）。
- 热路径优化用同一输入通过 `time.perf_counter()` 对比耗时，并检查结果一致性。只有测量证明必要时才考虑 JIT；新增 numba 等依赖先说明并取得授权。

### 4.3 日志与异常

- 各模块用标准库 logger 记录事件，不隐式配置 handler 或创建日志文件。通用格式化与输出配置在 `gr_tools.logging`，公共配置模型在 `gr_tools.config`；各包提供业务上下文，不各起一套日志配置。CLI 正常结果输出可以使用 `print()`。
- 启动入口通过 `gr_data.config.setup_logging(settings)` 适配配置；API 在 lifespan、Celery 在日志启动信号中初始化。业务 filter 放输出 handler，才能处理子 logger 传播来的记录。旧 `gr_data.logging` 仅作无隐式初始化的兼容入口。
- 日志消息英文，带可定位任务的字段；`DEBUG` 诊断、`INFO` 进度、`WARNING` 可恢复异常、`ERROR` 操作失败。记录异常时同样不得泄漏凭证或完整 payload。
- 外部调用在请求／任务边界落实 `try-except` 隔离，明确超时、恢复或失败返回；底层仅在能够恢复或补充上下文时捕获，保留异常链向上传播。
- 禁止裸 `except:`、`except Exception: pass` 或只记日志后伪装成功。批处理隔离独立任务的失败并汇总报告；具有原子性要求的任务整体回滚。

### 4.4 测试与依赖

- 核心数值逻辑按风险覆盖正常、空／单元素、极值、缺失值及 `NaN`／`Inf` 输入；时序逻辑覆盖排序、重复、分组和日期边界，修复缺陷时补能复现问题的回归用例。
- 随机测试与基准显式固定所用随机数生成器的种子；不修改生产代码的全局随机状态来迎合测试。
- 覆盖率以仓库配置和 CI 为准（当前 Python CI 为 75%），不另设模板阈值，不为提高覆盖率编写无行为断言的测试。
- 依赖声明在对应包的 `pyproject.toml`，运行依赖与开发依赖分开，使用 `uv` 更新并同步 lock；不手改锁文件。
- 自动修复和格式化仅限本次改动的文件；检查通过后停止，不顺手修复无关基线问题。纯指令／文档变更检查差异、链接与路径，不要求跑业务测试或连接真库。

### 4.5 配置归属与环境来源

- 公共配置模型／工具归 `gr-tools`，不得反向依赖领域包；不在仓库根新增不可独立安装的 Python config 模块。
- 现有 `gr_data.config.Settings` 保留为应用组装及兼容入口；数据库／供应商等模型按领域维护，不为日志改造整体迁移公共 API。
- 环境变量优先于本地 `.env`：连接、凭证、机器路径、环境开关、日志输出选项留在环境层；Python config 定义类型、校验与默认值；YAML 只放结构化采集参数，不再复制数据库或日志配置。
- 当前默认只依赖 PostgreSQL，`GETRICH_WORKER_BACKEND=inproc`；仅启用 Celery 时才需要 Redis，CH 只在调用相关能力时需要。配置了连接地址不代表启动了服务。
- CI 默认仅启动 PG；手动 workflow_dispatch 的 `extra_services` 可恢复 CH／Redis 服务与 CH 迁移／字典冒烟。CH 离线 DDL 与 mock 用例仍保留。

## 5. 前端编码规范（React 19 + TypeScript 6 + Vite 8 + Tailwind 4）

- **禁止 `any`**：严格推导类型。对接无类型外部遗留包时必须附详细说明。API 类型放 `src/types/`，**照后端 service 的 return 语句写，不要照设计稿或 openapi 草案写**（教训见 `DECISIONS.md` D-032）。
- **数据请求**：接口函数模块化写在 `src/api/`（走 `src/api/client.ts`），组件一律通过 `@tanstack/react-query` 的 `useQuery`／`useMutation` 管理异步数据与加载态。**禁止**组件内 `useEffect` + `useState` 手写轮询，禁止 inline `fetch`／`axios`，**禁止再另起一套并行的接口层**（`src/lib/api.ts` 已因此删除，见 D-034）。
  - 分层：`client.ts` 负责认证头／401／校验 `code`／剥信封；`src/api/<domain>.ts` 只发请求、返回 `Promise<T>`（`T` 即后端 `data`）；**面向视图的形状转换放组件里，不放 api 层**。
- **表单校验**：`react-hook-form` + `zod`。
- **UI 与图表**：优先用 `src/components/ui/`（shadcn/ui + Radix UI）+ **Tailwind CSS 4**，由 CLI 统一管理，不手改 UI 源码。时序／权益曲线用 `echarts`，其余常规图表用 `recharts`。
  - Tailwind 4 是 **CSS-first**：主题写在 `src/index.css` 的 `@theme` 块，**没有 `tailwind.config.js`，也没有 `postcss.config.js`**（构建走 `@tailwindcss/vite` 插件）。不要再添加这两个文件，也不要重新引入 `autoprefixer`（v4 内置）。迁移细节见 D-033。
- **XSS 防御**：渲染用户或作者提供的 HTML（如 `strategy.detail_html`）必须先过 DOMPurify 或等效方案再传给 `dangerouslySetInnerHTML`。后端同时用 Pydantic 长度限制和 bleach 归一化。

## 6. 常用命令

```bash
# 应用配置：只填写已有数据库服务的连接信息
cp .env.example .env

# 基础设施模板：只做静态校验，不在仓库内启动容器
docker compose --env-file deploy/.env.example -f deploy/docker-compose.yml config --quiet

# 建库 / 迁移（DDL 唯一真源是 gr-db）
uv run gr-db migrate --target pg           # 当前默认只运行 PostgreSQL；CH 启用后另迁移
uv run gr-db status                        # 只看磁盘上有哪些 DDL
uv run gr-db migrate --target pg --dry-run

# 数据接入
uv run gr-data raw tushare --mode update   # 抓取落 parquet
uv run gr-data ingest tushare              # 归一化入库
uv run gr-data own list                    # 表归属

# 选股标的池导入（CSV / Parquet；函数接口见 gr_api.services.pick_import.import_picks）
uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-12 \
    --file picks.csv --dry-run             # 预检不写库
uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-12 \
    --file picks.csv [--overwrite] [--allow-empty]

# 后端：示例端口与 apps/web/vite.config.ts 的代理一致
# find_project_root() 识别 workspace 根 .env；uvicorn --port 仍须显式指定（D-003）
uv run uvicorn gr_api.main:app --reload --host 0.0.0.0 --port 8001

# 全量测试（testpaths 覆盖全部七个有源码的包）
uv run pytest -v

# 打真库的集成用例（默认跳过）。选股模块用 30 天模拟数据跑「导入 → 读接口」全链路，
# 模拟数据见 packages/gr-api/tests/fixture_picks.py，跑完自己清理。
GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_pick_pg_integration.py -v

# 单包测试
uv run pytest packages/gr-backtest/tests -v

# 静态检查与格式化
uv run ruff check packages/ scripts/
uv run ruff format --check packages/ scripts/
uv run python scripts/lint_migrations.py   # DDL 安全模式检查
uv run basedpyright packages/gr-backtest/src   # 若已安装

# 依赖
uv lock --check
uv sync --frozen --all-packages
```

```bash
# 前端（Node 要求 ^20.19.0 || >=22.12.0，Vite 8 的下限；CI 与本地都用 24）
cd apps/web
npm ci           # 按 lock 装，CI 用的就是它；日常加依赖才用 npm install
npm run dev      # Vite 开发服务（3000，/v1 代理到 gr-api:8001）
npm run build    # tsc -b && vite build
npm run lint     # ESLint
npm run preview  # 预览生产构建产物
```

前端**没有测试框架**，`lint` + `build` 就是 CI 的全部门禁（`.github/workflows/web.yml`），
修改前后按任务验证，结果以实际运行及 CI 为准，不把历史通过当作当前基线。

## 7. 文档与跨会话状态

文档按读者与用途组织，导航与新增规则见 [`docs/README.md`](docs/README.md)。

| 文件／目录 | 主要读者 | 维护内容 |
|---|---|---|
| `AGENTS.md` | 执行任务的 Agent | 现行项目规则；工具入口只引用此文件 |
| `.agents/brain/NOTES.md` | 接续任务的 Agent | 简短当前状态、阻塞、验证边界；可整体更新 |
| `.agents/brain/DECISIONS.md` | Agent 与维护者 | 按主题索引的有效决策、取舍原因与防错说明 |
| `docs/guides/` | 使用功能的开发者 | 操作与排障指南，不复制 DDL／响应字段目录 |
| `docs/plans/` | 决定范围的维护者、执行已选任务的 Agent | 未决问题、证据、待定选择与验收条件 |
| `docs/history/` | 追溯历史的维护者 | 已完成计划／审查快照，不能当作当前任务指令 |

- **会话开始**：先读 NOTES，再按任务查 DECISIONS 的主题索引及相关指南；不默认加载所有历史材料。
- **会话结束**：实质性代码、schema 或技术方案变化后更新 NOTES；完成项从状态／待办中移除，长期原因写入 DECISIONS。
- **新增文档**：先明确读者、用途、状态；优先更新已有文件。只有独立用途或用户要求时才新建，不为每次修复创建总结。
- **决策维护**：日常以追加和明确取代为主；用户授权清理时可删除过期／无用条目，修复引用，保留其余编号，不重排或复用。
- **自改进**：AI 误判或测试暴露的问题，只有具有项目特定、可复用防范价值时才记入决策；不要追加通用操作失误流水账。
- **证据时效**：测试数字、数据库行数、机器路径与服务健康带日期和验证范围；未重查时标为历史，不写成实时状态。
- **移动文档**：更新入口与相对链接；已记账 SQL 不为文档搬迁改 checksum，历史引用通过决策说明。

## 8. 改动边界与禁止事项

- 不静默变更架构、依赖、凭证、数据路径、公开 API、表结构 —— 这几类必须先说。
- 保留工作区已有修改，仅改任务所需文件；未获用户明确要求，不得 commit、push、publish、deploy、创建 PR 或发送外部消息。工具权限 allow 不等于用户授权。
- **绝对禁止**输出或提交真实凭证、token、私钥，以及本地 `.env` 里的真实值。
- **绝对禁止**用 `git reset --hard` 等 destructive 命令修改未提交的工作区代码。
- **绝对禁止**在 `packages/gr-api/src/gr_api/main.py::create_app()` 中移除 `SecurityHeadersMiddleware` —— 这是协议级 XSS 兜底（`Content-Security-Policy` / `X-Frame-Options` / `nosniff` / `Referrer-Policy`），也是 OWASP 推荐做法。新增路由或中间件时，测试必须用 `TestClient` 验证响应仍带这 4 个头。
- **绝对禁止**未经 DOMPurify 或等效清洗就用 `dangerouslySetInnerHTML` 渲染用户内容。
- 超过 100,000 行的数据集**绝对禁止**存普通 CSV，必须用 Parquet（`zstd` 压缩）。

## 9. 语言约定

- 用用户使用的语言回复。
- 注释、commit message、文档正文：中文。
- 标识符、函数名、类名、日志消息、配置键、表名、字段名、文件名：英文（为了可 grep）。
