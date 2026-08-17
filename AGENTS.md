# GetRich — AI 开发指令集

本文件是 GetRich 项目约束的**唯一真源**，供 Claude Code、Codex、DeepSeek 等所有 harness 共用。`CLAUDE.md` 只是指向本文件的入口，不重复内容。

各 harness 自己的全局约定（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md` 等）定义通用行为与 agent 调度；本文件只写 GetRich 特有的约束，更具体的指令优先。

---

## 1. 仓库结构与运行环境

```
apps/web              主前端（Vite 7 + React 19 + TypeScript 5.9）
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
archive/              历史脚手架，删除前必须得到明确确认
.agent/brain/         跨会话开发进度（见第 7 节）
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

- Python 3.10+，首行 `from __future__ import annotations`；依赖统一用 `uv` 管理，不用 pip。
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

**parquet 落地**：根目录 `$RAW_PARQUET_ROOT`（仓库外）。布局
`<root>/<provider>/<dataset>/...`，路径解析统一走 `common/paths.py::RawPaths`，
禁止散落硬编码。一律 zstd 压缩；**原子写**（先写 `*.tmp-<uuid>`，再 `os.replace()`）；
追加按时间索引去重（新数据胜出）。

**日志**：统一 `gr_data.logging.get_logger(name)`，**禁止 `print()` 做运行日志**。
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

## 5. 前端编码规范（React 19 + TypeScript 5.9）

- **禁止 `any`**：严格推导类型。对接无类型外部遗留包时必须附详细说明。API 类型放 `src/types/`，与后端 Pydantic schema 对齐。
- **数据请求**：接口函数模块化写在 `src/api/`（走 `src/api/client.ts`），组件一律通过 `@tanstack/react-query` 的 `useQuery`／`useMutation` 管理异步数据与加载态。**禁止**组件内 `useEffect` + `useState` 手写轮询，禁止 inline `fetch`／`axios`。
- **表单校验**：`react-hook-form` + `zod`。
- **UI 与图表**：优先用 `src/components/ui/`（shadcn/ui + Radix UI）+ Tailwind CSS 3，由 CLI 统一管理，不手改 UI 源码。时序／权益曲线用 `echarts`，其余常规图表用 `recharts`。
- **XSS 防御**：渲染用户或作者提供的 HTML（如 `strategy.detail_html`）必须先过 DOMPurify 或等效方案再传给 `dangerouslySetInnerHTML`。后端同时用 Pydantic 长度限制和 bleach 归一化。

## 6. 常用命令

```bash
# 应用配置：只填写已有数据库服务的连接信息
cp .env.example .env

# 基础设施模板：只做静态校验，不在仓库内启动容器
docker compose --env-file deploy/.env.example -f deploy/docker-compose.yml config --quiet

# 建库 / 迁移（DDL 唯一真源是 gr-db）
uv run gr-db migrate --target all          # pg | ch | all
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

# 后端：启动 FastAPI 开发服务器
# find_project_root() 已修好，不再需要显式 --env-file（D-003）
uv run uvicorn gr_api.main:app --reload --host 0.0.0.0 --port 8000

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
# 前端
cd apps/web
npm run dev      # Vite 开发服务
npm run build    # 类型检查 + 生产打包
npm run lint     # ESLint
```

## 7. 开发进度文档（`.agent/brain/`）

两个文件，职责不同，**不要混写**：

| 文件 | 性质 | 写什么 |
|---|---|---|
| `NOTES.md` | **状态快照**，可整体覆写 | 当前进行中的工作、未决 P0／P1、已知失败基线。历史沿革交给 `git log`，不在这里追加流水账 |
| `DECISIONS.md` | **只增不改**的长期记录 | 技术决策及其理由、踩坑与防范策略、不可从代码推导的隐式约束 |

- **会话开始**：先读 `NOTES.md` 恢复状态，再读 `DECISIONS.md` 了解历史约束与坑。
- **会话结束**：只要发生了实质性代码变更、表结构调整或技术方案抉择，必须在结束 turn 前更新 `NOTES.md`。
- **自改进**：若出现 AI 误判导致的用户纠错或测试失败，把错误模式、根本原因、防范策略追加到 `DECISIONS.md`。
- 写入前先核对：已经过期的条目要删掉，不要让互相矛盾的两条同时存在。

## 8. 改动边界与禁止事项

- 不静默变更架构、依赖、凭证、数据路径、公开 API、表结构 —— 这几类必须先说。
- **绝对禁止**输出或提交真实凭证、token、私钥，以及本地 `.env` 里的真实值。
- **绝对禁止**用 `git reset --hard` 等 destructive 命令修改未提交的工作区代码。
- **绝对禁止**在 `packages/gr-api/src/gr_api/main.py::create_app()` 中移除 `SecurityHeadersMiddleware` —— 这是协议级 XSS 兜底（`Content-Security-Policy` / `X-Frame-Options` / `nosniff` / `Referrer-Policy`），也是 OWASP 推荐做法。新增路由或中间件时，测试必须用 `TestClient` 验证响应仍带这 4 个头。
- **绝对禁止**未经 DOMPurify 或等效清洗就用 `dangerouslySetInnerHTML` 渲染用户内容。
- 超过 100,000 行的数据集**绝对禁止**存普通 CSV，必须用 Parquet（`zstd` 压缩）。

## 9. 语言约定

- 用用户使用的语言回复。
- 注释、commit message、文档正文：中文。
- 标识符、函数名、类名、日志消息、配置键、表名、字段名、文件名：英文（为了可 grep）。
