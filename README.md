# GetRich 📈

> 现代化、全链路 A 股量化投研与实盘信号平台。  
> 数据接入 · 向量化回测 · 实盘信号 · 持仓诊断 · React 19 现代化界面

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TimescaleDB](https://img.shields.io/badge/TimescaleDB-PostgreSQL-FDB515?logo=postgresql&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-green.svg)

项目主页：<https://getrich-2026.github.io/getrich/>

读者：首次运行项目的开发者。功能操作说明和待办按下方导航查阅。

开发约束的唯一真源是 [`AGENTS.md`](AGENTS.md)（所有 AI harness 共用）。本文只讲怎么跑起来。

---

## 仓库结构

uv workspace，七个有源码的 Python 包、一个占位包与两个前端。**目录名 `gr-x` 与 import 名 `gr_x` 一一对应。**

| 包 | import | 职责 |
|---|---|---|
| `packages/gr-data` | `gr_data` | 数据配置、数据库连接、外部数据接入（raw → ingest → PG） |
| `packages/gr-db` | `gr_db` | 全部 DDL 与迁移，数据库结构的唯一真源 |
| `packages/gr-backtest` | `gr_backtest` | 回测引擎（纯库，不含 Web / 实盘 / 调度） |
| `packages/gr-signal` | `gr_signal` | 实盘信号生产与交易执行 |
| `packages/gr-api` | `gr_api` | FastAPI 应用 + 回测作业队列 + Celery worker |
| `packages/gr-factor` | `gr_factor` | 期权定价与因子分析 |
| `packages/gr-tools` | `gr_tools` | 环境加载、配置、日志、文件系统、表格读取与可读格式化，叶子包 |
| `packages/gr-agent` | — | 占位包，尚无源码 |

依赖方向单向（箭头指向被依赖方），包边界由测试约束：

```
gr-tools（叶子，不依赖任何一方包）
   ↑
gr-data  ←──  gr-db
   ↑
   └──  gr-backtest  ←──  gr-signal  ←──  gr-api
gr-factor（独立）
```

前端：`apps/web`（主前端）、`apps/backtest-web`（回测前端，暂停维护）。

---

## 五分钟跑通

数据库是**单独部署**的基础设施，不随应用构建。先有一个可连的 PostgreSQL
（推荐 TimescaleDB 镜像），再按下面走。默认 `GETRICH_WORKER_BACKEND=inproc`，此路径不需要 Redis 或 ClickHouse。

```bash
# 1. 依赖
uv sync --frozen --all-packages

# 2. 配置：填数据库连接与数据源凭证
cp .env.example .env
# 配置只在应用／CLI 入口显式加载；不会自动生成用户目录 .env

# 3. 建 PostgreSQL 表（若也配置了 ClickHouse，再执行 --target ch）
uv run gr-db migrate --target pg

# 4. 灌数据：示例回测需要标的与该区间日线（只需在 .env 填 TUSHARE_TOKEN）
uv run gr-data raw tushare --mode update
uv run gr-data ingest tushare

# 5. 跑一个回测
uv run python - <<'PY'
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import psycopg
from gr_backtest import Backtest, PgBarLoader, compute_metrics
from gr_backtest.report import TearSheet
from gr_backtest.strategies.ma_cross import MACross
from gr_data.config import load_postgres
from gr_tools.config import load_environment

TZ = ZoneInfo("Asia/Shanghai")
cfg = load_postgres(load_environment())

# 关键字参数传连接信息，密码含空格或特殊字符也能正确连接
with psycopg.connect(
    host=cfg.host, port=cfg.port, dbname=cfg.database,
    user=cfg.user, password=cfg.password,
) as conn:
    bt = Backtest(
        strategy=MACross(fast=5, slow=20),
        bar_loader=PgBarLoader(conn=conn),
        symbols=["000001.SZ"],
        start=datetime(2024, 1, 1, tzinfo=TZ),
        end=datetime(2024, 10, 1, tzinfo=TZ),
        initial_cash=Decimal("1000000"),
        freq="1d",
        run_id="demo",
    )
    result = bt.run()

metrics = compute_metrics(result)
print("总收益:", metrics.total_return, " 最大回撤:", metrics.max_drawdown)

# 出 HTML 报告（含中文，显式 UTF-8）
with open("tearsheet.html", "w", encoding="utf-8") as f:
    f.write(TearSheet(result=result, metrics=metrics).to_html())
PY
```

数据抓取的范围、月份筛选与其他供应商见 [`packages/gr-data/README.md`](packages/gr-data/README.md)。
`tushare` 与米筐 `rqdatac` 已列入主依赖；银河 AmazingData、华泰 INSIGHT（已停用，代码保留）的 SDK 需按需手动安装。

回测结果入库用 `gr_backtest.persistence.PgBacktestResultStore.save_result()`，
写进 `backtest` schema。

### 起服务

```bash
# 后端 API
uv run uvicorn gr_api.main:app --reload --port 8001

# 前端
cd apps/web && cp .env.example .env.local && npm ci && npm run dev
```

后端示例端口 8001 与 `apps/web/vite.config.ts` 的代理目标一致；改变端口时同步代理。
前端需要 Node `^20.19.0 || >=22.12.0`（Vite 8 的下限），CI 与本地都用 24。

---

## 常用命令

```bash
uv run pytest -v                              # 全量测试
uv run ruff check packages/ scripts/          # 静态检查
uv run ruff format --check packages/ scripts/
uv run basedpyright                           # 类型检查（CI 只拦新增错误）
uv run python scripts/lint_migrations.py      # DDL 安全模式检查
uv lock --check && uv sync --frozen --all-packages
```

完整命令表见 `AGENTS.md` §6。CI 默认只启动 PostgreSQL；手动运行 CI 时可勾选 `extra_services` 启用 ClickHouse／Redis。离线 CH 检查始终保留。

## 文档导航

完整分类、读者与维护规则见 [文档目录](docs/README.md)。

| 我想做什么 | 入口 |
|---|---|
| 让 Agent 开始工作 | [项目规则](AGENTS.md) → [当前状态](.agents/brain/NOTES.md) |
| 启动主前端 | [前端开发指南](docs/guides/frontend-dev.md) |
| 导入每日选股池 | [选股导入指南](docs/guides/pick-import.md) |
| 接入持仓诊断页面 | [诊断 API 指南](docs/guides/diagnosis-api.md) |
| 查数据库结构／生成字典 | [数据字典指南](docs/guides/data-dictionary.md) |
| 抓取与入库数据 | [gr-data 手册](packages/gr-data/README.md) |
| 配置数据库基础设施 | [部署模板](deploy/README.md) |
| 决定下一步做什么 | [待决问题](docs/plans/backlog.md) |
| 理解实现为何这样选 | [决策记录](.agents/brain/DECISIONS.md) |
