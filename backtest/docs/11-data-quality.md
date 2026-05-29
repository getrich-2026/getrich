# 11. 数据质量与复权

> 本文档定义"数据进入回测引擎前"的清洗与口径，对应原需求第 1 节"数据质量与复权体系"。规则的核心目标：**避免 look-ahead、避免幽灵收益、口径一致**。

## 1. 缺失、异常与停牌

| 场景 | 检测 | 处理 |
| --- | --- | --- |
| 缺失 bar | (`symbol`, `freq`) 按 Calendar 应有但缺失 | 1m：日内插入空 bar，OHLC 全为前一根 close，`volume=0`，`is_missing=true` 标记；1d：不补 |
| 异常价格 | `|close - prev_close| / prev_close > 0.5` 且非涨跌停 | 标记 `is_outlier=true`，由数据流水线人工复核；回测引擎默认**剔除该 bar**（不参与撮合与估值） |
| 成交量为 0 | `volume == 0` | 视为不可成交；执行引擎拒绝该 bar 的市价/限价撮合（详见 `30-execution-engine.md` §3） |
| 停牌 | `is_suspended=true` | 该 bar 既不下单也不估值；持仓估值用最近一个非停牌 `close` |
| 涨停 | `close >= limit_up - eps` | 买单**部分成交概率为 0**（详见 `30-execution-engine.md` §3.4）；卖单允许成交 |
| 跌停 | `close <= limit_down + eps` | 卖单部分成交概率为 0；买单允许成交 |
| ST/*ST | `is_st=true` | 仅打标，由策略 universe 过滤决定是否参与；引擎不自动剔除 |

`eps`：A 股取 `1e-4 × close`，期权取 `tick_size`。

### 1.1 缺失 bar 的"不可成交"传播

某根 bar `is_missing=true` 时：

- 该 bar 上的 `OrderIntent` 全部转为下一根 bar 重新尝试（带 `attempt_count`）；
- `attempt_count > max_attempts`（默认 3）则订单自动取消，触发 `on_order_expired`。

## 2. A 股复权

### 2.1 三种口径

| 口径 | 用途 | 计算 |
| --- | --- | --- |
| `none` 不复权 | 真实交易回放；账户层估值与结算 | 原始价 |
| `pre` 前复权 | 策略研究、因子计算（多数情况） | 以**最新除权日**为基准，历史价 ÷ 累计前复权因子 |
| `post` 后复权 | 长周期分析、净值口径 | 以**上市日**为基准，未来价 × 累计后复权因子 |

### 2.2 复权因子表

`md_adj_factor_equity`：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `symbol` | `Utf8` | |
| `dt` | `Date` | 除权除息日 |
| `pre_factor` | `Float64` | 当日及之前的前复权累计因子 |
| `post_factor` | `Float64` | 当日及之后的后复权累计因子 |
| `event_type` | `Enum{div,split,rights,bonus}` | 事件类型 |
| `cash_dividend` | `Float64` | 每股现金分红 |
| `split_ratio` | `Float64` | 拆股比例（送转） |
| `rights_price` | `Float64` | 配股价 |
| `rights_ratio` | `Float64` | 配股比例 |

### 2.3 引擎内的复权策略

- **策略层（信号/因子）**：默认 `adj_policy="pre"`，价格序列连续，便于技术指标。
- **账户层（估值/结算）**：必须 `adj_policy="none"`，按真实当日不复权价记账；除权除息日由"公司行为引擎"调整持仓股数与现金（见 §2.4）。
- **回测器自动区分**：`Backtest` 在装载时调用两份数据，分别注入策略上下文与账户上下文。**策略代码不应直接读未复权价**。

### 2.4 公司行为对持仓的调整（落到账户层）

除权除息日 T，账户层在 T 日**收盘结算后**执行：

| 事件 | 操作 |
| --- | --- |
| 现金分红 | `cash += shares × cash_dividend × (1 - dividend_tax_rate)`；股数不变。税率按持有期阶梯（< 1 月 20%，1 月-1 年 10%，> 1 年 0%） |
| 送转股 | `shares = shares × (1 + split_ratio)`；现金不变；下一根 bar 的 mark-to-market 自动按新股数 × 复权后新价 |
| 配股 | 在配股股权登记日提示策略；策略需在缴款截止日前下"参与/放弃"指令；账户按指令扣现金、加股数 |
| 红股 | 同送转股逻辑 |

> 配股事件向策略推送 `on_corp_action(event)` 回调；策略未实现则默认**放弃**。

## 3. 期货主连与换月

### 3.1 主连类型

| 主连 | 选取规则 | 行情列名 |
| --- | --- | --- |
| 主力 (`main`) | 当日**持仓量最大**的活跃合约 | `RB.SHF` (主连) |
| 次主力 (`sub`) | 持仓量第二大且距离到期 > N 日 | `RB_SUB.SHF` |
| 加权指数 (`weighted`) | 按持仓量加权的合成价格 | `RB_W.SHF` |

### 3.2 换月规则

1. **触发**：T 日收盘后，若旧主力 `oi(t) < new_candidate.oi(t)` 且 `new_candidate.oi(t) > 1.05 × old.oi(t)`（阈值可配），则 T+1 切换。
2. **避免抖动**：主力一旦切换，**N 日**（默认 10）内不再回切。
3. **临近交割锁定**：旧主力距离最后交易日 ≤ 7 日，强制切换到次主力。

### 3.3 价差跳变处理

主连切换会产生跳变（旧 → 新合约价差非零）。两种处理口径：

| 模式 | 处理 | 适用 |
| --- | --- | --- |
| `splice` 拼接 | 在切换日把所有 OHLCV、settlement 整体平移 `Δ = new_close - old_close`，使曲线连续 | 趋势策略、因子研究 |
| `ratio` 比例 | 整体乘 `ratio = new_close / old_close` | 收益率研究、波动率估计 |
| `none` 原始 | 不调整，留跳变 | 风险测试、滑点研究 |

主连记录 `splice_offset`、`splice_ratio` 列，可逆。

### 3.4 主连回测的限制

主连价格用于**信号生成**，但下单与持仓必须落到**具体合约**（如 `RB2412.SHF`）。映射规则：

- 策略输出 `OrderIntent(symbol='RB.SHF')` → 执行引擎查 T 日主连映射 → 实际下单到当日实际主力 `RB2412.SHF`。
- 跨换月持仓的策略需在 `on_session_open` 处理换月：策略可选择**自动 roll**（平旧 + 开新，引擎提供 `ctx.roll_position(symbol)` 工具）或**保留旧合约**直至接近交割。

## 4. 期权数据质量

- **远月低成交**：`volume < 10` 的远月期权，执行引擎默认不允许成交（可配 `min_bar_volume`）。
- **隐含波动率回填**：bar 表不存 IV；由 `analytics/option.py` 在加载后按 BSM/Black-76 求解并缓存到 `IVStore`。
- **到期日处理**：到期日 15:00 起触发 `on_option_expire(strategy, symbol)`；策略未平仓时由账户层自动行权（实值）或作废（虚值）。详见 `31-account-margin.md` §5.

## 5. 数据质量校验流水线

回测启动前，`DataQualityChecker.run(bars, instruments)` 输出报告：

```text
[OK]   schema:           列与类型符合规范
[OK]   timezone:         全部 Asia/Shanghai aware
[WARN] missing_bars:     2,310 (0.03%)  — 已自动补齐
[WARN] outliers:         12             — 已剔除
[ERR]  duplicate_keys:   3              — 阻塞回测
[OK]   adj_factor_join:  100% symbol 命中
[OK]   continuous_chain: 无空隙
```

报告写入 `runs/{run_id}/data_quality.json`，作为复跑必检项（见 `51-config-versioning.md`）。

## 6. 已知踩坑（"防再犯"清单）

| 坑 | 现象 | 防范 |
| --- | --- | --- |
| 用前复权价做账户估值 | 历史 PnL 偏小 / 偏大 | 账户层强制 `adj_policy="none"` |
| 主连数据用于实际下单 | 下不到合约 | 引擎在下单前 `resolve_actual_contract(symbol, dt)` |
| 涨停板买入即成交 | 回测虚高 | `30-execution-engine.md` §3.4 涨停成交概率为 0 |
| 跨夜盘日期切割 | 夜盘 22:00 被算到次日 | 全部 timestamptz + Asia/Shanghai；详见 `12-calendar-tradability.md` |
| 配股忽略 | 现金/持仓偏差 | `on_corp_action` 默认放弃，并记录 `corp_action_skipped` 事件 |
| 期权到期未处理 | 持仓"凭空消失"或"凭空多现金" | 到期日由账户层显式 settle |
