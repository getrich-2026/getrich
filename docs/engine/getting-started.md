# 5 分钟上手

本节带你从 0 到 1 跑通一个最小可运行的回测，并生成 HTML Tear Sheet。

---

## 1. 最小的 5 行回测

假设你已经有了时序数据（Polars DataFrame），完整流程是：

```python
from decimal import Decimal
from datetime import datetime
from getrich_backtest import (
    Backtest, DataFrameBarLoader, MACross, ZeroFee, ZeroSlippage,
    get_shanghai_tz,
)
import polars as pl

# 1. 构造 K 线
bars = pl.DataFrame({
    "dt": pl.datetime_range(
        datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        datetime(2024, 4, 1, 15, 0, tzinfo=get_shanghai_tz()),
        "1d", eager=True,
    ),
    "symbol": ["BTCUSDT"] * 91,
    "open": [100.0] * 91, "high": [105.0] * 91,
    "low": [95.0] * 91, "close": [100.0] * 91,
    "volume": [1000.0] * 91,
}).sort(["dt"])

# 2. 用内存 BarLoader
loader = DataFrameBarLoader(bars)

# 3. 配置并运行
bt = Backtest(
    strategy=MACross(fast=5, slow=20),
    bar_loader=loader,
    symbols=["BTCUSDT"],
    start=datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
    end=datetime(2024, 4, 1, 15, 0, tzinfo=get_shanghai_tz()),
    initial_cash=Decimal("100000"),
    fee_model=ZeroFee(),
    slippage_model=ZeroSlippage(),
    freq="1d",
    run_id="hello-001",
)
result = bt.run()

# 4. 看指标
print(result.metrics())
```

预期输出（部分）：

```
BacktestMetrics(
    total_return=Decimal('0.0'),
    sharpe_ratio=0.0,
    max_drawdown=Decimal('0.0'),
    total_trades=0,
    ...
)
```

> **数据是平的（无波动）所以指标都是 0**。真实数据请用 `PgBarLoader` 从 PostgreSQL 加载（见 [数据加载器](data-loaders.md)）。

---

## 2. 跑测试套件（验证安装）

```bash
# 核心引擎单元测试（不需要 live DB）
uv run pytest tests/getrich_backtest/ -v --durations=10
```

预期：~800 tests pass，~10 skipped（live DB）。

---

## 3. 生成 HTML Tear Sheet

```python
from getrich_backtest import Reporter

reporter = Reporter.from_result(result)
reporter.save(
    "runs/hello/",
    formats=["html", "parquet"],
)
```

输出目录：

```
runs/hello/
├── manifest.json           # 元数据（run_id, strategy_name, ...）
├── equity.parquet          # 权益曲线（zstd 压缩）
├── fills.parquet           # 所有成交
├── orders.parquet          # 所有订单
├── tear_sheet.html         # 交互式 HTML 报告（Plotly）
└── metrics.json            # 指标字典
```

在浏览器中打开 `runs/hello/tear_sheet.html` 即可查看完整回测报告。

---

## 4. 端到端示例（PG + Worker）

如果你想跑一个完整的端到端回测（涉及 PG 持久化、Worker 池、SSE 实时进度）：

```bash
# 1. 启动后端
uv run uvicorn getrich.apps.web.main:app --reload --port 8001

# 2. 启动前端
cd frontend
npm run dev
# 访问 http://localhost:5173

# 3. 登录 demo 账号（demo@getrich.io / Demo@2024!）

# 4. 进入 "Backtests" → "New Backtest" → 填表 → 提交

# 5. 浏览器实时显示进度（5% 步进）
```

---

## 5. 常见错误

### 5.1 naive datetime 警告

```
TimezoneError: All datetimes must be Asia/Shanghai-aware.
```

**修复**：

```python
from getrich_backtest import get_shanghai_tz
dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
```

> **CLAUDE.md §3.1 铁律**：所有 `dt` 字段必须 `Asia/Shanghai (UTC+8)` 时区感知。

### 5.2 浮点价格

```
TypeError: Money field must be Decimal, not float.
```

**修复**：

```python
from decimal import Decimal
price = Decimal("100.50")  # 不是 100.50 (float)
```

> **CLAUDE.md §3.2 铁律**：财务金额、PnL、可用资金计算一律用 `Decimal`。

### 5.3 列名拼错

```
BarSchemaError: Missing required column: 'open'
```

**修复**：检查 DataFrame 列名，必须包含 `open, high, low, close, volume, symbol, dt`。详见 [数据加载器](data-loaders.md)。

### 5.4 导入错误

```
ImportError: cannot import name 'DataFrameBarLoader' from 'getrich_backtest'
```

**修复**：`DataFrameBarLoader` 位于子模块：

```python
from getrich_backtest.data import DataFrameBarLoader
```

### 5.5 引擎没找到 `Strategy` 钩子

```
TypeError: Can't instantiate abstract class MACross with abstract method on_bar
```

**修复**：继承 `Strategy` 必须实现 `on_bar(ctx) -> Iterable[OrderIntent]`。详见 [策略开发](strategies.md)。

---

## 6. 下一步

- 理解核心抽象：[核心概念](concepts.md)
- 写自己的策略：[策略开发](strategies.md)
- 多策略组合：[组合与权重](portfolio-allocation.md)
- 参数扫描：[参数优化](parameter-optimization.md)
- 实盘信号：[实盘信号](live-signals.md)
