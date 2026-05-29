# 50. 参数搜索与样本外验证

> 防止过拟合的核心模块。覆盖参数网格/随机/贝叶斯搜索、Walk-forward、Train/Val/Test 切分、稳定性分析。对应原需求第 5 节"参数搜索与样本外验证"。

## 1. 搜索范式

| 方法 | 何时用 | 内置类 |
| --- | --- | --- |
| **Grid** | 参数维度 ≤ 4、连续小空间 | `GridSearch` |
| **Random** | 参数 ≥ 5 维或长尾搜索 | `RandomSearch` |
| **Bayesian** | 评估成本高 | `BayesianSearch`（基于 `scikit-optimize`） |
| **CMA-ES** | 连续高维优化 | `CmaesSearch` |

均实现 `ParamSweep` 协议：

```python
class ParamSweep(Protocol):
    def iter_configs(self) -> Iterable[ParamConfig]: ...
    def report(self, results: list[SweepResult]) -> SweepReport: ...
```

## 2. 参数空间定义

```python
from getrich_backtest.research import ParamSpace, P

space = ParamSpace({
    "fast": P.int_range(3, 20, step=1),
    "slow": P.int_range(20, 100, step=5),
    "atr_mult": P.float_range(1.0, 3.0, step=0.25),
    "use_filter": P.categorical([True, False]),
    "neutralize": P.categorical(["industry", "size", "industry_size", "none"]),
})
# constraint：fast < slow
space.add_constraint(lambda cfg: cfg["fast"] < cfg["slow"])
```

## 3. Walk-forward

```text
|---- Train 24m ----|--- Val 6m ---|       step
                     |---- Train 24m ----|--- Val 6m ---|
                                          |---- Train ...
```

每次窗口：在 Train 上做 ParamSweep → 选最优配置 → 在 Val 上单跑 → 拼接 Val 段权益。

```python
wf = WalkForward(
    train_months=24,
    val_months=6,
    step_months=6,
    refit="rolling",       # rolling / anchored
    select_metric="sharpe",
    select_n=1,            # top-n 配置在 Val 上同时跑（取均值或保守者）
)

result = wf.run(
    strategy_cls=MACross,
    param_space=space,
    bt_template=bt_config,   # 除参数外的回测配置
    start="2018-01-01",
    end="2024-12-31",
)
```

### 3.1 Refit 模式

- `rolling`：训练窗口固定长度向前滚动（窗口外样本不进入下次训练）
- `anchored`：训练起点固定，窗口逐步扩张（更稳定但反应慢）

### 3.2 Val 段权益拼接

按 Val 段时序连续拼接为单条"样本外权益曲线"，用 §6 的报告统一呈现。同时保留每段的 Train/Val 单独报告。

## 4. Train / Val / Test 三段切分

适合非滚动的"一次性"研究：

```python
splits = TimeSplitter.split(
    "2018-01-01", "2024-12-31",
    train_ratio=0.6, val_ratio=0.2, test_ratio=0.2,
    mode="chronological",   # 按时间顺序
)
# splits.train = (2018-01-01, 2022-03-15)
# splits.val   = (2022-03-15, 2023-08-08)
# splits.test  = (2023-08-08, 2024-12-31)
```

约定：

- Train 上做参数搜索
- Val 上做"在线选模型"或"早停"
- Test 上做**一次性**最终评估，**禁止反复回访 Test**

引擎记录 Test 访问次数；超过 1 次发出 `TestSetLeakageWarning` 并在最终报告高亮。

## 5. 过拟合检测

### 5.1 IS / OOS 一致性

```python
@dataclass
class ISOOSReport:
    is_sharpe_top_n: list[float]
    oos_sharpe_top_n: list[float]
    rank_corr_is_oos: float        # IS 排名 vs OOS 排名的 Spearman
    drop_off_ratio: float          # mean(OOS) / mean(IS)
```

`drop_off_ratio < 0.3` 视为强过拟合信号；`rank_corr < 0.2` 视为参数选择无效。

### 5.2 参数稳定性热力图

二维参数（如 fast × slow）：

```
Sharpe heatmap(fast × slow)
```

读法：

- 单点尖峰 → 过拟合
- 大片高 Sharpe 平台 → 稳健参数区
- 等高线发散 → 参数不敏感

支持 N 维主成分降维到 2D 后绘制。

### 5.3 拔靴法（Block Bootstrap）

把日度收益按 N 天 block 重采样 K 次（默认 N=20, K=1000），得到 K 条"假装的另一条历史"上的 Sharpe 分布。`p_value` = `P(Sharpe_bootstrap > 0)`；< 0.05 视为统计显著。

### 5.4 PBO（Probability of Backtest Overfitting）

按 Lopez de Prado (2015) 实现：

- 把回测期切成 K 块（默认 K=16）
- 按所有 `C(K, K/2)` 种 Train/Val 切分，记录 IS 最优策略在 OOS 上是否仍跑赢中位数
- `PBO = P(IS-best OOS-rank < median)`
- 值越接近 0.5 越接近"随机"，> 0.5 视为强过拟合信号

## 6. 报告

```python
report = wf.report()
report.iso_oos_table()
report.heatmap("fast", "slow", metric="sharpe")
report.stability_curve()
report.pbo()
report.save_html("runs/abc/walkforward.html")
```

报告结构（详见 `52-report-visualization.md` §5）：

- 顶部：综合判断（过拟合风险、推荐配置）
- 中部：参数稳定性热力图、IS/OOS 散点
- 底部：每个窗口的详细回测摘要

## 7. 并行执行

回测进程隔离，多核 / 多机分发：

```python
runner = SweepRunner(
    backend="multiprocessing", workers=8,
    cache_dir="runs/_sweep_cache/",  # 配置哈希命中即跳过
)
results = runner.run(strategy_cls, space, bt_template)
```

- `cache_dir` 用 `(RunConfig hash, code_rev hash, data_version)` 三元组哈希做 key；命中则直接读上次结果（详见 `51-config-versioning.md`）。
- backend 也支持 `ray` / `dask`，接口同。

## 8. 多目标搜索

`select_metric` 可为函数或 `Pareto` 多目标：

```python
wf = WalkForward(
    ...,
    select_metric=Pareto([
        Metric("sharpe", maximize=True),
        Metric("max_drawdown", maximize=False),
        Metric("turnover_annual", maximize=False),
    ]),
)
```

返回 Pareto 前沿，由用户最终选；可叠加约束（如 `sharpe > 1.5 AND max_drawdown > -0.15`）。

## 9. 因子参数搜索

因子参数（如 mom 的回看天数）可用同一接口：

```python
fe_sweep = FactorParamSweep(
    factor_fn=lambda lookback: compute_mom(lookback),
    space=ParamSpace({"lookback": P.int_range(5, 60, step=5)}),
    metric="rank_ic_ir",
)
```

输出 IC/RankIC 随参数变化曲线。

## 10. 最小示例

```python
from getrich_backtest.research import (
    WalkForward, ParamSpace, P, GridSearch,
)

space = ParamSpace({
    "fast": P.int_range(3, 20, step=2),
    "slow": P.int_range(20, 100, step=10),
})
space.add_constraint(lambda c: c["fast"] < c["slow"])

wf = WalkForward(
    train_months=18, val_months=3, step_months=3,
    sweep=GridSearch(space),
    select_metric="sharpe",
    refit="rolling",
)

result = wf.run(
    strategy_cls=MACross,
    bt_template={
        "universe": Universe.csi_300(),
        "freq": "1d",
        "initial_capital": Decimal("10_000_000"),
        "fee_model": FeeModel.equity_a_default(),
    },
    start="2018-01-01",
    end="2024-12-31",
)

result.report().save_html("runs/ma_wf.html")
```

## 11. 设计禁区

- **禁止**在 Train 上做特征选择又在 Train 上做参数搜索而不留 Val（双重选择都用同一数据）。
- **禁止**反复回访 Test 集——`TestSetLeakageWarning` 出现则报告必须高亮。
- **禁止**只看 Sharpe 不看 PBO/IS-OOS 一致性。
- **禁止**用未来数据（如"截至今天"的 universe 成分股）回填到 Train 段——universe 必须用每个时点的历史快照。
