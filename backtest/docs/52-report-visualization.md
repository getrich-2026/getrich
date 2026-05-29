# 52. 报告与可视化

> 把回测结果转成可读、可分享的报告。对应原需求第 10 节"报告与可视化"。

## 1. 报告类别

| 报告 | 内容 | 适用 |
| --- | --- | --- |
| **Tear Sheet** | 单回测综合 | 策略复盘、PR review |
| **Walk-forward Report** | 多窗口对比、过拟合诊断 | 研究阶段 |
| **Factor Report** | IC/RankIC/分层/衰减 | 因子研究 |
| **Risk Dashboard** | Greeks 曲线、暴露热图、限额突破 | 风控 |
| **Stress Dashboard** | 各情景 PnL、保证金冲击 | 风控、合规 |
| **Multi-strategy Report** | 各策略横向对比、相关性、归因 | 投资组合管理 |
| **Compare Report** | 两/多次 run 对比 | A/B 测试 |

所有报告由统一的 `Reporter` 渲染框架生成，输出格式：HTML（默认）/ Parquet / JSON。

## 2. Tear Sheet 结构

```text
┌─────────────────────────────────────────────────────┐
│ Header: 策略名 · 版本 · 时间区间 · run_id            │
├─────────────────────────────────────────────────────┤
│ Summary 标量卡片：                                  │
│   Total / Annualized / Sharpe / Calmar / MaxDD /    │
│   WinRate / Payoff / Turnover / FeeDrag / ...       │
├─────────────────────────────────────────────────────┤
│ 权益曲线（含 benchmark 对比）                       │
├─────────────────────────────────────────────────────┤
│ 回撤曲线 + Top-5 回撤区间标记                       │
├─────────────────────────────────────────────────────┤
│ 月度收益热力图（年 × 月）                           │
├─────────────────────────────────────────────────────┤
│ 持仓时间序列 / 净敞口 / 杠杆                        │
├─────────────────────────────────────────────────────┤
│ 风险时间序列：Cash Delta / Vega / 风险度 / 单品种   │
├─────────────────────────────────────────────────────┤
│ Top-N 盈亏标的、Top-N trade、交易点位标注           │
├─────────────────────────────────────────────────────┤
│ 归因：按品种 / 行业 / 因子 / 时段 / 成本            │
├─────────────────────────────────────────────────────┤
│ 数据质量摘要（取自 11-data-quality §5 报告）        │
├─────────────────────────────────────────────────────┤
│ Footer: 配置摘要 · code_rev · data_version · seed   │
└─────────────────────────────────────────────────────┘
```

## 3. 图表清单

| 图 | 库 | 数据源 |
| --- | --- | --- |
| 权益曲线 | plotly | `equity.parquet` |
| 回撤曲线 | plotly | derived |
| 月度收益热力图 | plotly | derived from `equity.parquet` |
| 持仓堆叠 | plotly | `positions_timeline.parquet` |
| 净敞口 / 杠杆时序 | plotly | `risk_timeline.parquet` |
| Cash Greeks 时序 | plotly | `greeks_timeline.parquet` |
| 因子 IC 热图 | plotly | factor report |
| 分层回测 | plotly | layered result |
| 参数稳定性热图（Walk-forward） | plotly | sweep result |
| 成交点位（OHLC + buy/sell mark） | plotly | `fills.parquet` |
| 蜘蛛图（风险维度雷达） | plotly | risk snapshot |

> 也可启用 `pyecharts` 后端渲染权益/回撤/月度热图（视觉风格更接近内部 BI），由 `Reporter(backend='echarts')` 选择。

## 4. Reporter 接口

```python
class Reporter:
    def __init__(self, result: BacktestResult, theme: str = "light"): ...

    def tear_sheet(self) -> TearSheet: ...
    def factor_report(self) -> FactorReport: ...
    def walk_forward(self) -> WalkForwardReport: ...
    def risk_dashboard(self) -> RiskDashboard: ...
    def stress_dashboard(self) -> StressDashboard: ...

class TearSheet:
    def to_html(self) -> str: ...
    def to_dict(self) -> dict: ...
    def to_parquet(self, path: Path) -> None: ...
    def save(self, dir_: Path, formats: list[str] = ["html"]) -> Path: ...
```

## 5. Walk-forward Report 专属

```text
┌─────────────────────────────────────────────────┐
│ 拼接 OOS 权益曲线（vs benchmark）               │
├─────────────────────────────────────────────────┤
│ 每窗口 Train vs Val Sharpe 对比柱图             │
├─────────────────────────────────────────────────┤
│ 参数选择时序：每窗口选中的参数标记              │
├─────────────────────────────────────────────────┤
│ 二维参数稳定性热图（取所有窗口聚合）            │
├─────────────────────────────────────────────────┤
│ IS-OOS Sharpe 散点（每窗口一点）                │
├─────────────────────────────────────────────────┤
│ PBO 估计 / 拔靴法 p-value                       │
└─────────────────────────────────────────────────┘
```

## 6. 多 Run 对比报告

```python
report = compare_runs([
    "runs/9f3c8b1a/",
    "runs/baseline/",
])
report.equity_overlay()           # 多权益曲线叠加
report.metric_diff_table()        # 指标差异表
report.config_diff()              # 配置 patch
report.save_html("runs/_compare_ma_vs_baseline.html")
```

## 7. 导出格式

| 格式 | 用途 |
| --- | --- |
| `html` | 主报告，可独立打开（资源 inline） |
| `parquet` | 所有时序数据（权益、回撤、月度、归因）单独导出，便于二次分析 |
| `json` | 标量指标、配置摘要、识别信息，方便注入到 dashboard |
| `pdf` | 通过 weasyprint 转 HTML→PDF（可选依赖） |

资源处理：

- HTML 中图表用 `plotly.io.to_html(include_plotlyjs="cdn")` 引用 CDN，文件 ≤ 1MB
- 离线模式 `embed=True` 时所有 JS inline，文件 5-15MB

## 8. CLI 渲染

```bash
getrich-bt report runs/9f3c8b1a/                # 默认 tear sheet
getrich-bt report runs/9f3c8b1a/ --kind risk    # 风险报告
getrich-bt report runs/9f3c8b1a/ --compare runs/baseline/
```

也可在 Python 端：

```python
from getrich_backtest.report import Reporter
Reporter(result).tear_sheet().save("runs/9f3c8b1a/", formats=["html", "parquet"])
```

## 9. 主题与定制

- `theme="light" | "dark" | "minimal"`
- 自定义模板：`Reporter(result, template_path="my_template.j2")`
- 注入 LOGO / 公司信息：`Reporter(...).set_brand(name, logo_path)`

## 10. 报告与归因的一致性

- 报告中所有展示的指标都引用 `MetricsCalculator` 与 `AttributionEngine` 的输出
- 报告生成时再做一次 §8 对账（详见 `42-benchmark-attribution.md` §8）
- 不一致直接 `ReportConsistencyError`，避免"报告好看但内部错"

## 11. 最小示例

```python
result = bt.run(strategy)

from getrich_backtest.report import Reporter
report = Reporter(result, theme="light")
report.tear_sheet().save("runs/9f3c8b1a/tear_sheet/", formats=["html", "parquet", "json"])
report.risk_dashboard().save("runs/9f3c8b1a/risk/", formats=["html"])

# 比较两次 run
from getrich_backtest.report import compare_runs
compare_runs(["runs/9f3c8b1a/", "runs/baseline/"]).save_html("runs/_cmp.html")
```

## 12. 设计禁区

- **禁止**报告把 1m 收益放在 Sharpe 卡片里（必须 downsample 到日频，详见 `40-metrics.md` §9）。
- **禁止**HTML 报告超过 50MB（资源 embed 模式下需主动裁剪）。
- **禁止**在 tear sheet 隐藏 `data_quality` 报告中的 ERR/WARN——必须显示。
- **禁止**报告中使用未经一致性校验的归因数字。
