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

## 5. 常用开发命令

### 后端常用命令 (使用 `uv` 驱动)
```bash
# 本地启动 FastAPI 开发服务器
uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000
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

## 6. NOTES.md 规范与自改进
为了在多个 AI 会话间无缝继承开发进度，必须严格维护根目录下的 `NOTES.md` 文件：
1. **读取规范**：每次新会话开始时，首要任务是读取 `NOTES.md` 以恢复状态与获取待办，其次阅读 `TODO.md` 查看 Web API 等持久技术参考。
2. **会话结束更新**：只要本次会话中发生了实质性的代码变更、数据库表结构调整或技术方案抉择，必须在结束 turn 前更新 `NOTES.md`，将当前进度、最近变更、接下来的 P0/P1 TODO 事项及已知技术债落盘。
3. **自改进记录 (Self-Improvement)**：若开发过程中出现了由于 AI 误判导致的用户纠错或测试失败，必须将错误模式、根本原因及防范策略以“技术债/踩坑记录”的形式记录于 `NOTES.md` 或本指令集中，防止在下个会话中犯同样的错误。

## 7. 禁止事项 (Don'ts 铁律)
- **绝对禁止**在 ClickHouse 中执行事务更新或行级频繁删除操作。
- **绝对禁止**在没有对齐时间轴（`shift`）的情况下使用行情或因子数据，防止 look-ahead bias。
- 对于超过 100,000 行的大规模数据集，**绝对禁止**保存为普通 CSV 格式，必须统一采用高性能、高压缩率的 `Parquet` 格式（选用 `zstd` 压缩）。
- **绝对禁止**在没有异常捕获 (`try-except`) 隔离的情况下在主线程中启动外部 API调用或网络请求。
- **绝对禁止**使用 destructive 命令如 `git reset --hard` 修改用户的工作区未提交代码。
