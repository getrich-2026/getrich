# GetRich — AI 开发指令集

本文件是 GetRich 项目约束的**唯一真源**，供 Claude Code、Codex、DeepSeek 等所有 harness 共用。`CLAUDE.md` 只是指向本文件的入口，不重复内容。

各 harness 自己的全局约定（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md` 等）定义通用行为与 agent 调度；本文件只写 GetRich 特有的约束，更具体的指令优先。

---

## 1. 仓库结构与运行环境

```
apps/web              主前端（Vite 7 + React 19 + TypeScript 5.9）
apps/backtest-web     回测前端
packages/gr-{agent,api,backtest,data,factor,signal}
                      uv workspace 成员，各自有 pyproject.toml / src / tests
deploy/               数据库基础设施部署模板，不在仓库内实例化
scripts/              仅存 lint_migrations.py
archive/              历史脚手架，删除前必须得到明确确认
.agent/brain/         跨会话开发进度（见第 7 节）
```

- Python 3.10+，首行 `from __future__ import annotations`；依赖统一用 `uv` 管理，不用 pip。
- 数据处理优先 Polars / DuckDB；pandas 只留给小数据和兼容场景。
- 后端服务用 FastAPI。
- **数据库单独部署，不随应用一起构建**：`deploy/docker-compose.yml` + `deploy/config/` 只定义 PostgreSQL、ClickHouse、Redis 三个基础设施服务，是可复现的部署模板；GetRich 仓库内不创建 Docker 实例。真实 `.env`、数据卷、日志和运维脚本全部放在仓库外的部署目录，不进 git。仓库内不维护应用的 Dockerfile 或 systemd unit。
- 不要在 GetRich 仓库内执行 `docker compose up`、`down` 或 `restart`。改动 `deploy/` 后，需将其中的文件同步到仓库外的部署目录根，不保留外层 `deploy/`，再从部署目录校验和重启容器。

## 2. 数据库职责划分（铁律）

| 数据库 | 存储实体 | 约束 |
|---|---|---|
| **PostgreSQL**（`getrich` 库） | 策略元数据、实盘信号、用户订阅、账户资产快照、支付账单、交易订单、系统配置 | 业务与事务的唯一主库。需要事务安全、主外键约束或 `ON CONFLICT` 原子 UPSERT 的数据，必须且仅能写这里 |
| **ClickHouse** | 分钟线／日线 OHLCV、Tick 逐笔、因子时序输出 | 只做大批量写入和按 symbol／时间范围的分析查询。持久化表必须用 `MergeTree` 系列引擎，强制配置 `PARTITION BY`、`ORDER BY`、`TTL` |
| **DuckDB** | ad-hoc 一次性分析、回测中间数据、本地 Parquet 报表 | 只作内存临时计算层，不做任何业务的终态存储 |
| **Redis** | 消息分发、tick 缓存、跨进程状态、分布式锁、限流 | 永不作为最终存储，关键数据必须周期性落 PG／CH；历史数据和关系数据都不进 Redis |

**绝对禁止**在 ClickHouse 中执行事务更新或行级频繁删除。

## 3. 量化与时序规范

### 3.1 时区对齐

- 平台主时区 `Asia/Shanghai (UTC+8)`。
- PostgreSQL 在 `pool.py` 初始化时已强制 `SET timezone='Asia/Shanghai'`，所有写入的 timestamp 必须显式处理时区。
- ClickHouse 行情表及因子表的时间字段必须用 `DateTime64(3, 'Asia/Shanghai')`。写入 `Date`／`Date32` 前，必须在 Python 端转成 aware datetime 再用 `.astimezone(tz).date()` 提取，防止 UTC 偏移导致日期错一天。
- 含跨日夜盘（21:00 至次日 02:30）的时序数据必须统一用 `DateTime64`，**绝对禁止**用 `Date` 区分。
- datetime 全部 timezone-aware 或全部 naive，不混用。

### 3.2 列名与精度

- OHLCV 字段名固定为 `open, high, low, close, volume, vwap, oi, symbol, dt`，禁止任何缩写或变体。
- 财务金额、PnL、可用资金一律用 `decimal.Decimal`，禁止 `float`，避免累积舍入误差。
- 收益率必须显式区分单利 `simple_return` 与对数 `log_return`，并在函数签名和 docstring 中注明。

### 3.3 回测正确性

- **禁止 look-ahead bias**：$T$ 时刻的决策只能用 $\le T-1$ 可得的数据。用 `shift`／`lag` 时说明滞后期，区分信号生成时间戳与执行时间戳。
- 明确复权方式，区分信号计算用价与成交执行用价。
- 必须计入滑点、手续费、资金约束、保证金与爆仓风险，不假设无限资金零成本。
- 上线顺序：历史回测 → 模拟盘 → 小资金实盘，不跳级。
- 因子公式、复权规则、数据字段、行情商 API 一律不臆造，不确定就要文档。

## 4. 后端编码规范

- **不引入 heavy ORM**：用 `psycopg3` 的 `AsyncConnectionPool` 手写原生 SQL。
- 大批量写入优先 COPY 协议或 multi-values UPSERT（`ON CONFLICT DO UPDATE`）。
- **绝对禁止**在没有 `try-except` 隔离的情况下在主线程中发起外部 API 调用或网络请求。

## 5. 前端编码规范（React 19 + TypeScript 5.9）

- **禁止 `any`**：严格推导类型。对接无类型外部遗留包时必须附详细说明。API 类型放 `src/types/`，与后端 Pydantic schema 对齐。
- **数据请求**：接口函数模块化写在 `src/api/`（走 `src/api/client.ts`），组件一律通过 `@tanstack/react-query` 的 `useQuery`／`useMutation` 管理异步数据与加载态。**禁止**组件内 `useEffect` + `useState` 手写轮询，禁止 inline `fetch`／`axios`。
- **表单校验**：`react-hook-form` + `zod`。
- **UI 与图表**：优先用 `src/components/ui/`（shadcn/ui + Radix UI）+ Tailwind CSS 3，由 CLI 统一管理，不手改 UI 源码。时序／权益曲线用 `echarts`，其余常规图表用 `recharts`。
- **XSS 防御**：渲染用户或作者提供的 HTML（如 `strategy.detail_html`）必须先过 DOMPurify 或等效方案再传给 `dangerouslySetInnerHTML`。后端同时用 Pydantic 长度限制和 bleach 归一化。

## 6. 常用命令

```bash
# 应用配置：只填写已有数据库服务的连接信息
cp .env.example .env

# 基础设施模板：只做静态校验，不在仓库内启动容器
docker compose --env-file deploy/.env.example -f deploy/docker-compose.yml config --quiet

# 后端：启动 FastAPI 开发服务器
# 注意必须显式 --env-file，原因见 .agent/brain/DECISIONS.md
uv run --env-file .env uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000

# 全量测试（testpaths = packages/gr-backtest/tests + packages/gr-factor/tests）
uv run pytest -v

# 单包测试
uv run pytest packages/gr-backtest/tests -v

# 静态检查与格式化
uv run ruff check packages/ scripts/
uv run ruff format --check packages/ scripts/
uv run basedpyright packages/gr-backtest/src   # 若已安装

# 依赖
uv lock --check
uv sync --frozen --all-packages
```

```bash
# 前端
cd apps/web
npm run dev      # Vite 开发服务
npm run build    # 类型检查 + 生产打包
npm run lint     # ESLint
```

## 7. 开发进度文档（`.agent/brain/`）

两个文件，职责不同，**不要混写**：

| 文件 | 性质 | 写什么 |
|---|---|---|
| `NOTES.md` | **状态快照**，可整体覆写 | 当前进行中的工作、未决 P0／P1、已知失败基线。历史沿革交给 `git log`，不在这里追加流水账 |
| `DECISIONS.md` | **只增不改**的长期记录 | 技术决策及其理由、踩坑与防范策略、不可从代码推导的隐式约束 |

- **会话开始**：先读 `NOTES.md` 恢复状态，再读 `DECISIONS.md` 了解历史约束与坑。
- **会话结束**：只要发生了实质性代码变更、表结构调整或技术方案抉择，必须在结束 turn 前更新 `NOTES.md`。
- **自改进**：若出现 AI 误判导致的用户纠错或测试失败，把错误模式、根本原因、防范策略追加到 `DECISIONS.md`。
- 写入前先核对：已经过期的条目要删掉，不要让互相矛盾的两条同时存在。

## 8. 改动边界与禁止事项

- 不静默变更架构、依赖、凭证、数据路径、公开 API、表结构 —— 这几类必须先说。
- **绝对禁止**输出或提交真实凭证、token、私钥，以及本地 `.env` 里的真实值。
- **绝对禁止**用 `git reset --hard` 等 destructive 命令修改未提交的工作区代码。
- **绝对禁止**在 `apps/web/main.py::create_app()` 中移除 `SecurityHeadersMiddleware` —— 这是协议级 XSS 兜底（`Content-Security-Policy` / `X-Frame-Options` / `nosniff` / `Referrer-Policy`），也是 OWASP 推荐做法。新增路由或中间件时，测试必须用 `TestClient` 验证响应仍带这 4 个头。
- **绝对禁止**未经 DOMPurify 或等效清洗就用 `dangerouslySetInnerHTML` 渲染用户内容。
- 超过 100,000 行的数据集**绝对禁止**存普通 CSV，必须用 Parquet（`zstd` 压缩）。

## 9. 语言约定

- 用用户使用的语言回复。
- 注释、commit message、文档正文：中文。
- 标识符、函数名、类名、日志消息、配置键、表名、字段名、文件名：英文（为了可 grep）。
