# 仓库导览

> **本节带新贡献者 10 分钟走完 GetRich 仓库**。了解每个目录的职责、关键文件在哪、新代码加在哪。

---

## 1. 仓库结构总览

```text
getrich/
├── src/
│   ├── getrich_backtest/        # ⭐ 核心回测引擎（无 IO 依赖）
│   └── getrich/                 # 平台层（apps/ + libs/ + config/ + migrations/）
├── frontend/                    # Vite + React 19 + TS 前端
├── tests/                       # 镜像 src/ 的测试
├── migrations/                  # PG schema 演进
│   └── clickhouse/              # CH schema
├── docs/                        # MkDocs 文档站
├── scripts/                     # CI / 运维工具
├── reference/                   # OpenAPI 规范等参考
├── backtest/docs/               # 19 篇设计契约（docs.yml 自动嵌入）
├── .github/workflows/           # 4 个 CI workflow
├── .agent/brain/                # AI agent 笔记
├── docker-compose.yml           # 本地一键起服务
├── Dockerfile                   # 容器镜像
├── pyproject.toml               # Python 项目元数据 + 依赖
├── uv.lock                      # 锁定的依赖版本
├── mkdocs.yml                   # 文档站配置
└── LICENSE                      # MIT
```

---

## 2. `src/getrich_backtest/` —— 核心回测引擎

> **纯计算库**，无 IO 依赖（不连 DB、不写文件、不调 HTTP）。可在 notebook / 脚本 / 服务任意环境跑。

```
src/getrich_backtest/
├── __init__.py              # 公共 API 出口
├── api.py                   # Backtest.run() 主入口
├── result.py                # BacktestResult / CombinedResult / ResultView
├── runconfig.py             # RunConfig (frozen dataclass, fingerprint)
├── time.py                  # Shanghai TZ 工具 + require_shanghai_aware
├── types.py                 # Frequency enum, FREQ_TO_MINUTES, Order/Fill/Side/...
├── exceptions.py            # 异常类层级
├── analytics/               # compute_ic, factor_evaluation_report, ...
├── attribution/             # Brinson / FactorRegression / PnL / Session
├── cost.py                  # FeeModel + SlippageModel
├── data/                    # BarLoader 协议 + DataFrame/Pg/DuckDB 实现
├── execution.py             # NextBarMatchingModel + Order 状态机
├── account.py               # Account / Position / SubAccount
├── margin.py                # MarginCalculator
├── risk.py                  # RiskManager + RiskConfig
├── metrics.py               # BacktestMetrics 16 字段
├── benchmark.py             # Benchmark + compute_benchmark_comparison
├── report.py                # TearSheet + Reporter (Plotly / Matplotlib)
├── live/                    # Signal / SignalProducer / SignalWriter
├── persistence.py           # PgBacktestResultStore
├── sweep.py                 # SweepRunner (网格搜索)
├── walk_forward.py          # WalkForward (滚动/锚定)
├── walk_forward_report.py   # WalkForwardReport
├── sweep_persistence.py     # PgSweepResultStore
├── walk_forward_persistence.py # PgWalkForwardResultStore
├── job_persistence.py       # PgBacktestJobStore
├── strategy/                # Strategy 基类 / SignalStrategy / TargetPositionStrategy
│   ├── base.py
│   ├── signal.py
│   ├── target_position.py
│   ├── portfolio.py         # Portfolio + Constraints + Rebalance
│   ├── alloc_weight.py      # 6 个 WeightAllocator
│   └── preprocessor.py      # SignalPreprocessor 链
└── strategies/              # 内置策略
    ├── ma_cross.py
    └── bollinger_mr.py
```

### 2.1 新增代码加在哪

| 你想加什么 | 加到哪 |
|---|---|
| 新内置策略 | `src/getrich_backtest/strategies/<name>.py` + 加到 `strategies/__init__.py` |
| 新 WeightAllocator | `src/getrich_backtest/strategy/alloc_weight.py` |
| 新归因方法 | `src/getrich_backtest/attribution.py`（或新文件） |
| 新指标 | `src/getrich_backtest/metrics.py::BacktestMetrics` 字段 + `compute_metrics()` |
| 新 FeeModel / SlippageModel | `src/getrich_backtest/cost.py` |
| 新 BarLoader | `src/getrich_backtest/data/<your_loader>.py` + 实现协议 |
| 新异常 | `src/getrich_backtest/exceptions.py` |
| 新导出 | `src/getrich_backtest/__init__.py` |

> **导出前先 import** —— 公共 API 必须从 `__init__.py` 走，import path 才有意义。

---

## 3. `src/getrich/` —— 平台层

```
src/getrich/
├── apps/                     # 4 个 entry point app
│   ├── web/                  # FastAPI HTTP API
│   │   ├── main.py           # create_app() 入口
│   │   ├── middleware.py     # SecurityHeadersMiddleware
│   │   ├── deps.py           # get_db / require_user / request_id / page_dep
│   │   ├── response.py       # 全局异常 handler
│   │   ├── errors.py         # ApiError + 5 子类
│   │   ├── routers/          # 11 个 router（auth, strategies, ...）
│   │   ├── schemas/          # Pydantic request/response 模型
│   │   ├── services/         # 业务 service（apps/web/services/<name>.py）
│   │   └── pagination.py     # PageParams + make_page_params
│   ├── worker/               # Celery 异步任务
│   │   ├── celery_app.py
│   │   ├── tasks.py
│   │   ├── lifespan.py
│   │   ├── cancel_listener.py  # Round #1080 LISTEN/NOTIFY
│   │   └── cli.py            # 入口（systemd getrich-worker@.service）
│   ├── strategy/             # 实盘信号生成
│   │   ├── live_runner.py    # LiveSignalRunner.run_once
│   │   ├── live_data_provider.py
│   │   ├── live_risk.py      # LiveRiskMonitor + 3 AlertChannel
│   │   ├── signal_writer.py
│   │   ├── account_loader.py
│   │   ├── registry.py       # StrategyRegistry
│   │   ├── backtest_job_runner.py
│   │   ├── cli.py            # getrich-signals 入口
│   │   └── cli_multi.py
│   └── gateway/              # 预留 gateway 入口
├── libs/                     # 跨 app 复用的基础设施
│   ├── postgres/             # PgConnectionPool (psycopg3 async)
│   ├── clickhouse/           # ChPool (sync) + ChDatabase + ChTable
│   ├── logging.py
│   └── quant_duckdb.py
├── config/                   # pydantic-settings
│   └── settings.py           # 12 个 Config 类 + Settings
├── migrations/               # PG migration CLI 入口（区别于 migrations/）
│   ├── cli.py
│   ├── runner.py
│   └── executors.py
└── optionLib/                # 期权相关库（独立子包）
```

### 3.1 新增代码加在哪

| 你想加什么 | 加到哪 |
|---|---|
| 新 API endpoint | `apps/web/routers/<name>.py` + `main.py::create_app` 注册 |
| 新 service | `apps/web/services/<name>.py`（被 router 调用） |
| 新 Pydantic schema | `apps/web/schemas/<name>.py` |
| 新 Celery task | `apps/worker/tasks.py` |
| 新 AlertChannel | `apps/strategy/live_risk.py` |
| 新 Config 字段 | `config/settings.py` |
| 新 libs helper | `libs/<name>.py` |

---

## 4. `frontend/` —— 前端

```
frontend/
├── src/
│   ├── api/                  # 18 个 *.ts（每个对应 1 个后端 router）
│   │   ├── client.ts         # fetch wrapper + 401 interceptor + JWT 轮换
│   │   ├── auth.ts
│   │   ├── strategies.ts
│   │   ├── signals.ts
│   │   ├── backtestJobs.ts
│   │   ├── backtestRuns.ts
│   │   ├── backtestSweeps.ts
│   │   ├── backtestWalkForwards.ts
│   │   ├── backtestJobEvents.ts  # SSE client
│   │   ├── orders.ts
│   │   ├── signalSettings.ts
│   │   ├── subscriptions.ts
│   │   └── *.test.ts         # 镜像的 vitest 测试
│   ├── components/
│   │   ├── ProtectedRoute.tsx
│   │   ├── PublicRoute.tsx
│   │   ├── EquityCurveChart.tsx
│   │   └── ui/               # shadcn/ui 生成
│   ├── contexts/
│   │   └── AuthContext.tsx
│   ├── lib/
│   │   ├── sanitize.ts       # DOMPurify wrapper (XSS 防御)
│   │   ├── eslint-plugin-no-unsanitized-danger.cjs
│   │   └── utils.ts
│   ├── pages/
│   │   ├── Dashboard.tsx / Login.tsx / Register.tsx
│   │   ├── Strategies.tsx / StrategyDetail.tsx / StrategyEdit.tsx
│   │   ├── Signals.tsx / SignalDetail.tsx
│   │   ├── Trades.tsx / Orders.tsx / SignalSettings.tsx
│   │   └── backtests/        # 8 个 backtest 相关页面
│   ├── test/
│   │   └── fetch.ts          # vitest fetch mock helper
│   ├── App.tsx               # 路由树
│   ├── main.tsx              # React 19 root
│   └── index.css
├── public/                   # 静态资源
├── package.json
├── tsconfig.json
├── vite.config.ts            # 含 manualChunks
├── vitest.config.ts
└── eslint.config.js          # 含自定义 no-unsanitized-danger 规则
```

### 4.1 新增代码加在哪

| 你想加什么 | 加到哪 |
|---|---|
| 新 page | `src/pages/<Name>.tsx` + `App.tsx` 加 `<Route>` + nav 加 `<Link>` |
| 新 API 模块 | `src/api/<name>.ts` + `*.test.ts` |
| 新 shadcn 组件 | `npx shadcn@latest add <name>`（自动写 `components/ui/`） |
| 新 context | `src/contexts/<Name>.tsx` |
| 新通用 hook | `src/hooks/use<Name>.ts` |

---

## 5. `tests/` —— 测试（与 src/ 镜像）

```
tests/
├── getrich_backtest/         # 镜像 src/getrich_backtest/
│   ├── data/
│   ├── live/
│   ├── strategies/
│   ├── test_api.py
│   ├── test_metrics.py
│   ├── test_sweep.py
│   ├── test_walk_forward.py
│   ├── test_persistence.py
│   └── test_attribution.py
├── getrich/
│   ├── apps/
│   │   ├── web/              # router + service 测试
│   │   ├── worker/           # Celery tasks 测试
│   │   └── strategy/
│   ├── libs/                 # 池 + database 测试
│   ├── config/
│   └── migrations/
└── scripts/
    └── test_find_silent_fails.py
```

> **约定**：`tests/getrich_backtest/test_xxx.py` 镜像 `src/getrich_backtest/xxx.py`。

### 5.1 跑测试

```bash
# 后端（CI 跑）
uv run pytest tests/getrich_backtest tests/getrich/apps -x --timeout=60

# 前端（CI 跑）
cd frontend && npm run test -- --run

# 单独跑某个
uv run pytest tests/getrich_backtest/test_metrics.py -x -v
cd frontend && npm run test -- auth.test.ts
```

---

## 6. `migrations/` + `migrations/clickhouse/` —— Schema 演进

```
migrations/
├── 001_sub_account_routing.sql
├── 002_strategy_trades.sql
├── 003_users.sql
├── ...
├── 025_signals_reason_length.sql
└── clickhouse/
    ├── 001_ohlcv_bars.sql
    └── 002_factors_long.sql
```

### 6.1 命名规范

- 文件名前缀 3+ 位数字（`001_xxx.sql`）决定应用顺序
- 数字必须**连续**（不允许 `001 → 003` 跳过 `002`，runner 会拒绝）
- 不得有重复前缀（runner 会拒绝）
- 优先用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 幂等语句
- 破坏性变更（DROP / TRUNCATE）必须先在 NOTES.md 风险评估

### 6.2 新增 migration

```bash
# 1. 看下一个可用编号
ls migrations/ | tail -3
# 002_strategy_trades.sql ← 最大

# 2. 新文件
cat > migrations/003_users.sql <<'EOF'
CREATE TABLE IF NOT EXISTS frontend.users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
EOF

# 3. 试跑
uv run python -m getrich.migrations.cli postgres --dry-run

# 4. 应用
uv run python -m getrich.migrations.cli postgres

# 5. 验证
psql -U quant -d getrich -c "\d users"
```

> 详细：[migration-runner](../operations/migration-runner.md)

---

## 7. `docs/` + `mkdocs.yml` —— 文档站

```
docs/
├── index.md                  # 站点首页
├── getting-started/          # 新人 5min
├── engine/                   # 引擎用户指南（13 页，最详尽）
├── design-contracts/         # 19 篇设计契约（!include 嵌入 backtest/docs/）
├── platform/                 # 平台指南
├── operations/               # 运维指南
├── development/              # 开发指南
├── reference/                # 参考
└── about/                    # 关于
```

构建：`uv run mkdocs build --strict --clean`
预览：`uv run mkdocs serve --dev-addr 0.0.0.0:8001`

> 详细：[编码规范 — 文档](../development/coding-standards.md)

---

## 8. `.github/workflows/` —— CI

```
.github/workflows/
├── ci.yml                    # 4 主 job (lint + silent-fails + frontend + test) + 新加 docs
└── docs.yml                  # mkdocs build + 部署 gh-pages
```

> Round #1129 把 `docs` job 加进 `ci.yml` 作为 defense-in-depth（每个 PR 都跑 `mkdocs build --strict`，而 `docs.yml` 是 path-filtered 的）。

---

## 9. `scripts/` —— 工具脚本

```
scripts/
├── etl/                      # 行情 / 因子 ETL（独立子目录）
└── find_silent_fails.py      # Round #1059 silent-fail 扫描器（CI 用）
```

---

## 10. `reference/` —— 参考

```
reference/
├── getrich.openapi.json      # OpenAPI 3.1 规范（从 FastAPI 导出）
└── (其他规范)
```

> `mkdocs build` 不读这个目录；`platform/api-reference.md` 用 `<iframe>` 嵌入 Redoc 渲染 `getrich.openapi.json`。

---

## 11. `backtest/docs/` —— 19 篇设计契约

```
backtest/docs/
├── 00-index.md
├── 01-architecture.md
├── 10-data-layer.md
├── 11-data-quality.md
├── 12-calendar-tradability.md
├── 20-strategy-api.md
├── 21-portfolio-construction.md
├── 30-execution-engine.md
├── 31-account-margin.md
├── 32-risk-control.md
├── 40-metrics.md
├── 41-factor-eval.md
├── 42-benchmark-attribution.md
├── 43-stress-test.md
├── 50-param-search.md
├── 51-config-versioning.md
├── 52-report-visualization.md
└── 60-client-api.md
```

> 文档站 `docs/design-contracts/01-architecture.md` 等价于 `backtest/docs/01-architecture.md`（**用 `!include` 嵌入**，不复制）。

---

## 12. `.agent/brain/` —— AI 笔记

```
.agent/brain/
├── NOTES.md                  # 跨 session 进度笔记（最大）
└── TODO.md                   # 持久技术参考
```

> 新会话开始先读这两个文件。更新用 `Update NOTES.md`（CLAUDE.md §6）。

---

## 13. 配置与隐藏文件

| 文件 | 用途 |
|---|---|
| `pyproject.toml` | Python 项目元数据 + 依赖 + ruff/mypy 配置 |
| `uv.lock` | 锁定的依赖版本（**必须** commit） |
| `mkdocs.yml` | 文档站配置 |
| `tsconfig.json` | TypeScript 严格模式（noUnusedLocals / erasableSyntaxOnly） |
| `vite.config.ts` | 含 manualChunks（react/router/query/echarts/forms） |
| `vitest.config.ts` | Vitest 配置 |
| `eslint.config.js` | ESLint + 自定义 `getrich/no-unsanitized-danger` 规则 |
| `getrich-*.service` / `getrich-*.timer` | systemd 单元（生产） |
| `getrich-broker.service` | broker systemd 单元 |
| `Dockerfile` | 容器镜像 |
| `docker-compose.yml` | 本地开发栈 |
| `.env.example` | 环境变量模板（**不含密码**） |
| `.gitignore` | 排除 .env.local、.venv、node_modules、site、__pycache__ 等 |

---

## 14. 关键约定

### 14.1 命名

| 类型 | 命名 | 例 |
|---|---|---|
| 类 | PascalCase | `BacktestMetrics` |
| 函数 / 变量 | snake_case | `compute_metrics` |
| 常量 | UPPER_SNAKE | `FREQ_TO_MINUTES` |
| 私有 / 内部 | `_leading_underscore` | `_run_single` |
| 测试函数 | `test_<scenario>` | `test_insufficient_cash_raises` |

### 14.2 导入

- 公共 API 只能从 `getrich_backtest/__init__.py` 走
- 内部模块用相对导入（`from .account import Account`）
- 跨包用绝对导入（`from getrich.libs.postgres import pg_pool`）

### 14.3 Decimal vs float

> CLAUDE.md §3.2 铁律：所有金额 / 数量用 `Decimal`；**禁止** `float` 算 PnL。

### 14.4 时区

> CLAUDE.md §3.1 铁律：所有 `dt` 用 `Asia/Shanghai (UTC+8)` aware。

### 14.5 数据库

> CLAUDE.md §2 铁律：
> - 业务事务 → PG
> - 时序 / 因子 → CH
> - ad-hoc 分析 → DuckDB
> - **禁止越权使用**

---

## 15. 进一步阅读

- 编码规范：[开发指南 — 编码规范](../development/coding-standards.md)
- 测试：[开发指南 — 测试](../development/testing.md)
- 引擎用户指南：[engine/index](../engine/index.md)
- 平台架构：[platform/architecture](../platform/architecture.md)
- 数据库：[operations/database-topology](../operations/database-topology.md)
- 工具：
    - [Conventional Commits](https://www.conventionalcommits.org/) —— commit message 格式
    - [GitHub Flow](https://docs.github.com/en/get-started/quickstart/github-flow) —— PR 流程
