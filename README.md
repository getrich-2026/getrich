# GetRich

A 股量化平台：数据接入、回测引擎、实盘信号、面向前端的查询 API。

开发约束的唯一真源是 [`AGENTS.md`](AGENTS.md)（所有 AI harness 共用）。本文只讲怎么跑起来。

---

## 仓库结构

uv workspace，六个 Python 包 + 两个前端。**目录名 `gr-x` 与 import 名 `gr_x` 一一对应。**

| 包 | import | 职责 |
|---|---|---|
| `packages/gr-data` | `gr_data` | 配置、数据库连接、外部数据接入（raw → ingest → PG） |
| `packages/gr-db` | `gr_db` | 全部 DDL 与迁移，数据库结构的唯一真源 |
| `packages/gr-backtest` | `gr_backtest` | 回测引擎（纯库，不含 Web / 实盘 / 调度） |
| `packages/gr-signal` | `gr_signal` | 实盘信号生产与交易执行 |
| `packages/gr-api` | `gr_api` | FastAPI 应用 + 回测作业队列 + Celery worker |
| `packages/gr-factor` | `gr_factor` | 期权定价与因子分析 |

依赖方向单向：`gr-data ← gr-db`，`gr-data ← gr-backtest ← gr-signal ← gr-api`。
六个包都能单独安装、单独 import。

前端：`apps/web`（主前端）、`apps/backtest-web`（回测前端，暂停维护）。

---

## 五分钟跑通

数据库是**单独部署**的基础设施，不随应用构建。先有一个可连的 PostgreSQL
（推荐 TimescaleDB 镜像），再按下面走。

```bash
# 1. 依赖
uv sync --all-packages

# 2. 配置：填数据库连接与数据源凭证
cp .env.example .env

# 3. 建库：12 个业务 schema、92 张表
uv run gr-db migrate --target all

# 4. 跑一个回测
uv run python - <<'PY'
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import psycopg
from gr_backtest import Backtest, PgBarLoader, compute_metrics
from gr_backtest.report import TearSheet
from gr_backtest.strategies.ma_cross import MACross
from gr_data.config import settings

TZ = ZoneInfo("Asia/Shanghai")
cfg = settings.postgres
conn = psycopg.connect(
    f"host={cfg.host} port={cfg.port} dbname={cfg.database} "
    f"user={cfg.user} password={cfg.password}"
)

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

# 出 HTML 报告
open("tearsheet.html", "w").write(TearSheet(result=result, metrics=metrics).to_html())
PY
```

回测结果入库用 `gr_backtest.persistence.PgBacktestResultStore.save_result()`，
写进 `backtest` schema。

### 起服务

```bash
# 后端 API
uv run uvicorn gr_api.main:app --reload --port 8000

# 前端
cd apps/web && cp .env.example .env.local && npm install && npm run dev
```

### 灌数据

行情数据靠 `gr-data` 从供应商抓取，见 [`packages/gr-data/README.md`](packages/gr-data/README.md)。
Tushare 在 PyPI 上开箱可用，只需 `TUSHARE_TOKEN`；银河／米筐／华泰的 SDK 需手动安装。

```bash
uv run gr-data raw tushare --mode update
uv run gr-data ingest tushare
```

---

## 常用命令

```bash
uv run pytest -v                              # 全量测试
uv run ruff check packages/ scripts/          # 静态检查
uv run ruff format --check packages/ scripts/
uv run python scripts/lint_migrations.py      # DDL 安全模式检查
uv lock --check && uv sync --frozen --all-packages
```

完整命令表见 `AGENTS.md` §6。

### 数据字典

```bash
# 从活库生成 HTML / JSON；--target 可用 pg、ch、all
uv run gr-db docs --target pg --out /tmp/data-dictionary.html --fail-on-drift
uv run gr-db docs --target ch --format json --out - --fail-on-drift

# CI 中检查新增建表或新增字段是否有 COMMENT ON
uv run python scripts/lint_migrations.py --db pg --comments --base-ref origin/dev
```

数据字典只展示 `gr-db` 管理的 12 个业务 schema；`ch` 模式不依赖 PostgreSQL。开发环境的
匿名快照地址为 `http://45.142.166.254:3000/data-dictionary.html`，后续将迁入登录态页面。

---

## 文档去向

| 内容 | 位置 |
|---|---|
| 开发约束、数据库职责、编码规范 | [`AGENTS.md`](AGENTS.md) |
| 数据接入层怎么跑、排障 | [`packages/gr-data/README.md`](packages/gr-data/README.md) |
| 数据库结构与数据字典命令 | 本 README「数据字典」 |
| 基础设施部署模板 | [`deploy/README.md`](deploy/README.md) |
| 当前进度、未决 TODO、已知失败 | `.agent/brain/NOTES.md` |
| 技术决策与踩坑记录 | `.agent/brain/DECISIONS.md` |
| 设计文档、厂商接口资料 | 独立仓库 `getrich-design` |
