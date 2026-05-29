# 41. 因子评估

> 与策略回测并行的研究分支。给定一个因子（如 `mom20`、`pe_inv`、`iv_skew`），评估它对未来收益的预测力、稳定性、衰减、换手与组合质量。对应原需求"因子评估"全部条目。

## 1. 因子表 Schema（长表）

```text
columns:
  dt:       Datetime("ms", "Asia/Shanghai")
  symbol:   Utf8
  factor:   Utf8                # 因子名
  value:    Float64             # 原始值
  asset_class: Categorical
```

存储：与行情同库 PgSQL，表名 `factors_long`，PgSQL 声明式分区 `PARTITION BY RANGE (dt)` 按月切分，索引 `(factor, dt, symbol)`；大批量回填用 `COPY` 协议。本回测引擎按需 SQL 提取后转 Polars 长表。

## 2. 评估流程

```text
Factor (raw)
   │
   ▼
1. 预处理 (与 21-portfolio-construction §2 共用)
   │
   ▼
2. 对齐未来收益 (前瞻 H 期 forward return)
   │
   ▼
3. IC / RankIC / IR 计算
   │
   ▼
4. 分层回测 (Quantile portfolio)
   │
   ▼
5. 衰减 (Decay)、换手 (Turnover) 分析
   │
   ▼
6. 报告
```

## 3. Forward Return

定义"未来 H 期收益"：

```
fwd_return_t,i,H = price_{t+H, i} / price_{t, i} - 1
```

- 价格基准：`price = open_{t+1}` 至 `close_{t+H}`，避免用 `close_t` 引入 look-ahead（与 `30-execution-engine.md` lag 一致）
- 多个 H：典型 `H ∈ {1, 5, 10, 20, 60}` 个 bar / 天
- 中性化 forward return：可减去市场 / 行业平均，研究 alpha

## 4. IC / RankIC / IR

### 4.1 IC

```
IC_t(H) = Pearson(factor_t, fwd_return_t,H)
```

横截面（每个 t）算一次，得到 IC 时序。汇总：

| 指标 | 公式 |
| --- | --- |
| `IC_mean` | `mean(IC_t)` |
| `IC_std` | `std(IC_t)` |
| `IC_IR` | `IC_mean / IC_std` |
| `IC_t_stat` | `IC_mean / (IC_std / √N)` |
| `IC_positive_ratio` | `Σ IC_t > 0 / N` |
| `IC_skew` | 偏度 |

### 4.2 RankIC

把 factor 与 fwd_return 转秩后计算 Spearman：

```
RankIC_t(H) = Spearman(factor_t, fwd_return_t,H)
```

RankIC 对极端值更鲁棒，是主流因子评价指标。

### 4.3 IR

```
IR = IC_mean / IC_std
```

可分别报 `IC_IR` 和 `RankIC_IR`。

## 5. 分层回测（Layered / Quantile Backtest）

将横截面按 factor 分 K 组（默认 5 / 10）：

```python
class LayeredBacktest:
    def __init__(self, factor: str, k: int = 5, weighting: str = "equal",
                 rebalance: str = "1d", H: int = 1,
                 long_short: bool = True): ...

    def run(self, ctx) -> LayeredResult: ...

@dataclass
class LayeredResult:
    equity_by_group: pl.DataFrame      # [dt, q1, q2, ..., qk]
    long_short_equity: pl.DataFrame    # qk - q1
    metrics_per_group: pl.DataFrame    # 每组 Sharpe / annual return / max_dd
    monotonicity: float                # IC 的方向性（kendall's tau between rank & annual return）
    turnover_per_group: pl.DataFrame
```

注意事项：

- 调仓频率与 H 应对齐，否则会有"调仓 lag 偏差"
- `weighting`: `equal` / `value` / `score`（按因子值大小线性映射）
- 行业/市值中性化后再分层（避免 q1 全是小盘股）

## 6. 衰减分析（Decay）

观察因子在不同前瞻 H 下的 IC 变化：

```
IC_H = mean over t of IC_t(H)  for H in [1, 2, ..., 60]
```

输出 `IC_decay_curve`：随 H 增大 IC 衰减速度。

- 快衰减（H=1 即接近 0）：高频因子
- 慢衰减（H=20 仍显著）：低频价值类因子
- 拐点：决定最优调仓频率

## 7. 因子换手率

```
turnover_t = mean over symbols of |w_t - w_{t-1}|
```

由分层回测的目标权重时序计算。结合 IC 评估：

```
adjusted_IR = IR × (1 - cost_per_turnover × annual_turnover / annual_return)
```

提供"换手成本调整 IR"作为更现实的因子质量指标。

## 8. 多因子综合评估

支持多因子合成与正交化：

| 步骤 | 说明 |
| --- | --- |
| `factor_corr_matrix` | 因子横截面相关矩阵，识别共线 |
| `gram_schmidt(target, by=["mom20", "size"])` | 把 `target` 因子对其他因子正交化 |
| `linear_combine(weights)` | 加权组合得到合成因子 |
| `ic_per_industry`, `ic_per_size_bucket` | 分组 IC，识别在哪些子集表现稳健 |

## 9. FactorEvaluator 接口

```python
class FactorEvaluator:
    def __init__(self, factor_store: FactorStore, bars_loader: BarLoader): ...

    def ic(self, factor: str, universe: Universe, start, end,
           H: int = 1, method: str = "rank") -> ICResult: ...
    def decay(self, factor: str, universe: Universe, start, end,
              horizons: list[int]) -> DecayResult: ...
    def layered(self, factor: str, universe: Universe, start, end,
                k: int = 5, **kw) -> LayeredResult: ...
    def report(self, factor: str, universe: Universe, start, end) -> FactorReport: ...
```

`FactorReport` 是把 IC/Decay/Layered/Turnover 一键合并的高层接口，用于生成因子 tear sheet（详见 `52-report-visualization.md` §4）。

## 10. 与策略回测共享的部分

- 数据层：同一 `BarLoader` 与 `Universe`
- 预处理：同一套 `Winsorize`/`Standardize`/`Neutralize`
- 调仓与换手：分层回测复用 `ExecutionEngine` 与 `CapacityModel`（默认关闭，但研究"现实因子收益"时打开）
- 报告：tear sheet 共用 `Reporter` 渲染

## 11. 最小示例

```python
from getrich_backtest.analytics import FactorEvaluator
from getrich_backtest.strategy import Universe

fe = FactorEvaluator(factor_store, bar_loader)
universe = Universe.csi_500()

# IC / RankIC
ic = fe.ic("mom20", universe, "2022-01-01", "2024-12-31", H=5, method="rank")
print(ic.summary())
# RankIC_mean=0.043, RankIC_IR=0.62, t_stat=4.1, positive_ratio=0.58

# Decay
decay = fe.decay("mom20", universe, "2022-01-01", "2024-12-31", horizons=[1,5,10,20,60])
decay.plot()  # 衰减曲线

# 分层
layered = fe.layered("mom20", universe, "2022-01-01", "2024-12-31", k=10)
print(layered.metrics_per_group)
print(f"Monotonicity (Kendall's tau): {layered.monotonicity:.3f}")
layered.long_short_equity.write_parquet("runs/mom20/ls_equity.parquet")
```

## 12. 设计禁区

- **禁止**用未来 H 期的收益**反向训练**因子的 lag（典型 look-ahead）。
- **禁止**在分层回测里用 `close_t` 作为下一根的开仓价（必须用 `open_{t+1}`）。
- **禁止**忽略行业 / 市值中性化即下结论——会被风格因子污染。
- **禁止**只看 IC 均值不看 IC 稳健性（`IR` 与 `positive_ratio` 同样重要）。
