# 环境变量

本节提供 `GETRICH_*` 全部环境变量的完整清单。**所有变量的唯一真源是 `src/getrich/config/settings.py`**；这里只是镜像展示。

---

## 1. 基础

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `APP_ENV` | `dev` | ✅ | `dev` / `prod` / `research` |
| `STRICT_MODE` | `false` | - | 严格模式（额外的运行时检查） |
| `LOG_LEVEL` | `INFO` | - | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FMT` | `[%(asctime)s][%(name)s][%(levelname)s] %(message)s` | - | 日志格式 |
| `LOG_FILE` | - | - | 可选日志文件路径 |

---

## 2. PostgreSQL

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `PG_HOST` | `100.80.19.6` | ✅ | 数据库地址 |
| `PG_PORT` | `5432` | ✅ | 端口 |
| `PG_USER` | - | ✅ | 用户名 |
| `PG_PASSWORD` | - | ✅ | 密码 |
| `PG_DB` | `getrich` | ✅ | 业务库名（注意：不是 `frontend`，`frontend` 是 schema 名） |
| `PG_POOL_MIN` | `2` | - | 连接池最小连接数 |
| `PG_POOL_MAX` | `20` | - | 连接池最大连接数 |

> **业务库命名**：项目业务库名是 `getrich`（与 settings.py 中 `cfg.database` 一致），业务 schema 是 `frontend`。所有迁移 SQL 内部使用 `frontend.users` 等全限定引用。

---

## 3. ClickHouse

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `CLICKHOUSE_HOST` | - | ✅ | 数据库地址 |
| `CLICKHOUSE_PORT` | `8123` | ✅ | HTTP 端口 |
| `CLICKHOUSE_USER` | - | ✅ | 用户名 |
| `CLICKHOUSE_PASSWORD` | - | ✅ | 密码 |
| `CLICKHOUSE_DB` | `getrich` | ✅ | 数据库名（与 PG 一致） |
| `CLICKHOUSE_PROTOCOL` | `http` | - | `http` / `https`（注：`clickhouse_connect` 1.x 用 `secure=bool`，旧 `protocol=` 已废弃） |

---

## 4. Web API

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `WEB_HOST` | `0.0.0.0` | - | API 绑定地址 |
| `WEB_PORT` | `8000` | - | API 端口 |
| `WEB_CORS_ORIGINS` | `*`（dev） | - | CORS 白名单；**生产必须**列出具体 origin |
| `JWT_SECRET` | `getrich-dev-secret-change-in-prod` | ✅ 生产 | JWT 签名密钥（≥ 32 字符强随机） |
| `JWT_EXPIRE_MINUTES` | `1440` | - | Access Token 有效期（24h） |
| `JWT_REFRESH_EXPIRE_HOURS` | `168` | - | Refresh Token 有效期（7d） |
| `CSP_POLICY` | 默认值含 `unsafe-inline` / `unsafe-eval` | ✅ 生产 | Content-Security-Policy；**生产必须**移除不安全指令 |

---

## 5. Worker 池

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `GETRICH_WORKER_BACKEND` | `inproc` | - | `inproc`（同进程直接调用）/ `celery`（Celery 队列） |
| `GETRICH_BROKER_URL` | `redis://localhost:6379/0` | ✅ | Celery broker |
| `GETRICH_RESULT_BACKEND` | `redis://localhost:6379/1` | ✅ | Celery 结果存储 |
| `GETRICH_FLOWER_URL` | `http://localhost:5555` | - | Flower UI 监控（Celery） |

> **CI 强制**：`GETRICH_WORKER_BACKEND=celery` —— 让 router 测试走 dispatch 路径而无需起真实 worker。

---

## 6. 存储 / Artifact

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `BACKTEST_ARTIFACT_DIR` | `tmp/artifacts` | ✅ 生产 | Tear Sheet / Parquet 等 artifact 存储根目录（**绝对路径**） |
| `DUCKDB_PATH` | `:memory:` | - | DuckDB 数据库路径（`:memory:` 或绝对路径） |
| `DUCKDB_PARQUET_ROOT` | - | - | 可选 Parquet 根目录 |

> **安全**：`BacktestStorageConfig` 校验 `BACKTEST_ARTIFACT_DIR` 防 path traversal；生产必须设为绝对路径（如 `/var/lib/getrich/artifacts`）。

---

## 7. 信号 / 风控

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `SIGNAL_ALERT_WEBHOOK_URL` | - | - | Webhook 告警 URL（LiveRiskMonitor） |
| `SIGNAL_ALERT_EMAIL_FROM` | - | - | Email 告警发件人 |
| `SIGNAL_ALERT_EMAIL_TO` | - | - | Email 告警收件人（逗号分隔） |
| `SIGNAL_ALERT_EMAIL_SMTP` | - | - | SMTP 地址 |

---

## 8. 第三方数据

| 变量 | 默认 | 必填 | 说明 |
|---|---|---|---|
| `RICEQUANT_ENABLED` | `false` | - | 启用 RICEQUANT 行情源 |
| `RICEQUANT_API_KEY` | - | - | RICEQUANT API Key |
| `ENABLE_INSIGHT` | `false` | - | 启用 Insight 模块 |
| `INSIGHT_USER` | - | - | Insight 用户名 |
| `INSIGHT_PASSWORD` | - | - | Insight 密码 |
| `ENABLE_HDB` | `false` | - | 启用 HDB 模块 |

---

## 9. .env.example 模板

```bash
# GetRich 生产环境变量模板
APP_ENV=prod

# PG
PG_HOST=db.internal
PG_PORT=5432
PG_USER=getrich
PG_PASSWORD=<STRONG_PASSWORD>
PG_DB=getrich
PG_POOL_MIN=2
PG_POOL_MAX=20

# ClickHouse
CLICKHOUSE_HOST=ch.internal
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=getrich
CLICKHOUSE_PASSWORD=<STRONG_PASSWORD>
CLICKHOUSE_DB=getrich
CLICKHOUSE_PROTOCOL=https

# Redis
GETRICH_BROKER_URL=redis://redis.internal:6379/0
GETRICH_RESULT_BACKEND=redis://redis.internal:6379/1

# Web
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_CORS_ORIGINS=https://app.getrich.com
JWT_SECRET=<32+字符强随机>
CSP_POLICY=default-src 'self'; script-src 'self'; style-src 'self' 'nonce-XXX'

# Worker
GETRICH_WORKER_BACKEND=celery
GETRICH_FLOWER_URL=http://flower.internal:5555

# 存储
BACKTEST_ARTIFACT_DIR=/var/lib/getrich/artifacts
DUCKDB_PATH=/var/lib/getrich/duckdb/getrich.duckdb

# 告警
SIGNAL_ALERT_WEBHOOK_URL=https://alerts.internal/webhook
SIGNAL_ALERT_EMAIL_FROM=alerts@getrich.com
SIGNAL_ALERT_EMAIL_TO=ops@getrich.com,risk@getrich.com
```

---

## 10. 校验

CI 在启动时调用 `Settings()`，校验必填变量；缺失时 `ValidationError` 立即退出。

源码：[`src/getrich/config/settings.py`](https://github.com/getrich/getrich/blob/main/src/getrich/config/settings.py)
