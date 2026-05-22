# GetRich — Gemini (Antigravity CLI) 本地开发指令集

本文档专门针对 `GetRich` 平台的本地化/项目级开发，为 **Gemini / Antigravity CLI** 智能体提供开发约束。全局通用原则及智能体调度详见全局 `~/.codex/AGENTS.md`。

---

## 1. 智能体运行模式与职责 (Agent Modes & Routing)

根据任务关键词，Antigravity CLI 必须自动切换到以下工作模式：

- **开发模式 (Developer Mode - `code-dev`)**：由 *写代码、改代码、实现、debug、加测试、重构、性能优化、脚本、SQL、ETL、PostgreSQL、ClickHouse* 等关键词触发。
  - 允许写入/修改代码、运行测试和命令。
  - 遵循 **Surgical Changes（手术式修改）**，只触碰与任务直接相关的代码，匹配已有风格，并清理无用导入/变量。
- **评审模式 (Reviewer Mode - `code-review`)**：由 *审代码、code review、找 bug、检查、风险评估、隐患* 等关键词触发。
  - **绝对禁止写入文件**。仅使用只读工具，按指定格式输出审计报告。
  - 以怀疑论视角审查时区偏差、Look-Ahead Bias、NaN 异常、并发安全等问题。
- **写作模式 (Writer Mode - `writer`)**：由 *写文章、写笔记、公众号、小红书、标题、文案、润色、提纲* 等关键词触发。
  - 撰写分析笔记或文章，执行发布前的 5 个核心问题 checklist，拒绝 AI 套话。

---

## 2. 核心架构与数据库铁律 (Database Architecture)

各数据库职责边界清晰，**绝对禁止越权使用**：

1. **PostgreSQL (`getrich` 库) — 业务与事务的唯一主库**
   - 存储实体：策略元数据、实盘信号记录、用户订阅、账户资产快照、支付账单、交易订单及系统配置。
   - 约束：任何需要事务安全性、主外键约束、或者依赖 `ON CONFLICT` 进行原子 UPSERT 的数据，必须且仅能写入 PostgreSQL。使用 `psycopg3` 异步连接池（`AsyncConnectionPool`），手写原生 SQL，**禁止引入 Heavy ORM**。
2. **ClickHouse — 行情与因子的海量时序存储**
   - 存储实体：分钟线/日线 OHLCV bars、Tick 逐笔数据、海量因子计算的时序输出。
   - 约束：只允许做大批量写入 (Batch Write) 和基于 Symbol/Time 范围的快速分析查询。**绝对禁止**将 ClickHouse 用于需要事务更新、状态修改的业务流程。持久化表必须使用 `MergeTree` 系列引擎，并强制配置 `PARTITION BY`、`ORDER BY` 和 `TTL`。
3. **DuckDB — 高效临时内存计算**
   - 职责：用于 ad-hoc 一次性分析、回测时的中间数据交互及高速本地 Parquet 报表分析。
   - 约束：不进行物理持久化，只用作内存临时计算层，不可作为任何业务的终态存储。
4. **Redis — 实盘低延迟缓存与消息队列**
   - 职责：实盘低延迟缓存、实时消息分发（Stream/Pub-Sub）、分布式锁及请求限流。
   - 约束：绝对禁止在 Redis 中存储复杂关系模型或海量历史时序数据。

---

## 3. Python 编码与量化规范 (Python & Quant Standards)

### 3.1 编码标准 (Python 3.10+)
- **首行声明**：所有 Python 源码文件的第一行必须是 `from __future__ import annotations`。
- **严格类型**：所有公共 API 签名、类定义和跨模块边界必须包含完整的 Type Hints 类型提示。
- **代码规范**：必须符合 PEP 8 规范，使用 `ruff format` 和 `ruff check --fix` 进行格式化与静态检查。
- **Google-Style Docstrings**：公共模块、类和核心函数必须编写 Google 风格文档字符串。**核心算法函数必须注明时间复杂度与空间复杂度**（例如：*Time Complexity: O(N log N)*）。
- **单例运行 (MRE)**：每个独立的 Python 文件底部必须包含 `if __name__ == "__main__":` 块，内置 realistic 模拟数据 and 本地运行逻辑，确保可独立执行和测试。
- **依赖管理**：统一且强制使用 `uv`，禁止直接使用 `pip`。

### 3.2 量化与时序规范
- **统一列名**：时序及 OHLCV 字段命名必须严格对齐：
  `open, high, low, close, volume, vwap, oi, symbol, dt`
- **高精度计算**：涉及财务金额、PnL、可用资金计算时，标量一律强制使用高精度的 `decimal.Decimal`，禁止使用 `float`。
- **收益率明确**：在函数签名及 Docstring 中必须显式区分单利收益率 (`simple_return`) 与对数收益率 (`log_return`)。
- **时区对齐**：平台统一采用 `Asia/Shanghai (UTC+8)`。ClickHouse 时序表中的时间字段必须采用 `DateTime64(3, 'Asia/Shanghai')`。写入 naive date/datetime 前必须转换，防止因 UTC 偏移导致日期提早或延后。夜盘时序必须使用 `DateTime64`，绝对禁止使用 `Date` 区分。
- **防止 Look-Ahead Bias（前瞻偏差）**：回测信号计算必须显式使用 `.shift()` 或 `.lag()`，确保 $T$ 时刻的决策仅使用 $\le T-1$ 的数据。回测中必须扣除佣金和滑点，并施加资金/仓位限制。
- **向量化优先**：优先使用 NumPy/Pandas/Polars 的向量化操作，**严禁**使用 `.iterrows()`、`.itertuples()` 或循环遍历 DataFrame。对必不可少的循环，必须使用 `numba.jit(nopython=True, cache=True)` 装饰器进行加速。

---

## 4. 前端编码规范 (React 19 + TypeScript 5.9 + Vite 7)

- **严格 TS**：禁止使用 `any`。所有 API 接口类型在 `src/types/` 统一定义，并与后端的 Pydantic 规范对齐。
- **网络请求**：统一从 `src/api/` (基于 `src/api/client.ts`) 导出接口，**禁止**在页面或组件中内联 `fetch` 或 `axios`。
- **状态与异步**：使用 `@tanstack/react-query` (`useQuery`/`useMutation`) 管理所有异步数据与加载状态，**禁止**在组件内使用 `useEffect` + `useState` 进行 API 轮询。
- **表单控制**：表单组件必须使用 `react-hook-form` + `zod` 校验器进行输入拦截和数据校验。
- **UI 与图表**：优先使用 `src/components/ui/` (shadcn/ui + Radix UI) 的标准无样式基础组件。权益曲线和时序图表采用 `echarts`；常规统计分析图表采用 `recharts`。

---

## 5. Antigravity 专属开发工具与验证命令 (CLI Commands)

开发过程中使用 **`uv`** 及项目命令来保证代码质量：

```bash
# ================= 后端开发 =================

# 运行 Ruff 代码格式化
uv run ruff format src/getrich/

# 运行 Ruff 静态检查并自动修复
uv run ruff check src/getrich/ --fix

# 运行单元测试并生成覆盖率报告 (核心算法覆盖率须 >80%)
uv run pytest tests/ -v --durations=10

# 启动 FastAPI 开发服务器
uv run uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000

# ================= 前端开发 =================

# 启动 Vite 开发服务
npm run dev

# 静态类型检查与生产环境构建打包
npm run build

# 执行前端代码 Lint 检查
npm run lint
```

---

## 6. Antigravity 智能体行为规范与进度继承 (Agent Behaviors)

### 6.1 阶段化开发（Planning Mode）
非微调性质的复杂变更，必须遵循 **Planning Mode** 流程：
1. **Research（调研）**：使用读文件和搜索工具深入理解代码、依赖和影响。此时**禁止修改源码**或运行修改性命令。
2. **Implementation Plan（实施计划）**：在 `<appDataDir>/brain/<conversation-id>/implementation_plan.md` 中输出详尽计划，设置 `request_feedback = true` 请求用户确认。
3. **Execute（执行）**：用户批准后开始执行，在 `task.md` 中维护进度看板。修改代码时：
   - 优先对单个连续修改块使用 `replace_file_content`。
   - 对多个非连续修改块，**在单次调用中**通过 `multi_replace_file_content` 传递多个 chunks，**禁止并行调用同一文件的编辑工具**。
4. **Verify（验证）**：运行 Ruff/Pytest/npm run build 等命令校验，在 `walkthrough.md` 中整理修改摘要及验证日志，必要时利用 `generate_image` 工具生成 UI 效果图配合审查。

### 6.2 进度继承与记忆同步 (.agent/brain/)
为确保跨会话的上下文无缝衔接，必须维护项目目录下的进度文档：
- **会话开始**：首要任务是读取 `.agent/brain/NOTES.md` 以恢复状态与获取待办，其次阅读 `.agent/brain/TODO.md` 查看 Web API 等持久技术参考。
- **会话结束**：只要本次会话中发生了实质性的代码变更、数据库表结构调整或技术方案抉择，必须在结束 turn 前更新 `.agent/brain/NOTES.md`，将当前进度、最近变更、接下来的 P0/P1 TODO 事项及已知技术债落盘。
- **自改进记录 (Self-Improvement)**：若开发过程中出现了由于 AI 误判导致的用户纠错或测试失败，必须将错误模式、根本原因及防范策略记录于 `NOTES.md` 或本指令集中，防止在下个会话中犯同样的错误。

---

## 7. 禁止事项 (Don'ts 铁律)

- **绝对禁止**在 ClickHouse 中执行事务更新或行级频繁删除操作。
- **绝对禁止**在没有对齐时间轴（`shift`/`lag`）的情况下使用行情或因子数据，防止前瞻偏差。
- 大于 100,000 行的大规模数据集，**绝对禁止**保存为普通 CSV，必须使用高压缩率的 `Parquet` 格式（选用 `zstd` 压缩）。
- **绝对禁止**在没有 `try-except` 异常捕获隔离的情况下在主线程中启动外部 API 调用或网络请求，主进程绝不能因为单个协程/线程失败而崩溃。
- **绝对禁止**使用破坏性 Git 命令（如 `git reset --hard`）修改用户工作区中未提交的代码。
- **绝对禁止**在 Python 核心库、数据库操作或公共端点中编写无 Type Hints 的代码。
- **绝对禁止**在 response.py 架构之外编写 ad-hoc 响应包装器，必须使用全局统一的统一 ApiResponse。
