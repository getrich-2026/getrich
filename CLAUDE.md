# GetRich — AI 开发指令

## 1. 角色定义

**角色**：全栈量化信号平台开发者（后端 Python / 前端 React TypeScript）。
**原则**：正确性优先，性能次之。在不影响业务关键路径的前提下，可接受轻微的性能欠缺，但不可接受逻辑错误或数据错误。

---

## 2. 技术栈

### 后端（Python）

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI >= 0.115 + Uvicorn + Pydantic >= 2.7 + orjson |
| 主业务库 | **PostgreSQL**（策略/信号/订阅/用户/订单）via psycopg3 + AsyncConnectionPool |
| 行情时序库 | **ClickHouse**（bars/ticks/因子序列）via clickhouse-connect |
| 内存计算 | DuckDB（临时分析，不持久化） |
| 数据处理 | polars > numpy 向量化 > pandas（仅兼容场景） |
| 静态检查 | ruff + basedpyright |

### 前端（TypeScript）

| 层 | 技术 |
|---|---|
| 框架 | React 19 + TypeScript 5.9 + Vite 7 |
| 路由 | react-router-dom 7（HashRouter） |
| 异步状态 | @tanstack/react-query 5 |
| HTTP | axios 1（`src/api/client.ts` 单例） |
| UI | Tailwind CSS 3 + shadcn/ui（基于 radix-ui） |
| 图表 | recharts 2 + echarts 6 |
| 表单 | react-hook-form 7 + @hookform/resolvers + zod 4 |

---

## 3. 数据库职责划分（关键约定）

**严格遵守，不得混用职责：**

- **PostgreSQL (`goldmine` 库)** — 唯一的业务主库：
  - 策略元数据、绩效快照、回测报告
  - 信号、订单、订阅、用户、支付
  - 任何需要事务、外键约束、UPSERT 的业务数据

- **ClickHouse** — 仅用于时间序列行情数据：
  - 分钟/日线 OHLCV bars、tick 数据
  - 因子序列（大批量写入、范围扫描场景）
  - **禁止**在 ClickHouse 存储业务状态或做事务操作

- **DuckDB** — 临时内存分析：
  - 一次性 ad-hoc 计算、回测中间结果
  - 不持久化，不作为生产存储

---

## 4. 量化领域规范

### 4.1 时区

- **统一时区**：`Asia/Shanghai (UTC+8)`，通过 `zoneinfo` 或 `pytz` 处理。
- PG 连接级设置 `SET timezone='Asia/Shanghai'`（已在 `pool.py` 的 `options` 中配置，所有连接自动继承）。
- ClickHouse：`DateTime64(3, 'Asia/Shanghai')` 对应 aware datetime，直接使用；`Date`/`Date32` 为 naive date，写入前必须 `.astimezone(tz).date()` 以避免 UTC 偏移。
- 夜盘数据（23:00–02:30）必须用 `DateTime64`，禁止用 `Date`。

### 4.2 字段命名

标准 OHLCV 列名：`open, high, low, close, volume, vwap, oi, symbol, dt`。全项目统一，不得使用缩写变体。

### 4.3 财务计算

- 标量 PnL / 金额：使用 `decimal.Decimal`。
- 收益率：明确区分 `log_return` 与 `simple_return`，函数名和 docstring 中显式标注。

### 4.4 回测原则

- 滑点、手续费、资金约束必须纳入回测，不可假设零成本。
- 绩效指标命名保持一致：`sharpe_ratio`, `max_drawdown`, `annualized_return`, `win_rate`。

### 4.5 执行前置检查

交易执行逻辑**必须**包含：价格区间验证、最大下单量限制、流动性约束。

---

## 5. ClickHouse Schema 规范（行情表）

```sql
-- 时间序列表（bars / ticks）
CREATE TABLE {table_name} (
    dt     DateTime64(3, 'Asia/Shanghai') CODEC(Delta, ZSTD(1)),
    symbol LowCardinality(String),
    open   Float64 CODEC(ZSTD(1)),
    high   Float64 CODEC(ZSTD(1)),
    low    Float64 CODEC(ZSTD(1)),
    close  Float64 CODEC(ZSTD(1)),
    volume Float64 CODEC(ZSTD(1))
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 5 YEAR;
```

**强制规则**：
- 持久化表只用 `MergeTree` 家族引擎。
- 每张表必须有 `PARTITION BY`、`ORDER BY`、`TTL`。
- Symbol 类字段用 `LowCardinality(String)`。
- Tick 时间戳用 `CODEC(DoubleDelta, ZSTD(1))`；`LowCardinality` / `Enum8` / `UInt8` 不加 CODEC。

---

## 6. 项目结构

```text
getrich/
├── src/                               # 前端 React TypeScript
│   ├── main.tsx                       # React 入口
│   ├── App.tsx                        # HashRouter + 路由配置
│   ├── api/                           # Axios 客户端
│   │   ├── client.ts                  # Axios 单例（拦截器、基 URL）
│   │   ├── strategies.ts
│   │   ├── signal.ts
│   │   └── subscription.ts
│   ├── components/
│   │   ├── ui/                        # shadcn/ui 组件（通过 CLI 管理，不手改）
│   │   └── (业务组件: StrategyCard, SignalCard, EquityChart …)
│   ├── pages/                         # 5 个页面
│   │   ├── MarketPage.tsx
│   │   ├── StrategiesPage.tsx
│   │   ├── StrategyDetail.tsx
│   │   ├── SignalDetail.tsx
│   │   └── KnowledgePage.tsx
│   ├── hooks/
│   ├── types/                         # TypeScript 类型定义
│   └── lib/
│
├── src/getrich/                       # 后端 Python 包
│   ├── apps/
│   │   ├── web/                       # FastAPI 应用
│   │   │   ├── main.py                # 应用工厂 + lifespan（PG 连接池）
│   │   │   ├── deps.py                # get_db / get_current_user / page_dep
│   │   │   ├── response.py            # ApiResponse 包装 + 异常 handler
│   │   │   ├── pagination.py
│   │   │   ├── errors.py
│   │   │   ├── routers/               # 6 个路由（strategies/signals/subscriptions/
│   │   │   │                          #   signal_settings/user/payments）
│   │   │   ├── services/              # 业务逻辑层（原生 SQL，不用 ORM）
│   │   │   └── schemas/               # Pydantic 请求体
│   │   ├── gateway/                   # 交易网关（经纪商适配器）
│   │   └── strategy/                  # 策略引擎（纯逻辑，参数由 config 注入）
│   ├── config/
│   │   └── settings.py                # 三库配置 + WebConfig（单例 `settings`）
│   ├── libs/
│   │   ├── clickhouse/                # CH 连接池（行情查询）
│   │   ├── postgres/pool.py           # PG 异步连接池（psycopg3）
│   │   └── quant_duckdb.py            # DuckDB 内存计算工具
│   └── optionLib/                     # 期权定价与 Greeks
│
├── tests/
├── pyproject.toml
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── NOTES.md                           # 开发进度快照（AI 每次会话后更新）
└── TODO.md                            # 待办（详细设计文档）
```

**模块边界**：
- `apps/gateway/` — 经纪商适配器，对外暴露统一交易接口。
- `apps/strategy/` — 纯策略逻辑，参数通过 config 注入，不直接调用外部 API。
- `libs/` — 跨模块复用的连接池与工具，不含业务逻辑。

---

## 7. 后端编码规范

```python
from __future__ import annotations  # 所有 Python 文件顶部必须有
```

- Python 3.10+，强制类型注解（basedpyright `typeCheckingMode = "all"`）。
- 工具脚本 / 独立模块需包含 `if __name__ == "__main__":` 块，内含可直接运行的最小示例（MRE）。
- 错误处理：主动处理 `NaN`、`Inf`、除零、空 DataFrame。
- 注释语言：复杂逻辑用简体中文注释；变量/函数名用英文；日志消息用英文（便于 grep）。
- 不用 ORM，手写 SQL（与 PG 函数、UPSERT、JSONB 直接配合）。
- UPSERT：优先 `ON CONFLICT ... DO UPDATE`，减少应用层去重。

---

## 8. 前端编码规范

- 严格 TypeScript，禁止 `any`（除非对接无类型外部库时明确注释原因）。
- 所有接口类型定义放 `src/types/`，与后端 Pydantic schema 保持字段对齐。
- API 调用只通过 `src/api/` 下的模块，不在组件内直接 `axios.get(...)`。
- 异步数据请求用 `@tanstack/react-query`（`useQuery` / `useMutation`），不手写 `useEffect + useState` 管理加载状态。
- 表单用 `react-hook-form` + `zod` schema 校验。
- UI 组件优先使用 `src/components/ui/`（shadcn/ui），`ui/` 下的文件通过 shadcn CLI 管理。
- 图表：时序/权益曲线用 echarts；其余统计图表用 recharts。
- 环境变量：前端变量名前缀 `VITE_`，敏感值不提交到版本控制。

---

## 9. 常用命令

```bash
# 后端
uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000
pytest tests/ -v
ruff format src/getrich/
ruff check src/getrich/ --fix
pip install -e .

# 前端
npm run dev       # Vite 开发服务器（默认 :5173）
npm run build     # tsc -b && vite build
npm run lint      # eslint
```

---

## 10. NOTES.md 规范

项目根目录维护一个 `NOTES.md`，用于跨会话快速同步开发状态。

**AI 会话规则**：
1. 每次新会话开始时，先读 `NOTES.md` 以恢复上下文；需要查 API 端点设计、启动命令或设计取舍时再读 `TODO.md`。
2. 本次会话有实质性变更（新增/修改功能、关键决策、schema 变更、重要 bug 修复）时，在会话结束前更新 `NOTES.md`。
3. **所有 TODO 只写 `NOTES.md`**，不在 `TODO.md` 维护待办。`TODO.md` 是 Web API 技术参考（端点表 / 设计取舍 / 启动命令），内容相对稳定。

**`NOTES.md` 结构模板**：

```markdown
# NOTES — GetRich 开发进度

## 当前状态
<一句话描述整体进度>

## 最近变更
- YYYY-MM-DD: <变更描述>（影响：<文件或模块>）

## TODO
- [ ] <P0 项>
- [ ] <P1 项>

## 关键决策
- <决策内容> — <原因> — <日期>

## 已知问题 / 技术债
- <问题描述>（影响：<范围>）
```

**与 `.agent/brain/` 的区别**：
- `NOTES.md` — 技术状态快照，供人和 AI 快速阅读。
- `.agent/brain/active_tasks.md` — 当前会话任务调度。
- `.agent/brain/work_log.md` — 工作流水日志。

---

## 11. 关键配置参考

| 配置项 | 位置 |
|---|---|
| 三库配置（连接参数） | `src/getrich/config/settings.py` + `.env` |
| PG 连接池 | `src/getrich/libs/postgres/pool.py` |
| API 基础 URL | `.env` → `VITE_API_BASE_URL` |
| Ruff / basedpyright | `pyproject.toml` |
| Tailwind 主题 | `tailwind.config.js` + `src/index.css` |
| shadcn 组件配置 | `components.json` |
