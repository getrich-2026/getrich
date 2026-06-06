# GetRich — AI 本地开发指令集

本文档仅定义针对 `GetRich` 平台的本地化/项目级开发约束。全局通用原则及智能体调度详见全局 `~/.claude/CLAUDE.md`。

## 1. 运行环境与特定约束
- **Node.js 依赖**：前端基于 Vite 7 + React 19。统一使用 `npm run dev` 启动开发服务器，使用 `npm run build` 执行生产打包。

## 2. 数据库职责划分（GetRich 铁律）
项目采用多数据库协同架构，各数据库职责边界清晰，**绝对禁止越权使用**：

1. **PostgreSQL (`getrich` 库) — 业务与事务的唯一主库**
   - 存储实体：策略元数据、实盘信号记录、用户订阅、账户资产快照、支付账单、交易订单及系统配置。
   - 约束：任何需要事务安全性、主外键约束、或者依赖 `ON CONFLICT` 进行原子 UPSERT 的高频业务数据，必须且仅能写入 PostgreSQL。使用 `psycopg3` + 异步连接池，手写原生 SQL，禁止引入 heavy ORM。
2. **ClickHouse — 行情与因子的海量时序存储**
   - 存储实体：分钟线/日线 OHLCV bars、Tick 逐笔数据、海量因子计算的时序输出。
   - 约束：只允许做大批量写入 (Batch Write) 和基于 Symbol/Time 范围的快速分析查询。**绝对禁止**将 ClickHouse 用于需要事务更新、状态修改的业务流程。持久化表必须使用 `MergeTree` 系列引擎，并强制配置 `PARTITION BY`、`ORDER BY` 和 `TTL`。
3. **DuckDB — 高效临时内存计算**
   - 职责：用于 ad-hoc 一次性分析、回测时的中间数据交互及高速本地 Parquet 报表分析。
   - 约束：不进行物理持久化，只用作内存临时计算层，不可作为任何业务的终态存储。

## 3. 量化与时序规范

### 3.1 严格的时区对齐
- **主时区**：平台统一采用 `Asia/Shanghai (UTC+8)`。
- **PostgreSQL**：在 `pool.py` 初始化时已强制设置 `SET timezone='Asia/Shanghai'`。所有写入的 timestamp 必须显式处理时区。
- **ClickHouse**：行情表及因子表中的时间字段必须采用 `DateTime64(3, 'Asia/Shanghai')` 类型。写入 `Date`/`Date32` 等 naive 日期时，必须在 Python 端提前转换为 aware datetime 并用 `.astimezone(tz).date()` 提取，防止因 UTC 偏移导致日期提早或延后一天。
- **夜盘处理**：包含跨日夜盘（如 21:00 至次日 02:30）的时序数据必须统一使用 `DateTime64`，绝对禁止使用 `Date` 进行区分。

### 3.2 统一的列名与字段
- 统一使用标准 OHLCV 字段名，禁止使用任何缩写或变体：
  `open, high, low, close, volume, vwap, oi, symbol, dt`
- 涉及财务金额、PnL、可用资金计算时，标量一律强制使用高精度的 `decimal.Decimal`，禁止使用 `float` 以免产生累积舍入误差。
- 收益率计算必须显式区分单利收益率 (`simple_return`) 与对数收益率 (`log_return`)，且必须在函数签名及 Docstring 中清晰注明。

## 4. 前后端编码规范

### 4.1 后端特定规范
- **SQL 编写**：直接使用原生 SQL，大批量写入时优先使用 `psycopg` 的 COPY 协议或 multi-values UPSERT (`ON CONFLICT DO UPDATE`)。

### 4.2 前端特定规范 (React 19 + TypeScript 5.9)
- **禁止 any**：严格推导类型，除非对接无类型的外部遗留包且附加详细说明，否则禁止使用 `any`。
- **数据请求**：统一在 `src/api/` 下编写模块化接口函数（如 `strategies.ts`），前端组件一律通过 `@tanstack/react-query`（`useQuery`/`useMutation`）管理异步数据与加载态，**禁止**在组件内部使用 `useEffect` + `useState` 手写 API 轮询。
- **表单校验**：表单组件必须使用 `react-hook-form` 结合 `zod` 校验器进行严格前端输入验证。
- **UI 与图表**：优先选用 `src/components/ui/`（基于 shadcn/ui + Radix UI）的无样式基础组件，由 CLI 统一管理，不手动更改 UI 源码。时序/权益曲线图表优先选择 `echarts` 绘制；其余常规图表可采用 `recharts`。
- **用户内容 XSS 防御**：渲染用户/作者提供的 HTML (`strategy.detail_html` 等) **必须**通过 `frontend/src/lib/sanitize.ts::sanitizeHtml()` 包装后再传给 `dangerouslySetInnerHTML`。裸的 `dangerouslySetInnerHTML` 会被本地 ESLint 规则 `getrich/no-unsanitized-danger` 拦截（`frontend/src/lib/eslint-plugin-no-unsanitized-danger.cjs`），仅放行 `sanitizeHtml()` / `DOMPurify.sanitize()` / `bleach.clean()` 之一的包裹形式。四层防御纵深：①表单 zod 长度上限 ②后端 Pydantic `max_length` + bleach 归一化 ③Postgres `CHECK` 约束（`migrations/024_*.sql`）④API 响应 `Content-Security-Policy` 头（`apps/web/middleware.py::SecurityHeadersMiddleware`，协议级最后一道兜底）。

## 5. 常用开发命令

### 后端常用命令 (使用 `uv` 驱动)
```bash
# 本地启动 FastAPI 开发服务器
uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000
```

### 回测包常用命令
```bash
# 执行回测包测试
uv run pytest tests/getrich_backtest -v

# 执行回测包 Ruff 静态检查
uv run ruff check src/getrich_backtest tests/getrich_backtest

# 检查回测包格式
uv run ruff format --check src/getrich_backtest tests/getrich_backtest

# 执行回测包类型检查（若环境已安装 basedpyright）
uv run basedpyright src/getrich_backtest
```

### 前端常用命令
```bash
# 本地启动 Vite 开发服务 (默认 5173 端口)
npm run dev

# 静态类型检查与生产环境构建打包
npm run build

# 执行前端 ESLint 静态代码检查
npm run lint
```

## 6. 开发进度文档规范 (.agent/brain/)

为了在多个 AI 会话间无缝继承开发进度，必须严格维护 `.agent/brain/` 下的进度文档：

1. **读取规范**：每次新会话开始时，首要任务是读取 `.agent/brain/NOTES.md` 以恢复状态与获取待办，其次阅读 `.agent/brain/TODO.md` 查看 Web API 等持久技术参考。
2. **会话结束更新**：只要本次会话中发生了实质性的代码变更、数据库表结构调整或技术方案抉择，必须在结束 turn 前更新 `.agent/brain/NOTES.md`，将当前进度、最近变更、接下来的 P0/P1 TODO 事项及已知技术债落盘。
3. **自改进记录 (Self-Improvement)**：若开发过程中出现了由于 AI 误判导致的用户纠错或测试失败，必须将错误模式、根本原因及防范策略以”技术债/踩坑记录”的形式记录于 `.agent/brain/NOTES.md` 或本指令集中，防止在下个会话中犯同样的错误。

## 7. 禁止事项 (Don'ts 铁律)
- **绝对禁止**在 ClickHouse 中执行事务更新或行级频繁删除操作。
- **绝对禁止**在没有对齐时间轴（`shift`）的情况下使用行情或因子数据，防止 look-ahead bias。
- 对于超过 100,000 行的大规模数据集，**绝对禁止**保存为普通 CSV 格式，必须统一采用高性能、高压缩率的 `Parquet` 格式（选用 `zstd` 压缩）。
- **绝对禁止**在没有异常捕获 (`try-except`) 隔离的情况下在主线程中启动外部 API调用或网络请求。
- **绝对禁止**使用 destructive 命令如 `git reset --hard` 修改用户的工作区未提交代码。
- **绝对禁止**在浏览器组件中未通过 `frontend/src/lib/sanitize.ts::sanitizeHtml()`（或同等的 `DOMPurify.sanitize()` / `bleach.clean()`）包装就直接 `dangerouslySetInnerHTML` 渲染用户/作者提供的内容；本地 ESLint 规则 `getrich/no-unsanitized-danger` 会在 CI 阶段拦截裸 sink。
- **绝对禁止**在 `apps/web/main.py::create_app()` 中移除 `SecurityHeadersMiddleware` —— 这是协议级 XSS 兜底（`Content-Security-Policy` / `X-Frame-Options` / `nosniff` / `Referrer-Policy`），同时也是 OWASP 推荐做法。新增路由/中间件时，测试必须用 `TestClient` 验证响应仍带这 4 个头。

## 6. 数据库迁移（Migration）约定

所有 PostgreSQL / ClickHouse schema 变更必须通过 `migrations/*.sql` 文件提交，并由 `python -m getrich.migrations.cli` 应用。**禁止**手动 `psql` 在生产 / 测试环境跑未走 runner 的 SQL。

### 命名规范
- 文件名前缀为 3+ 位数字（`001_xxx.sql`），决定应用顺序。
- 数字必须**连续**（不允许 `001 → 003` 跳过 `002`），runner 会拒绝。
- 不得有重复前缀，runner 会拒绝。
- PostgreSQL migration 放在 `migrations/`；ClickHouse migration 放在 `migrations/clickhouse/`。

### 应用 migration
```bash
# 应用 PostgreSQL migrations（默认目标）
python -m getrich.migrations.cli postgres

# 应用 ClickHouse migrations
python -m getrich.migrations.cli clickhouse

# 应用两个数据库的 migrations（推荐部署流程）
python -m getrich.migrations.cli all

# 只打印发现 / 已应用状态，不执行 SQL
python -m getrich.migrations.cli status

# 试跑：列出将应用哪些 migration 但不实际执行
python -m getrich.migrations.cli postgres --dry-run
```

### 编写规范
- 优先使用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 等幂等语句，方便重跑。
- 一个文件一个逻辑主题（一张表、一个 index、一组相关 ALTER），便于 review。
- 破坏性变更（DROP / TRUNCATE）必须先在 NOTES.md 风险评估。
- 新增列必须显式带 `DEFAULT`（避免大表 NOT NULL 失败）。
- ClickHouse migration 由于没有跨语句事务，**必须**幂等。
