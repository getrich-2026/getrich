# 运维指南

本节介绍 GetRich 平台的生产部署、迁移、监控与故障处理。

---

## 1. 部署模式

| 模式 | 适用 | 文档 |
|---|---|---|
| **本地开发** | 单机（macOS/Linux/Windows） | [快速开始 / 安装](../getting-started/installation.md) |
| **远程数据中心** | 多机（1 API + 4 workers + 1 signals） | [systemd 部署](systemd.md) |
| **生产** | 多机 + 监控 + 备份 | [systemd 部署](systemd.md) + [监控](monitoring.md) + [Runbook](runbook.md) |

---

## 2. 核心组件

部署涉及 4 类进程 + 3 类数据库：

```mermaid
graph TB
    subgraph Data[数据库]
        PG[(PostgreSQL<br/>业务/事务)]
        CH[(ClickHouse<br/>时序/因子)]
        Duck[(DuckDB<br/>临时分析)]
    end
    subgraph Cache[缓存]
        Redis[(Redis<br/>Celery broker)]
    end
    subgraph App[应用]
        API[getrich-api.service<br/>FastAPI + uvicorn]
        Worker[getrich-worker@.service<br/>Celery 池 ×4]
        Signals[getrich-signals.{service,timer}<br/>实盘信号生成]
        Broker[getrich-broker.service<br/>Redis 自身]
    end

    API <--> PG
    API <--> CH
    API <--> Duck
    API <--> Redis
    Worker <--> PG
    Worker <--> Redis
    Signals <--> PG
    Signals <--> CH
    Signals <--> Redis
    API -.->|enqueue| Worker
```

---

## 3. 进程清单

| 服务 | Unit | 启动顺序 | 端口 | 备注 |
|---|---|---|---|---|
| **Broker (Redis)** | `getrich-broker.service` | 1（最先） | 6379 | 其他服务依赖它 |
| **API** | `getrich-api.service` | 2 | 8000 | `--workers 1`（inproc backend 强制） |
| **Worker 池** | `getrich-worker@{1..4}.service` + `getrich-worker.target` | 3 | - | 4 个并发 worker |
| **实盘信号** | `getrich-signals.service`（oneshot）+ `getrich-signals.timer` | 4 | - | 每 5 分钟触发一次 |

详见 [systemd 部署](systemd.md)。

---

## 4. 关键文档

<div class="grid cards" markdown>

-   :material-server: **systemd 部署**

    ---

    4 个 unit + 1 target 详解

    [:octicons-arrow-right-24: 查看](systemd.md)

-   :material-database: **数据库迁移**

    ---

    getrich-migrate 4 子命令详解

    [:octicons-arrow-right-24: 查看](migration-runner.md)

-   :material-pulse: **监控与告警**

    ---

    Flower + pg_notify + 告警通道（Phase 2）

    [:octicons-arrow-right-24: 查看](monitoring.md)

-   :material-alert: **故障 Runbook**

    ---

    8 个常见故障处理清单（Phase 2）

    [:octicons-arrow-right-24: 查看](runbook.md)

</div>

---

## 5. 数据库拓扑

### 5.1 PostgreSQL

- 库名：`getrich`（注意：不是 `frontend`，业务库名是 `getrich`）
- 业务 schema：`frontend`（所有业务表在 `frontend.*` 下）
- 连接池：`pg_pool` 强制 `SET search_path=frontend`
- 异步：`psycopg3` + `AsyncConnectionPool`

### 5.2 ClickHouse

- 数据库：默认 `getrich`（与 PG 一致）
- 行情表：`md_bars_1d` / `md_bars_1m` / `md_bars_5m` / ...
- 因子表：`md_factors`（长表 `(dt, symbol, factor, value)`）
- MergeTree 引擎，强制 `PARTITION BY toYYYYMM(dt)` + `ORDER BY (symbol, dt)` + `TTL dt + INTERVAL 5/10 YEAR`
- 客户端：`clickhouse_connect` 1.x

### 5.3 DuckDB

- 默认 `:memory:` 模式
- 可选 `DUCKDB_PARQUET_ROOT` 路径，加载本地 Parquet
- 用于 ad-hoc 报表分析

### 5.4 Redis

- Celery broker + result backend
- 缓存层（如 `/strategies/categories` 1h TTL）
- 默认 `redis://localhost:6379/0`

---

## 6. 环境变量矩阵

完整环境变量清单见 [参考 / 环境变量](../reference/env-vars.md)。常用：

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `APP_ENV` | `dev` | ✅ | `dev` / `prod` / `research` |
| `PG_HOST` | `100.80.19.6` | ✅ | PostgreSQL 地址 |
| `PG_DB` | `getrich` | ✅ | 业务库名 |
| `CLICKHOUSE_HOST` | - | ✅ | ClickHouse 地址 |
| `GETRICH_BROKER_URL` | `redis://localhost:6379/0` | ✅ | Redis |
| `GETRICH_WORKER_BACKEND` | `inproc` | - | `inproc` / `celery` |
| `JWT_SECRET` | `getrich-dev-secret-change-in-prod` | ✅ 生产 | JWT 签名 |
| `BACKTEST_ARTIFACT_DIR` | `tmp/artifacts` | ✅ 生产 | artifact 存储（防 path traversal） |
| `CSP_POLICY` | 默认 | ✅ 生产 | Content-Security-Policy |

---

## 7. 备份策略

| 数据 | 频率 | 保留 | 工具 |
|---|---|---|---|
| PostgreSQL | 每天 03:00 | 30 天 | `pg_dump` + 对象存储 |
| ClickHouse | 每天 03:30 | 30 天 | ClickHouse 自带 backup |
| artifact | 实时同步 | 90 天 | S3 / OSS 生命周期 |
| Redis | 不需要（可重建） | - | - |

---

## 8. 下一步

- [systemd 部署](systemd.md) —— 4 个 unit + 1 target 详解
- [数据库迁移](migration-runner.md) —— 命名规范、幂等、CH/PG 差异
- [监控](monitoring.md) —— Flower + 告警
- [Runbook](runbook.md) —— 8 个故障处理
