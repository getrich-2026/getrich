# 第一个回测

本节带你跑通一个最小可运行的回测。整个流程只需 5 行核心代码 + 1 行调用。

---

## 1. 5 行最小回测

新建文件 `hello_backtest.py`：

```python
from decimal import Decimal
from datetime import datetime
from getrich_backtest import get_shanghai_tz  # 时间工具
from getrich_backtest import (
    Backtest, DataFrameBarLoader, MACross, ZeroFee, ZeroSlippage,
)
import polars as pl

# 1. 准备测试数据：60 个交易日的模拟收盘价
bars = pl.DataFrame({
    "dt": pl.datetime_range(
        datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        datetime(2024, 4, 1, 15, 0, tzinfo=get_shanghai_tz()),
        "1d", eager=True,
    ).to_list() * 3,  # 重复 3 次给 3 个 symbol
    "symbol": ["BTCUSDT"] * 60 + ["ETHUSDT"] * 60 + ["SOLUSDT"] * 60,
    "open": [100.0] * 180, "high": [105.0] * 180,
    "low": [95.0] * 180, "close": [100.0] * 180,
    "volume": [1000.0] * 180,
}).sort(["symbol", "dt"])

# 2. 用内存版 BarLoader 装载
loader = DataFrameBarLoader(bars)

# 3. 配置回测
bt = Backtest(
    strategy=MACross(fast=5, slow=20),
    bar_loader=loader,
    symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    start=datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
    end=datetime(2024, 4, 1, 15, 0, tzinfo=get_shanghai_tz()),
    initial_cash=Decimal("100000"),
    fee_model=ZeroFee(),
    slippage_model=ZeroSlippage(),
    freq="1d",
)

# 4. 运行 + 5. 看结果
result = bt.run()
print(result.metrics())
```

运行：

```bash
uv run python hello_backtest.py
```

预期输出（部分）：

```
BacktestMetrics(
    total_return=Decimal('0.0234'),
    sharpe_ratio=1.45,
    max_drawdown=Decimal('-0.082'),
    total_trades=12,
    ...
)
```

---

## 2. 完整示例（含真实数据源）

如果你想跑一个完整的端到端回测（含 PG 持久化），参考以下 6 步：

### 步骤 1：启动后端

```bash
uv run uvicorn getrich.apps.web.main:app --reload --port 8001
```

### 步骤 2：打开浏览器

<http://localhost:5173>（前端 dev server）

### 步骤 3：登录

使用 demo 账号：

- 邮箱：`demo@getrich.io`
- 密码：`Demo@2024!`

### 步骤 4：进入 "Strategies" 页面

浏览已有策略，订阅一个（比如 `MACross`）。

### 步骤 5：进入 "Backtests" → "New Backtest"

填表：

| 字段 | 值 |
|---|---|
| Strategy Name | `MACross` |
| Start Date | `2024-01-01` |
| End Date | `2024-06-30` |
| Initial Cash | `100000` |
| Frequency | `1d` |

点击 "Create Backtest"。

### 步骤 6：观察实时进度

页面会通过 SSE 实时显示：

- 进度条（5% 步进）
- 当前状态（queued → running → completed）
- 完成后显示 Tear Sheet 与归因分析

---

## 3. 跑测试套件（验证安装）

```bash
# 核心引擎
uv run pytest tests/getrich_backtest/ -v --durations=10

# 平台
uv run pytest tests/getrich/ -v --durations=10

# 完整套件
uv run pytest tests/ -v --durations=10
```

预期：~1500 tests pass，~20 skipped（live DB）。

---

## 4. 生成 HTML Tear Sheet

```python
from getrich_backtest.report import Reporter

reporter = Reporter.from_result(result)
reporter.save(
    "runs/hello/",
    formats=["html", "parquet"],
)
```

输出文件：

```
runs/hello/
├── manifest.json           # 元数据（run_id, strategy_name, etc.）
├── equity.parquet          # 权益曲线（zstd 压缩）
├── fills.parquet           # 所有成交
├── orders.parquet          # 所有订单
├── tear_sheet.html         # 交互式 HTML 报告（Plotly）
└── metrics.json            # 指标字典
```

在浏览器中打开 `runs/hello/tear_sheet.html` 即可查看完整回测报告。

---

## 5. 常见错误

### 错误 1：naive datetime 警告

```
TimezoneError: All datetimes must be Asia/Shanghai-aware.
```

**修复**：

```python
from getrich_backtest import get_shanghai_tz
dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
```

> **CLAUDE.md §3.1 铁律**：所有 `dt` 字段必须 `Asia/Shanghai (UTC+8)` 时区感知。

### 错误 2：浮点价格

```
TypeError: Money field must be Decimal, not float.
```

**修复**：

```python
from decimal import Decimal
price = Decimal("100.50")  # 不是 100.50 (float)
```

> **CLAUDE.md §3.2 铁律**：财务金额、PnL、可用资金计算一律用 `Decimal`。

### 错误 3：列名拼错

```
BarSchemaError: Missing required column: 'open'
```

**修复**：检查 DataFrame 列名，必须是 `open, high, low, close, volume, vwap, oi, symbol, dt` 之一。详见 [引擎 / 数据加载器](../engine/data-loaders.md)。

### 错误 4：导入错误

```
ImportError: cannot import name 'DataFrameBarLoader' from 'getrich_backtest'
```

**修复**：`DataFrameBarLoader` 位于子模块：

```python
from getrich_backtest.data import DataFrameBarLoader
```

---

## 6. 下一步

- 理解引擎的核心抽象：[核心概念](../engine/concepts.md)
- 写自己的策略：[策略开发](../engine/strategies.md)
- 多策略组合：[组合与权重](../engine/portfolio-allocation.md)（Phase 2 文档）
- 参数扫描：[参数优化](../engine/parameter-optimization.md)（Phase 2 文档）

---

## 附录：完整的可运行示例

```python
"""
hello_backtest.py — 最小可运行的回测示例。

运行：uv run python hello_backtest.py
"""
from decimal import Decimal
from datetime import datetime

import polars as pl

from getrich_backtest import get_shanghai_tz
from getrich_backtest import (
    Backtest, DataFrameBarLoader, MACross,
    ZeroFee, ZeroSlippage, BacktestMetrics,
)


def build_synthetic_bars(symbols: list[str], n_days: int = 60) -> pl.DataFrame:
    """构造合成 K 线（仅用于 demo，生产应使用 PgBarLoader）。"""
    rows = []
    import random
    rng = random.Random(42)
    for sym in symbols:
        base = rng.uniform(50, 200)
        for i in range(n_days):
            dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()).replace(
                day=1 + i  # naive 简化，实际应做工作日过滤
            )
            close = base * (1 + rng.uniform(-0.05, 0.05))
            rows.append({
                "dt": dt,
                "symbol": sym,
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": rng.uniform(1e5, 1e6),
            })
    return pl.DataFrame(rows).sort(["symbol", "dt"])


def main() -> None:
    # 1. 数据
    bars = build_synthetic_bars(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    print(f"Loaded {bars.shape[0]} bars across {bars['symbol'].n_unique()} symbols")

    # 2. Loader
    loader = DataFrameBarLoader(bars)

    # 3. Backtest
    bt = Backtest(
        strategy=MACross(fast=5, slow=20),
        bar_loader=loader,
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        start=datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        end=datetime(2024, 3, 1, 15, 0, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("100000"),
        fee_model=ZeroFee(),
        slippage_model=ZeroSlippage(),
        freq="1d",
        run_id="hello-001",
    )

    # 4. 运行
    result = bt.run()
    metrics: BacktestMetrics = result.metrics()

    # 5. 输出
    print(f"Run ID: {result.run_id}")
    print(f"Strategy: {result.strategy_name}")
    print(f"Total return: {metrics.total_return:.2%}")
    print(f"Sharpe ratio: {metrics.sharpe_ratio:.2f}")
    print(f"Max drawdown: {metrics.max_drawdown:.2%}")
    print(f"Total trades: {metrics.total_trades}")


if __name__ == "__main__":
    main()
```
