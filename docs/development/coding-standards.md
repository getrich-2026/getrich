# 编码规范

> **本节基于 [`CLAUDE.md`](https://github.com/getrich/getrich/blob/main/CLAUDE.md) 项目的工程规范**。任何修改以源文件为准；这里是面向开发者的导读版本。

---

## 1. 数据库职责铁律

**CLAUDE.md §2**：项目采用多数据库协同架构，**绝对禁止越权使用**。

### 1.1 三库职责

| 数据库 | 唯一职责 |
|---|---|
| **PostgreSQL** | 业务与事务的主库。`getrich` 库（**注意：业务库名是 `getrich`，不是 `goldmine`/`frontend`**）。策略元数据、实盘信号、订阅、订单、用户、refresh token、配置、backtest job 持久化等需要事务安全性的数据。 |
| **ClickHouse** | 行情与因子的海量时序存储。分钟线/日线 OHLCV、Tick、因子计算的时序输出。**只允许大批量写入和基于 Symbol/Time 范围的快速分析查询。** |
| **DuckDB** | 高效临时内存计算。ad-hoc 分析、回测中间数据交互、高速本地 Parquet 报表分析。**不进行物理持久化。** |

### 1.2 业务库命名

- **业务库名**：`getrich`（与 web 后端 service 连接字符串一致）
- **业务 schema 名**：`frontend`（所有业务表在 `frontend.*` 下）
- **migration runner**：会自动在 DSN 加 `options="-c search_path=frontend"`，但 SQL 内部**必须**全限定引用 `frontend.users` 等
- **连接池**：`src/getrich/libs/postgres/pool.py` 的 `pg_pool`，初始化时强制 `SET search_path=frontend`

### 1.3 PostgreSQL 使用规范

- `psycopg3` + 异步连接池（`AsyncConnectionPool`）
- 手写原生 SQL，**禁止引入 SQLAlchemy ORM 等 heavy ORM**
- 大批量写入用 `psycopg` 的 COPY 协议或 multi-values UPSERT (`ON CONFLICT DO UPDATE`)
- 业务表必须显式带 `DEFAULT` 子句（避免大表 NOT NULL 失败）

### 1.4 ClickHouse 使用规范

- `clickhouse_connect` 1.x（注意：早期 `protocol=` kwarg 已废弃，用 `secure=` 布尔值）
- 持久化表必须使用 `MergeTree` 系列引擎
- 强制配置 `PARTITION BY`、`ORDER BY` 和 `TTL`
- 不允许事务更新或行级删除
- 迁移必须幂等（CH 无跨语句事务）

---

## 2. 时序规范

**CLAUDE.md §3.1**：平台统一采用 `Asia/Shanghai (UTC+8)`。

### 2.1 时区

- **PostgreSQL**：`pool.py` 初始化时强制 `SET timezone='Asia/Shanghai'`
- **ClickHouse**：行情/因子表的时间字段用 `DateTime64(3, 'Asia/Shanghai')`
- 写入 `Date`/`Date32` 等 naive 日期时，**必须**在 Python 端先转为 aware datetime + `.astimezone(tz).date()` 提取

### 2.2 夜盘处理

包含跨日夜盘的时序数据（21:00 - 次日 02:30）必须用 `DateTime64(3, 'Asia/Shanghai')`，**绝对禁止**用 `Date`（日期类型会跨夜时丢失）。

### 2.3 关键工具

```python
from getrich_backtest import get_shanghai_tz, require_shanghai_aware, ensure_shanghai_aware

tz = get_shanghai_tz()  # ZoneInfo("Asia/Shanghai")
dt = datetime(2024, 1, 1, 9, 30, tzinfo=tz)  # 必须
```

`require_shanghai_aware(dt)` 在 naive datetime 上抛 `TimezoneError`。

---

## 3. 字段命名

**CLAUDE.md §3.2**：统一列名规范，**禁止**任何缩写或变体。

```
open, high, low, close, volume, vwap, oi, symbol, dt
```

财务金额、PnL、可用资金计算**必须**用 `decimal.Decimal`，**禁止** `float`。

收益率计算必须显式区分：

- `simple_return` = `(P_t - P_{t-1}) / P_{t-1}`
- `log_return` = `log(P_t / P_{t-1})`

函数签名 + docstring 必须明确说明使用哪种。

---

## 4. 后端编码规范

**CLAUDE.md §4.1**：

- 直接使用原生 SQL
- 大批量写入优先用 `psycopg` COPY 协议或 `ON CONFLICT DO UPDATE`
- 任何新加入的 `try/except: log` 必须配 `# silent-fail-ok: <reason>` 注释，否则 CI 静默失败扫描会拦截

---

## 5. 前端编码规范

**CLAUDE.md §4.2**：

### 5.1 TypeScript 严格模式

- **禁止 `any`**：严格推导类型；只有对接无类型外部包且附加详细说明时例外
- `from __future__ import annotations` 风格不适用 TS，但 type imports 区分 `import type`

### 5.2 数据请求

- 统一在 `src/api/` 写模块化接口函数（如 `strategies.ts`）
- 前端组件用 `@tanstack/react-query` 的 `useQuery`/`useMutation` 管理异步
- **禁止**在组件内 `useEffect` + `useState` 手写 API 轮询

### 5.3 表单校验

- 统一 `react-hook-form` + `zod` 校验器
- 严格前端输入验证

### 5.4 UI 组件

- 优先 `src/components/ui/`（基于 shadcn/ui + Radix UI）
- 时序/权益曲线图用 `echarts`
- 其他常规图用 `recharts`

### 5.5 XSS 防御（4 层）

1. **表单 zod 长度上限**（如 `max(2000)`）
2. **后端 Pydantic `max_length` + bleach 归一化**
3. **Postgres `CHECK` 约束**（`migrations/024_*.sql`）
4. **API 响应 `Content-Security-Policy` 头**（`apps/web/middleware.py::SecurityHeadersMiddleware`）

**铁律**：

- 渲染用户/作者提供的 HTML **必须**用 `frontend/src/lib/sanitize.ts::sanitizeHtml()` 包装
- 裸的 `dangerouslySetInnerHTML` 会被本地 ESLint 规则 `getrich/no-unsanitized-danger` 拦截
- 仅放行 `sanitizeHtml()` / `DOMPurify.sanitize()` / `bleach.clean()` 之一的包裹形式

### 5.6 不可移除的中间件

`apps/web/main.py::create_app()` 中的 `SecurityHeadersMiddleware`（CSP / X-Frame-Options / nosniff / Referrer-Policy）是协议级 XSS 兜底，**绝对禁止**移除。新增路由/中间件时，必须用 `TestClient` 验证响应仍带这 4 个头。

---

## 6. 数据库迁移（Migration）约定

**CLAUDE.md §6**：

### 6.1 命名

- 文件名 3+ 位数字前缀（`001_xxx.sql`），决定应用顺序
- **数字必须连续**（不允许 001 → 003 跳过 002），runner 会拒绝
- 不得有重复前缀，runner 会拒绝
- PostgreSQL migration 放 `migrations/`；ClickHouse migration 放 `migrations/clickhouse/`

### 6.2 应用

```bash
# PG（默认）
python -m getrich.migrations.cli postgres

# CH
python -m getrich.migrations.cli clickhouse

# 两库（推荐部署）
python -m getrich.migrations.cli all

# 只看状态
python -m getrich.migrations.cli status

# 试跑
python -m getrich.migrations.cli postgres --dry-run
```

### 6.3 编写规范

- 优先 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
- 一个文件一个逻辑主题
- 破坏性变更（DROP / TRUNCATE）必须先在 NOTES.md 风险评估
- 新增列必须显式带 `DEFAULT`
- ClickHouse migration 必须幂等（无跨语句事务）

---

## 7. 不可做的事 (Don'ts)

**CLAUDE.md §7**：

- ❌ 在 ClickHouse 中执行事务更新或行级频繁删除
- ❌ 在没有对齐时间轴 (`shift`) 的情况下使用行情或因子数据（防 look-ahead bias）
- ❌ 保存超过 100,000 行的 CSV（必须用 Parquet，zstd 压缩）
- ❌ 在主线程中启动外部 API 调用（必须有 try-except 隔离）
- ❌ 用 `git reset --hard` 修改工作区未提交代码
- ❌ 浏览器组件中裸 `dangerouslySetInnerHTML`（必须先 `sanitizeHtml()`）
- ❌ 在 `apps/web/main.py::create_app()` 中移除 `SecurityHeadersMiddleware`
