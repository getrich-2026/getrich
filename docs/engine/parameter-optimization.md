# 参数扫描与优化

> **本节讲解 sweep（网格搜索）和 walk-forward（滚动/锚定窗口）**——量化研究的两个最常用工具。两者都是给一组参数跑多遍 backtest，挑出泛化最好的组合。

---

## 1. 全景：两个抽象

| 工具 | 适用 | 关键参数 |
|---|---|---|
| `GridSearch` + `SweepRunner` | 完整 backtest × N 个参数组合 | `ParamSpace` + `select_metric` |
| `WalkForward` | 滚动/锚定时间窗的样本外测试 | `WalkForwardRunSpec` (window size, step, anchored) |

**共同点**：

- 都是**确定性**的（给定相同输入 + 相同 seed，结果一致）
- 都通过 `RetryableError` / `TerminalError` 控制 trial 失败时的行为
- 都支持 `on_progress` / `is_cancelled` / `request_hash` 三个钩子
- 都有 PostgreSQL 持久化（`PgSweepResultStore` / `PgWalkForwardResultStore`）

**区别**：Sweep 在**同一时间区间**上做参数变种；WalkForward 强调**时间维度的样本外验证**，更接近实战泛化能力。

---

## 2. `ParamSpace` —— 参数空间

```python
from getrich_backtest import ParamSpace, P

space = ParamSpace({
    "fast_window": P.int_range(5, 50, step=5),         # 5, 10, 15, ..., 50
    "slow_window": P.int_range(20, 200, step=20),     # 20, 40, ..., 200
    "threshold":   P.decimal_range("0.01", "0.10", step=Decimal("0.01")),
    "method":      P.categorical(["sma", "ema", "wma"]),
})
```

### 2.1 `P` 工厂

`P` 提供 3 种参数维度构造函数：

| 方法 | 用法 | 例子 |
|---|---|---|
| `P.categorical(values)` | 离散枚举 | `P.categorical(["sma", "ema"])` |
| `P.int_range(start, stop, step=1, inclusive=True)` | 整数范围 | `P.int_range(5, 50, step=5)` |
| `P.decimal_range(start, stop, step, inclusive=True)` | Decimal 范围 | `P.decimal_range("0.01", "0.10", step=Decimal("0.01"))` |

底层所有维度都展开为元组 `tuple[values]`，最终通过 `iter_configs()` 做笛卡尔积。

### 2.2 约束（`add_constraint`）

笛卡尔积可能产生不合理组合（如 `fast_window > slow_window`）。用 `add_constraint` 过滤：

```python
space = (
    ParamSpace({
        "fast_window": P.int_range(5, 50, step=5),
        "slow_window": P.int_range(20, 200, step=20),
    })
    .add_constraint(lambda p: int(p["fast_window"]) < int(p["slow_window"]))
)
```

约束在 `iter_configs()` 内部过滤，**不修改维度**，只筛选笛卡尔积的子集。

### 2.3 `iter_configs()` —— 确定性迭代

`iter_configs()` 按维度声明顺序返回 `dict[str, object]`，**每次调用结果完全相同**：

```python
for config in space.iter_configs():
    print(config)
# {'fast_window': 5, 'slow_window': 20}
# {'fast_window': 5, 'slow_window': 40}
# ...
```

---

## 3. `GridSearch` —— 笛卡尔 trial 序列

```python
from getrich_backtest import GridSearch

grid = GridSearch(space=space)
trials = list(grid.iter_trials(sweep_id="sma-2024"))
print(len(trials))  # 笛卡尔积（含 constraint 过滤后）的总 trial 数
```

`SweepTrial` 携带：

- `trial_id` —— SHA-256 指纹（基于 `sweep_id` + `params`）
- `params` —— 参数 dict
- `sweep_id` —— 扫描标识

`trial_id` 的**幂等性**：相同 `sweep_id` + 相同 `params` 产生相同 `trial_id`，所以 sweep 可以安全地断点续跑。

---

## 4. `SweepRunner` —— 串行执行

```python
from getrich_backtest import SweepRunner, SweepResult

runner = SweepRunner(
    sweep_id="sma-2024",
    search=grid,
    select_metric="sharpe_ratio",   # 用哪个指标挑赢家
    maximize=True,                   # 越大越好（Sharpe、Sortino）
    fail_fast=False,                 # 一个 trial 失败不影响其他
)

result = runner.run(
    strategy_factory=lambda params: MyStrategy(**params),
    backtest_factory=lambda strat, trial: Backtest(
        strategy=strat,
        bar_loader=DataFrameBarLoader(bars),
        # ... 其他配置
    ),
    on_progress=lambda i, total: print(f"{i}/{total}"),
    is_cancelled=lambda: check_db_for_cancel(),
)
```

### 4.1 `strategy_factory` / `backtest_factory`

**注入模式** —— runner 不关心 strategy / backtest 怎么构造，只调用工厂：

- `strategy_factory(params) -> Strategy` —— 把 params 注入 strategy 构造
- `backtest_factory(strategy, trial) -> Backtest` —— 用 strategy 构造 backtest（可以读 `trial.trial_id` 作为 run_id）

这样 runner 可以复用**任意 strategy 类型**（MA、信号、目标仓位）。

### 4.2 `on_progress(i, total)`

每完成一个 trial 调用一次。**失败回调不影响 sweep 继续**（runner 内部 `try/except` 包裹）：

```python
def on_progress(i: int, total: int) -> None:
    # 写 DB / 发 SSE / 更新 UI
    progress_pct = 100 * i / total
    db.update_sweep_progress(sweep_id, progress_pct)
```

### 4.3 `is_cancelled() -> bool`

每 trial 开头调用一次。**返回 True 立即停止 sweep**，已完成的 trial 结果保留：

```python
def is_cancelled() -> bool:
    # 读 backtest_jobs 表的 status
    return db.get_job_status(sweep_id) == "cancelled"
```

### 4.4 `select_metric` 与 `maximize`

- `select_metric="sharpe_ratio"` —— 挑 `SweepTrialResult.metrics.sharpe_ratio` 最高的
- `maximize=False` —— 用于 `max_drawdown` 这种"越小越好"的指标

```python
runner = SweepRunner(
    sweep_id="sma-2024",
    search=grid,
    select_metric="max_drawdown",
    maximize=False,  # 越小越好
)
```

### 4.5 `SweepResult`

```python
result: SweepResult = runner.run(...)
result.sweep_id           # str
result.trials             # tuple[SweepTrialResult, ...]
result.select_metric      # str
result.maximize           # bool
result.cancelled          # bool（是否被 is_cancelled 打断）
```

每个 `SweepTrialResult`：

```python
@dataclass
class SweepTrialResult:
    trial: SweepTrial
    status: str              # "completed" / "failed"
    result: BacktestResult | None
    metrics: BacktestMetrics | None
    error_message: str | None
```

挑赢家：

```python
def select_best(result: SweepResult) -> SweepTrialResult | None:
    candidates = [t for t in result.trials if t.metrics is not None]
    if not candidates:
        return None
    key = lambda t: getattr(t.metrics, result.select_metric)
    return max(candidates, key=key) if result.maximize else min(candidates, key=key)
```

### 4.6 `fail_fast`

开发期推荐 `True`（一个 trial 失败立刻抛错，方便调 bug）；生产推荐 `False`（个别 trial 失败不应该让整个 sweep 中断）。

---

## 5. `WalkForward` —— 滚动样本外验证

WalkForward 解决 sweep 的核心问题：**in-sample 过拟合**。它把整个时间区间切成多个 window，对每个 window：

1. 在 in-sample 段跑 sweep，挑出最佳参数
2. 在 out-of-sample 段用最佳参数跑 1 次
3. 报告 out-of-sample 表现

### 5.1 `WalkForwardRunSpec`

```python
from datetime import datetime
from getrich_backtest import WalkForward, WalkForwardRunSpec

spec = WalkForwardRunSpec(
    full_start=datetime(2020, 1, 1, tzinfo=get_shanghai_tz()),
    full_end=datetime(2024, 12, 31, tzinfo=get_shanghai_tz()),
    train_window_bars=252 * 2,    # in-sample 段 2 年
    test_window_bars=252,         # out-of-sample 段 1 年
    step_bars=252,                # 每次滚 1 年
    anchored=False,                # rolling（False）或 anchored（True）
)
```

### 5.2 Rolling vs Anchored

| 模式 | 含义 | 用途 |
|---|---|---|
| **Rolling** (`anchored=False`) | 训练窗固定大小，**向前滚动** | 模拟"每天用最近 N 年数据训练"的实战场景 |
| **Anchored** (`anchored=True`) | 训练窗**起点固定**、终点向前移动 | 用尽所有可用数据；适合数据稀疏场景 |

### 5.3 `WalkForward.run()`

```python
from getrich_backtest import WalkForward

wf = WalkForward(
    spec=spec,
    search=grid,
    select_metric="sharpe_ratio",
    maximize=True,
)
result = wf.run(
    strategy_factory=lambda params: MyStrategy(**params),
    backtest_factory=lambda strat, trial: Backtest(strategy=strat, ...),
)
```

返回 `WalkForwardResult`，结构：

```python
@dataclass
class WalkForwardResult:
    spec: WalkForwardRunSpec
    windows: tuple[WalkForwardWindowResult, ...]  # 每个 window 一个

@dataclass
class WalkForwardWindowResult:
    window: WalkForwardWindow           # (train_start, train_end, test_start, test_end)
    best_trial: SweepTrial               # in-sample 挑出的赢家
    oos_result: BacktestResult | None    # out-of-sample 表现
    oos_metrics: BacktestMetrics | None
    sweep_result: SweepResult             # in-sample sweep 完整结果
```

### 5.4 拼接 OOS 收益

把所有 window 的 OOS 段拼起来，就是"模拟实盘"的权益曲线：

```python
import polars as pl

oos_curves = [
    w.oos_result.equity_curve.with_columns(pl.lit(w.window.test_start).alias("window_start"))
    for w in result.windows
    if w.oos_result is not None
]
combined = pl.concat(oos_curves).sort("dt")
print(f"Walk-Forward OOS Sharpe: {compute_metrics(combined).sharpe_ratio:.2f}")
```

### 5.5 `WalkForwardReport`

`WalkForwardReport` 把 window-by-window 结果渲染成可读报表（HTML / Markdown）：

```python
from getrich_backtest import WalkForwardReport

report = WalkForwardReport(result)
report.to_html("/tmp/wf-report.html")
report.to_markdown()  # stdout
```

---

## 6. 错误与重试

### 6.1 `RetryableError` vs `TerminalError`

`SweepRunner` 和 `WalkForward` 都遵循这个约定：

| 异常类型 | 触发条件 | Runner 行为 |
|---|---|---|
| `RetryableError` | 临时故障（DB blip、network timeout） | 重试 trial（按 `retry` 策略） |
| `TerminalError` | 配置错误（bad param、schema 不匹配） | 立刻 `mark_failed`，不再重试 |
| 任何其他 `Exception` | 未知 | 立刻 `mark_failed`，sweep 继续（除非 `fail_fast=True`） |

业务代码在 strategy / op 里 raise：

```python
class MyStrategy(Strategy):
    def on_bar(self, ctx):
        if ctx.bar["close"][0] <= 0:
            raise TerminalError(f"bad price: {ctx.bar['close'][0]}")
        if self._api_call_failed:
            raise RetryableError("rate limit hit")
```

### 6.2 `request_hash` 幂等

`BacktestJobStore` 用 `request_hash` 去重（Round #967 + 023 migration）：

```python
# 同一 sweep 的同一 trial，重复 POST 不会创建第二个 job
job_id = await store.create_job(
    job_type="sweep",
    request_json={"sweep_id": "sma-2024", "params": {...}},
    user_id=current_user.id,
)
# 如果 request_hash 已存在，返回已有的 job_id
```

---

## 7. 持久化

### 7.1 Sweep 持久化

```python
from getrich_backtest import PgSweepResultStore, SweepResult

store = PgSweepResultStore()
await store.save_result(sweep_result)
loaded = await store.load_result(sweep_id="sma-2024")
```

### 7.2 WalkForward 持久化

```python
from getrich_backtest import PgWalkForwardResultStore, walk_forward_windows_to_frame

store = PgWalkForwardResultStore()
await store.save_result(wf_result)
loaded = await store.load_result(wf_id="wf-sma-2024")
df = walk_forward_windows_to_frame(loaded)  # polars DataFrame
```

### 7.3 `walk_forward_windows_to_frame`

把 `WalkForwardResult` 摊成 Polars DataFrame，每行一个 window：

| window_start | window_end | best_params | oos_sharpe | oos_max_dd |
|---|---|---|---|---|
| 2020-01-01 | 2021-12-31 | {"fast": 10, "slow": 50} | 1.2 | -8.5% |
| 2021-01-01 | 2022-12-31 | {"fast": 15, "slow": 60} | 0.9 | -12.1% |
| ... | ... | ... | ... | ... |

---

## 8. 平台层集成

平台层用 Celery 异步跑 sweep/walk_forward：

```python
# POST /sweeps/
{
  "sweep_id": "sma-2024",
  "search": {...},
  "select_metric": "sharpe_ratio",
  "maximize": true
}
# → POST /backtest-jobs/ 创建 job，Celery worker 跑 SweepRunner
# → SSE 推送进度（SweepRunner 的 on_progress → job_persistence.update_progress）
# → 通过 PgSweepResultStore 持久化最终结果
```

详见 [Web API 参考 / Sweep](../platform/api-reference.md) 和 [平台架构（Phase 2）](../platform/architecture.md)。

---

## 9. 完整示例：MA sweep + walk-forward

```python
from datetime import datetime
from decimal import Decimal
from getrich_backtest import (
    Backtest, DataFrameBarLoader, Strategy, BarContext,
    ParamSpace, P, GridSearch, SweepRunner,
    WalkForward, WalkForwardRunSpec,
    get_shanghai_tz, Frequency,
)


class MAStrategy(Strategy):
    fast_window: int
    slow_window: int

    def on_bar(self, ctx: BarContext) -> list:
        fast = ctx.history("1d").sma(self.fast_window)
        slow = ctx.history("1d").sma(self.slow_window)
        if fast is None or slow is None:
            return []
        if fast > slow and ctx.account.position("A").qty == 0:
            return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]
        if fast < slow and ctx.account.position("A").qty > 0:
            return [OrderIntent(symbol="A", side=Side.SELL, qty=Decimal("100"))]
        return []


# 1. 参数空间
space = ParamSpace({
    "fast_window": P.int_range(5, 30, step=5),
    "slow_window": P.int_range(20, 100, step=10),
}).add_constraint(lambda p: int(p["fast_window"]) < int(p["slow_window"]))

grid = GridSearch(space=space)

# 2. Sweep
sweep = SweepRunner(sweep_id="ma-2024", search=grid, select_metric="sharpe_ratio")
sweep_result = sweep.run(
    strategy_factory=lambda p: MAStrategy(**p),
    backtest_factory=lambda s, t: Backtest(strategy=s, bar_loader=DataFrameBarLoader(bars), ...),
    on_progress=lambda i, total: print(f"Sweep {i}/{total}"),
)
print(f"Best in-sample Sharpe: {sweep_result.trials[0].metrics.sharpe_ratio:.2f}")

# 3. Walk-Forward
spec = WalkForwardRunSpec(
    full_start=datetime(2020, 1, 1, tzinfo=get_shanghai_tz()),
    full_end=datetime(2024, 12, 31, tzinfo=get_shanghai_tz()),
    train_window_bars=252 * 2,
    test_window_bars=252,
    step_bars=252,
)
wf = WalkForward(spec=spec, search=grid, select_metric="sharpe_ratio")
wf_result = wf.run(
    strategy_factory=lambda p: MAStrategy(**p),
    backtest_factory=lambda s, t: Backtest(strategy=s, bar_loader=DataFrameBarLoader(bars), ...),
)
print(f"Walk-Forward OOS Sharpe: "
      f"{sum(1 for w in wf_result.windows if w.oos_metrics) / len(wf_result.windows):.2f}")
```

---

## 10. 过拟合检测 checklist

| 信号 | 检测方法 |
|---|---|
| In-sample Sharpe 很高，OOS Sharpe 很低 | 对比 sweep 最佳 trial 的 in-sample 和 walk-forward OOS |
| 不同 window 的"最佳参数"差异巨大 | `walk_forward_windows_to_frame` 看 `best_params` 分布 |
| 取消约束后 sweep 表现差异巨大 | `Constraints.max_single_weight` 调严 / 调松，看 Sharpe 稳定性 |
| 删除 1 年数据后 sweep 表现差异巨大 | 重新跑 sweep，对比 metrics 漂移 |
| 同一 trial 重跑结果不稳定 | 检查 `backtest.run()` 的随机性来源（`ctx.rng` 是否 seed） |

---

## 11. 进一步阅读

- 设计契约：[50 参数搜索](../design-contracts/50-param-search.md)
- API 详情：[API 参考 — 参数扫描与 Walk-Forward](api-reference.md#10-参数扫描与-walk-forward)
- 平台层：[Web API 参考 / Sweep](../platform/api-reference.md) 和 [Web API 参考 / Walk-Forward](../platform/api-reference.md)
- 源码：
    - [`src/getrich_backtest/sweep.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/sweep.py)
    - [`src/getrich_backtest/walk_forward.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/walk_forward.py)
    - [`src/getrich_backtest/walk_forward_report.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/walk_forward_report.py)
