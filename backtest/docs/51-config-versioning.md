# 51. 配置、版本与可复现

> 让任意一次回测**可复跑、可对账、可审计**。对应原需求第 8 节"配置、版本与可复现"。

## 1. 可复现的最小单位

一次回测的**复现身份** = `(RunConfig, DataVersion, CodeRev, Seed)` 四元组。同样的四元组在不同机器、不同时间运行，必须得到逐 fill 一致的结果。

```python
@dataclass(frozen=True)
class RunIdentity:
    run_id: str               # 自动生成，纯函数哈希
    config_hash: str          # RunConfig 内容哈希（json-canonical → sha256）
    data_version: str         # 数据快照版本（详见 §3）
    code_rev: str             # git commit + dirty marker
    seed: int                 # 随机种子
    started_at: datetime
```

`run_id = sha256(config_hash || data_version || code_rev || seed)[:12]`

## 2. RunConfig

完整 RunConfig 用 `pydantic` 定义，落 YAML：

```yaml
# config/ma_cross_v1.yaml
identity:
  strategy: "ma_cross_v1"
  description: "Double MA crossover on CSI300"

period:
  start: 2023-01-01
  end:   2024-12-31
  timezone: Asia/Shanghai

universe:
  type: csi_300
  rebalance_membership: monthly

data:
  freq: 1d
  adj_policy: pre
  loader:
    type: pgsql
    dsn_ref: getrich_main         # 引用 ~/.config 中的连接配置

capital:
  initial: "10000000"             # Decimal
  currency: CNY

strategy:
  class: getrich_strategies.ma.MACross
  params:
    fast: 5
    slow: 20
    atr_mult: 1.5

execution:
  matching: NextBarMatchingModel
  execution_lag_bars: 1
  slippage:
    equity_a:        { type: fixed_bps, bps: 5 }
    commodity_future: { type: fixed_tick, n: 1 }
  fees:
    equity_a:        default
    commodity_future: default
  capacity:
    type: bar_pct
    rate: 0.05
    mode: defer

risk:
  limits:
    - { scope: PORTFOLIO, metric: GROSS_LEVERAGE, upper: "3.0", action: BLOCK_NEW }
    - { scope: PORTFOLIO, metric: RISK_RATIO,     upper: "0.9", action: BLOCK_NEW }
    - { scope: STRATEGY,  metric: PRODUCT_EXP, key: IF, upper: "0.5", action: REDUCE }

benchmark:
  symbol: 000300.SH

reporting:
  formats: [html, parquet, json]
  output_dir: runs/{run_id}/

seed: 20250528
```

加载：

```python
from getrich_backtest.runtime import RunConfig
cfg = RunConfig.from_yaml("config/ma_cross_v1.yaml")
```

### 2.1 Schema 校验

- `pydantic` 强类型校验
- 自定义校验：`start < end`、`fast < slow`、连接 DSN 可解析
- 不通过校验直接 `ValidationError`，回测不启动

### 2.2 配置 Diff

```python
cfg_a.diff(cfg_b)
# 输出 RFC-6902 JSON Patch：[{op: replace, path: /strategy/params/fast, value: 8}, ...]
```

便于 PR review、A/B 配置对比。

## 3. 数据版本（DataVersion）

数据本身可变（修复行情错误、补回失败的导入），因此回测必须**钉**到具体快照。

### 3.1 快照机制

每个数据源 `BarLoader` 暴露：

```python
class BarLoader(Protocol):
    def version(self) -> str: ...
    def snapshot(self, dt: datetime | None = None) -> "BarLoader": ...
```

- `version()`：返回当前数据版本号（例如 `pgsql:md_bars@2025-05-28T10:00:00Z`，对应 PostgreSQL 中的 `last_modified` 最大值）
- `snapshot(dt)`：返回锁定到 `dt` 时刻的 view（PgSQL 用 `last_modified` 时间戳过滤或时间分区只读；离线 Parquet 仓用 commit hash）

### 3.2 快照存储

| 场景 | 实现 |
| --- | --- |
| 短期复现 | 引用 PgSQL 的 `last_modified` 时间戳，假设数据只追加 |
| 长期归档 | 把当次回测用到的数据 dump 为 Parquet 到 `runs/{run_id}/data_snapshot/`（适合关键回测） |
| Walk-forward | 共享一个 `data_version`，所有窗口跑在同一快照上 |

`RunConfig.data.snapshot_strategy = "ref" | "dump"`，默认 `ref`。

## 4. 代码版本

```python
CodeRev:
  git_commit: 8467e9e6...
  branch: dev
  dirty: true | false
  patch_hash: sha256(diff)   # 仅 dirty=true 时
```

- 干净（dirty=false）：`code_rev = git_commit`
- 脏（dirty=true）：`code_rev = f"{git_commit}-dirty-{patch_hash[:8]}"`，并把 `git diff` 落到 `runs/{run_id}/code_diff.patch`

CI 模式下强制 `dirty=false`，否则拒绝运行。

## 5. 随机种子

整链路所有随机源都接 `Seed`：

- 策略 RNG：`ctx.rng = random.Random(seed=seed)`
- 执行引擎滑点采样（若用随机扰动）：`engine.rng = random.Random(seed=seed + 1)`
- Monte Carlo VaR：`mc.rng = random.Random(seed=seed + 2)`

种子写入 `RunConfig.seed`；缺省时使用 `int.from_bytes(secrets.token_bytes(8))` 并落到 manifest。

## 6. Run Manifest

每次回测启动时落盘 `runs/{run_id}/manifest.json`：

```json
{
  "run_id": "9f3c8b1a4e2d",
  "config_hash": "ab12...",
  "data_version": "pgsql:md_bars@2025-05-28T10:00:00Z",
  "code_rev": "8467e9e6",
  "seed": 20250528,
  "started_at": "2026-05-28T14:00:00+08:00",
  "finished_at": "2026-05-28T14:23:45+08:00",
  "wall_time_seconds": 1425,
  "host": "wsl-johnny",
  "user": "johnny",
  "python_version": "3.13.1",
  "polars_version": "1.20.0",
  "config_path": "config/ma_cross_v1.yaml",
  "config_hash_inputs_canonical": "...",
  "summary": {
    "total_return": "0.234",
    "sharpe": "1.42",
    "max_drawdown": "-0.085"
  }
}
```

## 7. Snapshot 目录

```text
runs/{run_id}/
├── manifest.json
├── config.yaml                # 实际生效配置（可能含命令行覆盖）
├── config_canonical.json      # 规范化 JSON，用于哈希
├── code_diff.patch            # 仅 dirty=true 时
├── data_snapshot/             # snapshot_strategy=dump 时
│   ├── bars/...
│   └── calendar.parquet
├── checkpoint/                # 热启动点
│   └── 2024-09-30/
│       ├── account.parquet
│       └── strategy_state.parquet
├── ledger.parquet             # 全部资金流水
├── fills.parquet
├── orders.parquet
├── positions_timeline.parquet
├── risk_timeline.parquet
├── greeks_timeline.parquet
├── equity.parquet
├── trades.parquet
├── attribution.parquet
├── data_quality.json          # 详见 11-data-quality §5
├── risk_alerts.parquet
├── stress_dashboard.html
├── tear_sheet.html
└── summary.json
```

## 8. 复跑校验（Replay Check）

```python
from getrich_backtest.runtime import Replayer

replay = Replayer("runs/9f3c8b1a4e2d/")
new_run = replay.rerun()
diff = replay.diff(new_run)

assert diff.fills.is_empty()
assert diff.equity.l_inf < 1e-9
```

不一致时：

- 触发 `ReplayMismatchError`
- 自动 dump diff 报告到 `runs/{run_id}/replay_diff.json`

支持 CI 模式：

```bash
getrich-bt replay-check runs/9f3c8b1a4e2d --strict
```

## 9. 配置继承与覆盖

支持 YAML 继承：

```yaml
# config/base.yaml
period: ...
data: ...
execution: ...

# config/ma_cross_v1.yaml
extends: base.yaml
strategy: ...
```

命令行覆盖：

```bash
getrich-bt run config/ma_cross_v1.yaml \
    --override strategy.params.fast=8 \
    --override seed=42
```

覆盖结果作为最终 `RunConfig` 落盘。

## 10. 与 Sweep 的关系

参数搜索的每个 trial 都生成独立 `run_id`，共享同一 `data_version` 与 `code_rev`，仅 `config_hash` / `seed` 不同。`SweepRunner.cache_dir` 按 `(config_hash, data_version, code_rev)` 三元组缓存结果，避免重复计算。

## 11. 最小示例

```python
from getrich_backtest.runtime import RunConfig
from getrich_backtest import Backtest

cfg = RunConfig.from_yaml("config/ma_cross_v1.yaml")
bt = Backtest.from_config(cfg)
result = bt.run()

print(result.identity.run_id)             # '9f3c8b1a4e2d'
print(result.snapshot_dir)                # runs/9f3c8b1a4e2d/

# 1 年后，原始回测目录还在
from getrich_backtest.runtime import Replayer
replay = Replayer("runs/9f3c8b1a4e2d/")
new = replay.rerun()                       # 完全一致
```

## 12. 设计禁区

- **禁止**未通过 Schema 校验启动回测。
- **禁止**dirty 代码上 CI（`getrich-bt run --strict` 拒绝 dirty）。
- **禁止**让两次"逻辑上一致"的回测得到不同结果——必须能精确到 fill 数据级对账。
- **禁止**配置默认值散落在代码各处——所有默认值落在 `runtime/config_defaults.py` 单一文件，便于审计。
- **禁止**修改已落盘的 `runs/{run_id}/` 内容（除手动 `--evict` 清理）。
