# getrich-database

GetRich 平台的**外部数据接入层**：把上游供应商数据下载、归一化，写入 PostgreSQL / TimescaleDB。

> 边界：本仓库只做数据接入。**不含**因子定义、回测假设、策略逻辑或交易决策——那些属于主 `getrich` 工程。

## 架构

五层，**层优先、源其次**：顶层是职责分层，每层内部再按数据源（provider）切分。

```
                  ┌─────────────────────────────────────────────┐
  供应商 SDK ──→  │  raw      下载层：SDK → /opt/raw_parquet      │  不归一化
                  ├─────────────────────────────────────────────┤
  /opt/raw_parquet│  ingest   入库层：parquet → 归一化 → PG       │  canonical
                  ├─────────────────────────────────────────────┤
  实时行情流   ──→ │  stream   实时层：行情流 → realtime.tick_buffer│  按 provider
                  ├─────────────────────────────────────────────┤
                  │  db       库管理：DDL / 迁移 / 归档            │  PostgreSQL only
                  ├─────────────────────────────────────────────┤
                  │  common   共享内核：config/log/db/contracts/  │  全层复用
                  │           parquet/quality/ownership           │
                  └─────────────────────────────────────────────┘
```

每层内按 provider 分：`yinhe`（银河 AmazingData）、`ricequant`（米筐 rqdatac）、`insight`（华泰 INSIGHT）。
stream 仅 `yinhe` / `insight`。

## 数据源与目标表

| provider | raw 数据集 | 入库目标表 |
|---|---|---|
| yinhe | calendar, hist_code_list, backward_factor, kline_day, kline_min1 | `meta.instruments` / `meta.symbol_map` / `meta.trading_calendar` / `market.{stock,etf,index}_bar_1d` |
| ricequant | instruments, calendar, bars_1d | 同上 |
| insight | basic_info, trading_days, kline_day | 同上；实时 → `realtime.tick_buffer` |

**单表单一来源**：数据库内同一张目标表只能由一个 provider 写入，由 `ops.table_ownership` 登记并在入库/实时写库前强制校验。详见 [docs/conventions/provider-ownership.md](docs/conventions/provider-ownership.md)。

## 快速开始

```bash
uv sync                              # 安装依赖（供应商 SDK 需另行手动安装）
cp config.example.yaml config.yaml   # 填入 PG 连接与各 provider 凭证（环境变量名）

getrich db migrate                   # 应用 db/ddl 建库
getrich raw yinhe --mode init        # 抓取银河数据落 /opt/raw_parquet/yinhe/
getrich ingest yinhe                 # 归一化入库 PostgreSQL
getrich own list                     # 查看表归属
```

CLI 总览：

```
getrich raw    <provider> [--mode init|update] [--only a,b]
getrich ingest <provider> [--only a,b] [--force-ownership]
getrich stream <provider>                       # 长驻实时（需真实 SDK）
getrich db     migrate | status
getrich own    list | set <target> <provider> <channel> | release <target>
```

## 目录结构

```
src/getrich_data/
  common/     共享内核：config, logging, paths, parquet, db, contracts, quality, ownership, migrate
  raw/        下载层（yinhe / ricequant / insight），SDK → parquet
  ingest/     入库层（yinhe / ricequant / insight），parquet → PG
  stream/     实时层（yinhe / insight），行情流 → PG
db/
  ddl/        建库 DDL（00–70，按序执行）
  migrations/ 增量迁移
  archive/    历史 SQL（旧 frontend / legacy，只读留档）
docs/         规范与分层/数据源文档
reference/    API 列表、openapi、设计文档（资料）
tests/        common / raw / ingest / stream 测试
```

## 数据落地

- **raw parquet**：`/opt/raw_parquet/<provider>/<dataset>/...`（仓库外，不入库）。布局见 [docs/conventions/parquet-layout.md](docs/conventions/parquet-layout.md)。
- **PostgreSQL / TimescaleDB**：权威库。schema：`meta`（元数据）、`market`（行情）、`realtime`（实时缓冲）、`ops`（运维/归属/审计）、`staging`。

## 文档

入口见 [docs/README.md](docs/README.md)：架构、命名/时区/代码映射/落盘/日志规范、各层扩展方式、各 provider 说明、运行手册。

## 测试

```bash
uv run pytest                          # 全部（ingest/stream 需 docker，自动 skip）
uv run pytest tests/raw tests/common   # 仅离线测试
```

ingest/stream 集成测试用一次性 `timescaledb` docker 容器跑真实 PG；供应商 fetch 用 Fake SDK 驱动，无需真实凭证。
