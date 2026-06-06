# 快速开始

欢迎使用 GetRich 量化投研与信号平台。本节帮助你在 5 分钟内完成：

1. 安装 Python 依赖与外部服务
2. 运行一个最小的回测
3. 在浏览器中查看结果

---

## 5 分钟路线图

<div class="grid cards" markdown>

-   :material-download: **步骤 1：安装**

    ---

    安装 Python 3.10+、PostgreSQL、ClickHouse、Redis

    [:octicons-arrow-right-24: 安装指南](installation.md)

-   :material-code-braces: **步骤 2：第一个回测**

    ---

    复制粘贴 5 行代码，跑通你的第一个 backtest

    [:octicons-arrow-right-24: 第一个回测](first-backtest.md)

-   :material-book-open-page-variant: **步骤 3：深入引擎**

    ---

    理解 Strategy、Portfolio、WeightAllocator 的组合

    [:octicons-arrow-right-24: 核心概念](../engine/concepts.md)

</div>

---

## 系统要求

| 组件 | 最低版本 | 推荐 | 备注 |
|---|---|---|---|
| Python | 3.10 | 3.12 | CI 在 3.10 / 3.11 / 3.12 / 3.13 矩阵验证 |
| Node.js | 20 LTS | 22 LTS | 仅前端需要；Vite 8 floor |
| PostgreSQL | 14 | 16 | 业务与事务主库；`frontend` schema 隔离 |
| ClickHouse | 23 | 24.3 | 时序行情与因子；`md_*` 表前缀 |
| Redis | 6 | 7 | Celery broker + result backend；缓存层 |
| DuckDB | 0.9 | latest | 临时分析；可 `:memory:` |

> **如果你只想跑单元测试（不需要 PG/CH/Redis）**：使用 `uv sync --extra dev` 安装依赖后，`uv run pytest tests/getrich_backtest/` 可直接运行。少数集成测试（`test_persistence.py`）会跳过 live DB。

---

## 必备知识

在开始前，建议你熟悉：

- **Python 类型注解**（PEP 604、Protocol、dataclass）
- **Polars DataFrame**（与 Pandas 类似但更快、更严格）
- **Polars 长表 schema**（`dt, symbol, open, high, low, close, volume`）
- **PostgreSQL 基础**（schema、索引、COPY 协议）
- **时区感知 datetime**（`Asia/Shanghai`，UTC+8）

> **可选但强烈推荐**：阅读 [CLAUDE.md §2 数据库职责划分](https://github.com/getrich/getrich/blob/main/CLAUDE.md) 和 [§3 时序规范](https://github.com/getrich/getrich/blob/main/CLAUDE.md)，这是项目最严格的"铁律"。

---

## 完整学习路径

| 阶段 | 时长 | 内容 | 文档 |
|---|---|---|---|
| **入门** | 30 min | 跑通第一个回测 + 理解 BarLoader | [引擎 5 分钟上手](../engine/getting-started.md) |
| **基础** | 2 hour | 核心概念 + 内置策略 | [核心概念](../engine/concepts.md) · [策略开发](../engine/strategies.md) |
| **进阶** | 4 hour | Portfolio + 6 种 WeightAllocator | [组合与权重](../engine/portfolio-allocation.md) |
| **高级** | 1 day | 多频率 + 参数优化 + 归因 | [多频率](../engine/multi-frequency.md) · [参数优化](../engine/parameter-optimization.md) · [分析与报告](../engine/analysis-reporting.md) |
| **实盘** | 1 day | LiveSignal + RiskMonitor | [实盘信号](../engine/live-signals.md) |
| **贡献** | 持续 | 编码规范 + 测试 + CI | [开发指南](../development/index.md) |

---

## 获取帮助

- **搜索文档**：右上角搜索框（支持中文分词）
- **反馈问题**：在 GitHub 提交 issue
- **AI 助手辅助**：项目提供 [CLAUDE.md](https://github.com/getrich/getrich/blob/main/CLAUDE.md) / [AGENTS.md](https://github.com/getrich/getrich/blob/main/AGENTS.md) / [GEMINI.md](https://github.com/getrich/getrich/blob/main/GEMINI.md) 三套 AI 指令，可直接与 Claude/Codex/Gemini 协作

---

下一步：[安装](installation.md) → [第一个回测](first-backtest.md)
