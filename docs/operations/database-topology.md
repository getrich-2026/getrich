# 数据库拓扑

> **本节讲解 GetRich 平台三库职责** —— PostgreSQL（业务事务）、ClickHouse（时序/因子）、DuckDB（ad-hoc 临时分析）。每库有严格的使用边界，**绝对禁止越权**。这是 GetRich 项目的**铁律**之一。

---

## 1. 三库职责矩阵

| 维度 | PostgreSQL (`getrich` 库) | ClickHouse | DuckDB |
|---|---|---|---|
| **角色** | 业务与事务唯一主库 | 行情与因子的海量时序存储 | 临时内存计算 |
| **数据形态** | 关系型行存 + JSONB | 列存 + `MergeTree` 系列 | in-process 列存 |
| **存储实体** | 策略元数据、信号记录、订阅、账户快照、支付账单、订单、配置 | 分钟线/日线 OHLCV、Tick、因子时序输出 | 无（不持久化） |
| **事务** | ✅ 强 ACID | ❌ 弱（无行级事务） | ❌ 嵌入式，无分布式事务 |
| **典型查询** | `SELECT * FROM strategies WHERE user_id = ?` | `SELECT avg(close) FROM bar_1d WHERE symbol IN (...) GROUP BY dt` | ad-hoc pandas 风格 |
| **写入路径** | `psycopg3` 异步连接池，手写 SQL | Batch Write（COPY 协议） | 仅 in-memory |
| **约束** | 主外键、`ON CONFLICT`、CHECK | 强制 `PARTITION BY` + `ORDER BY` + `TTL` | 无（无 schema 概念） |

---

## 2. 铁律（Don'ts）

| 场景 | 禁止 | 原因 |
|---|---|---|
| **ClickHouse 事务更新** | ⛔️ 禁止在 CH 中做 `UPDATE` / `DELETE` 单行 | CH 无行级事务，频繁更新会引爆性能 |
| **PostgreSQL 存时序** | ⛔️ 禁止把分钟线 / Tick 写入 PG | PG 行存对时序扫描慢 100x |
| **DuckDB 持久化** | ⛔️ 禁止把 DuckDB 用作"业务终态存储" | DuckDB 是嵌入式分析，无并发/容错 |
| **PG 写大 parquet** | ⛔️ 禁止在 PG `bytea` 存 Parquet 文件 | 文件系统 / 对象存储更合适 |

> 详细规则见 [CLAUDE.md — 数据库职责划分](https://github.com/getrich/getrich/blob/main/CLAUDE.md)。

---

## 3. 库与表分布

### 3.1 PostgreSQL（`getrich` 库）

**核心 schema**：`frontend.*`（业务表）+ `auth.*`（用户/会话）。

| 表 | 用途 | 写入频率 |
|---|---|---|
| `strategies` | 策略元数据 | 中 |
| `strategy_versions` | 策略版本快照 | 中 |
| `signals` | 实盘信号 | 高（每 5min/strategy） |
| `subscriptions` | 用户订阅 | 低 |
| `account_snapshots` | 账户资产快照 | 日 |
| `payments` / `orders` | 支付账单、交易订单 | 中 |
| `users` / `user_auth` | 用户与认证 | 低 |
| `backtest_runs` / `backtest_metrics` / `backtest_equity_points` | 回测结果 | 中 |
| `backtest_jobs` / `sweeps` / `walk_forwards` | 异步任务 | 中 |
| `signal_settings` / `signal_reads_monthly` | 信号配置 | 中 |
| `strategy_trades` | 交易对账 | 高 |

> 全部 25 个 PG migration 见 `migrations/001_*.sql` ~ `025_*.sql`。

### 3.2 ClickHouse（`getrich` 库）

**核心表**：

| 表 | 引擎 | 用途 |
|---|---|---|
| `bar_1m` / `bar_5m` / `bar_15m` / `bar_30m` / `bar_60m` / `bar_1d` | `MergeTree` | 多频率 OHLCV |
| `tick` | `MergeTree` | 逐笔成交（仅部分品种） |
| `factor_values` | `ReplacingMergeTree` | 因子时序输出 |
| `strategy_signals` | `MergeTree` | 实时信号历史 |
| `market_snapshot` | `ReplacingMergeTree` | 行情快照（15min 滚动） |
| `instruments` | `ReplacingMergeTree` | 标的基础信息（symbol ↔ name） |
| `calendar` | `MergeTree` | 交易日历（`is_trading`, `session`） |
| `corp_actions` | `MergeTree` | 公司行为（分红/送股/拆股） |

> 2 个 CH migration：`migrations/clickhouse/001_*.sql`、`002_*.sql`。
> 所有时序表都强制 `PARTITION BY toYYYYMM(dt) ORDER BY (symbol, dt) TTL dt + INTERVAL 5 YEAR`。

### 3.3 DuckDB

**仅作为临时计算层**：

- 在 backtest 跑完后，`Reporter`/`TearSheet` 临时建内存 DuckDB 跑 ad-hoc SQL（计算归因、滚动 Sharpe、IC 衰减）
- 不写入磁盘
- 不跨进程

---

## 4. 时区与时间字段

**主时区**：`Asia/Shanghai (UTC+8)`，三库统一。

| 库 | 字段类型 | 强制 |
|---|---|---|
| PostgreSQL | `TIMESTAMPTZ`（always tz-aware） | pool 初始化 `SET timezone='Asia/Shanghai'` |
| ClickHouse | `DateTime64(3, 'Asia/Shanghai')` | 列类型固定 tz |
| DuckDB | 字符串 / Python `datetime`（with tz） | Python 端 `.astimezone(tz)` |

> 写入 `Date` / `Date32` 必须先用 `.astimezone(tz).date()` 转换，防止 UTC 偏移导致日期漂移。

**夜盘数据**（如商品期货 21:00 ~ 次日 02:30）：

- ClickHouse 必须用 `DateTime64`（**绝对禁止** `Date`）
- 重采样必须传 `sessions=(Session(...), ...)`，桶边界对齐到 session 起点

---

## 5. 连接池

### 5.1 PostgreSQL

`src/getrich/libs/postgres/pool.py`：

```python
class PgConnectionPool:
    """psycopg3 异步连接池。
    
    - 初始化时 SET timezone='Asia/Shanghai'
    - min_size=2, max_size=20（默认）
    - search_path 默认 'frontend, public'
    """
```

`pg_pool` 是全局单例：

```python
from getrich.libs.postgres.pool import pg_pool

async with pg_pool.connection() as conn:
    await conn.execute("SELECT 1")
```

### 5.2 ClickHouse

`src/getrich/libs/clickhouse/pool.py`：

```python
class ChPool:
    """clickhouse-driver 连接池（同步）。
    
    - 同步 API（clickhouse-driver 不支持 async）
    - 在 async 上下文用 asyncio.to_thread() 包装
    - 默认 max_size=10
    """
```

### 5.3 DuckDB

嵌入式，无池：

```python
import duckdb
con = duckdb.connect()  # 内存模式
con.execute("SELECT * FROM df")
```

---

## 6. 数据流图

```mermaid
flowchart LR
    A[外部数据源<br/>通达信/聚宽/clickhouse-client] --> B[ETL<br/>scripts/etl/]
    B -->|COPY| C[CH: bar_1m/.../factor_values]
    B -->|INSERT|UPSERT| D[PG: instruments/calendar/corp_actions]

    E[Strategy.on_bar] -->|读| C
    E -->|写| F[PG: signals/orders]
    F -->|SSE| G[Frontend]
    F -->|触发| H[Broker API]
    H -->|回调| F

    I[Backtest.run] -->|读| C
    I -->|读| D
    I -->|写| J[PG: backtest_runs + artifacts]
    J -->|GET| G

    K[Reporter/TearSheet] -.->|DuckDB in-mem| I
```

---

## 7. 容量规划

| 库 | 6 个月数据量 | 1 年 |
|---|---|---|
| PG | ~5 GB | ~10 GB |
| CH (bar) | ~50 GB | ~100 GB |
| CH (factor) | ~200 GB | ~400 GB |
| DuckDB | 0（不持久化） | 0 |

> 备份策略：PG `pg_dump` 每日 + WAL 归档；CH `BACKUP ... TO S3` 每周；DuckDB 不备份。

---

## 8. 进一步阅读

- 设计契约：[10 数据层](../design-contracts/10-data-layer.md)
- 项目铁律：[CLAUDE.md — 数据库职责划分](https://github.com/getrich/getrich/blob/main/CLAUDE.md)
- 迁移工具：[migration-runner](migration-runner.md)
- 监控：[monitoring](monitoring.md)
- 故障处理：[runbook](runbook.md)
- 源码：
    - [`src/getrich/libs/postgres/pool.py`](https://github.com/getrich/getrich/blob/main/src/getrich/libs/postgres/pool.py)
    - [`src/getrich/libs/clickhouse/pool.py`](https://github.com/getrich/getrich/blob/main/src/getrich/libs/clickhouse/pool.py)
