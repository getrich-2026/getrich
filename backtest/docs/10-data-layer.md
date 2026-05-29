# 10. 数据层

> 行情访问的唯一入口。所有上层模块（策略、执行、归因、因子）只通过本层定义的 `BarLoader` / `Universe` 协议拿数据，不直连数据库。
>
> **存储说明**：行情数据统一落 **PostgreSQL** 的 `getrich` 库（OHLCV、Tick、因子等过去由 ClickHouse 承担的角色已收回 PgSQL），通过 `psycopg3` 异步连接池读取，转 Polars 长表进入回测引擎。DuckDB 仍可作为本回测进程内的临时分析层（详见 §9）。`BarLoader` 为协议，未来若引入其它后端（Parquet 仓、DuckDB 文件）只需新增实现类，上层契约不变。

## 1. Polars 长表 Schema

所有 OHLCV 行情统一为**长表 (long format)**，一行一个 `(dt, symbol)` 组合。

### 1.1 Bar 表（核心）

| 列 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `dt` | `Datetime("ms", "Asia/Shanghai")` | 是 | bar 起始时间（**左闭右开**）。1m 表示该分钟开始时刻；1d 表示交易日 0 点 |
| `symbol` | `Categorical` | 是 | 合约/标的代码，详见 §2 |
| `asset_class` | `Categorical` | 是 | `equity_a`/`equity_option_a`/`commodity_future`/`index_future`/`commodity_future_option`/`index_future_option` |
| `exchange` | `Categorical` | 是 | `SSE`/`SZSE`/`BSE`/`CFFEX`/`SHFE`/`DCE`/`CZCE`/`INE`/`GFEX` |
| `freq` | `Categorical` | 是 | `1m` / `1d`（其余频率扩展位） |
| `open` | `Float64` | 是 | 开盘价（已按 `adj_policy` 调整） |
| `high` | `Float64` | 是 | 最高价 |
| `low` | `Float64` | 是 | 最低价 |
| `close` | `Float64` | 是 | 收盘价 |
| `volume` | `Float64` | 是 | 成交量（股 / 张 / 手；按 §2.4 单位规范） |
| `amount` | `Float64` | 是 | 成交额（元） |
| `vwap` | `Float64` | 否 | 区间 VWAP；优先使用 `amount / volume` 计算并回填 |
| `oi` | `Float64` | 否 | 期末未平仓量；现货为 null |
| `settlement` | `Float64` | 否 | 期货当日结算价（仅日频；分钟级为 null） |
| `adj_factor` | `Float64` | 否 | A 股复权因子（详见 `11-data-quality.md` §2） |
| `limit_up` | `Float64` | 否 | 当日涨停价（A 股、A 股期权） |
| `limit_down` | `Float64` | 否 | 当日跌停价 |
| `is_suspended` | `Boolean` | 否 | 当日停牌标志（默认 false） |
| `is_st` | `Boolean` | 否 | A 股 ST/*ST 状态 |

> **左闭右开惯例**：`dt=09:30:00` 的 1m bar 覆盖 `[09:30:00, 09:31:00)`。

### 1.2 元数据表

为避免在 bar 表里重复期权/期货静态属性，单独维护 `instruments` 元数据表。

`instruments_equity`

| 列 | 类型 |
| --- | --- |
| `symbol` | `Utf8` |
| `name` | `Utf8` |
| `exchange` | `Categorical` |
| `list_date` | `Date` |
| `delist_date` | `Date`（null=在市） |
| `lot_size` | `Int64`（A 股一手 100） |
| `industry_l1`, `industry_l2`, `industry_l3` | `Utf8` |
| `is_index_component` | `Struct{csi300:Bool, csi500:Bool, csi1000:Bool, ...}` |

`instruments_future`

| 列 | 类型 |
| --- | --- |
| `symbol` | `Utf8`（如 `IF2412.CFE`） |
| `product` | `Utf8`（`IF`/`RB`/...） |
| `exchange` | `Categorical` |
| `multiplier` | `Float64`（合约乘数） |
| `tick_size` | `Float64`（最小变动价位） |
| `tick_value` | `Float64`（每跳点价值=tick × multiplier） |
| `margin_ratio_long` | `Float64` |
| `margin_ratio_short` | `Float64` |
| `list_date` | `Date` |
| `last_trade_date` | `Date` |
| `delivery_date` | `Date` |
| `night_session` | `Boolean` |

`instruments_option`

| 列 | 类型 |
| --- | --- |
| `symbol` | `Utf8`（如 `510050C2412M03000.SH`） |
| `underlying` | `Utf8` |
| `strike` | `Float64` |
| `expiry` | `Date` |
| `option_type` | `Enum{C,P}` |
| `exercise_style` | `Enum{E,A}` |
| `multiplier` | `Float64` |
| `tick_size` | `Float64` |
| `list_date` | `Date` |

### 1.3 时区与精度

- 所有 `dt` 列必须 **aware**，时区 `Asia/Shanghai`。
- 由 PgSQL 读出的 `timestamptz` 在 Polars 端用 `pl.Datetime("ms", "Asia/Shanghai")`，从 `timestamp` 无时区列读出时显式 `dt_replace_time_zone("Asia/Shanghai")`。
- `Float64` 用于价格、收益率；现金、保证金、PnL 在账户/分析层用 `Decimal`，**不进入** Polars 行情表（Polars 不原生支持 Decimal 算术）。

### 1.4 单位规范

| 资产 | volume 单位 | amount 单位 |
| --- | --- | --- |
| A 股现货 | 股 | 元 |
| A 股期权 | 张 | 元 |
| 商品期货 | 手 | 元（= 收盘价 × 乘数 × 手数 的合计） |
| 股指期货 | 手 | 元 |
| 期货期权 | 手 | 元 |

`vwap = amount / volume`（按上述单位自动得出每股/每张/每手平均价）。

## 2. 品种与代码规范

`symbol` 是跨模块的唯一标识，遵循下表：

| 资产 | 代码示例 | 说明 |
| --- | --- | --- |
| A 股现货 | `600519.SH`, `000001.SZ`, `301001.BJ` | `.{交易所后缀}` |
| A 股 ETF 期权 | `510050C2412M03000.SH` | 标准期权代码 |
| A 股个股期权 | `90000123.SH`（沪市），`90000456.SZ` | 8 位数字 |
| 商品期货 | `RB2412.SHF`, `M2501.DCE`, `CF2503.CZC`, `SC2410.INE`, `SI2412.GFE` | `产品+合约月` + `.交易所` |
| 股指期货 | `IF2412.CFE`, `IH2412.CFE`, `IC2412.CFE`, `IM2412.CFE` | |
| 商品期货期权 | `RB2412C3500.SHF`, `M2501P3000.DCE` | 期货代码 + `C/P` + 行权价 |
| 股指期货期权 | `IO2412C4000.CFE`, `HO2412P2400.CFE`, `MO2412C6000.CFE` | |
| 期货主连 | `RB.SHF`, `IF.CFE` | 不带月份，行情来自连续合约（见 `11-data-quality.md` §3） |

> 交易所后缀：`SH`/`SZ`/`BJ`/`CFE`/`SHF`/`DCE`/`CZC`/`INE`/`GFE`。

## 3. PgSQL 表设计建议

按"分类 + 频率"分表，避免单表过大：

```text
md_bars_equity_1m
md_bars_equity_1d
md_bars_future_1m
md_bars_future_1d
md_bars_option_1m
md_bars_option_1d
```

建议在 PgSQL 端：
- 分区：按 `(asset_class, year_month)` 范围分区。
- 索引：`(symbol, dt)` 主键，`(dt, symbol)` 辅助索引以支持横截面切片。
- timezone：连接初始化 `SET timezone='Asia/Shanghai'`（与平台 `pool.py` 一致）。

## 4. 加载接口（BarLoader）

```python
from typing import Protocol, Sequence
from datetime import datetime
import polars as pl

class BarLoader(Protocol):
    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = "1d",
        asset_class: str | None = None,
        columns: Sequence[str] | None = None,
        adj_policy: str = "pre",        # "none" / "pre" / "post"
    ) -> pl.DataFrame:
        """返回标准长表。symbols=None 表示按 asset_class 全量返回。"""
        ...

    def load_instruments(self, asset_class: str) -> pl.DataFrame: ...
    def load_corp_actions(self, symbols: Sequence[str]) -> pl.DataFrame: ...
    def load_calendar(self, exchange: str, start, end) -> pl.DataFrame: ...
```

具体的 PgSQL 实现 `PgBarLoader` 在 `data/loader.py`，构造时接受连接池：

```python
loader = PgBarLoader(pool=get_pg_pool())
bars = loader.load_bars(
    symbols=["600519.SH", "000001.SZ"],
    start=datetime(2023, 1, 1, tzinfo=SHA),
    end=datetime(2024, 12, 31, 15, 0, tzinfo=SHA),
    freq="1m",
    adj_policy="pre",
)
```

### 4.1 流式加载

对大区间分钟数据，提供 `iter_bars(...)` 生成器，按月切片返回 Polars DataFrame，控制内存峰值：

```python
for chunk in loader.iter_bars(symbols, start, end, freq="1m", chunk="month"):
    process(chunk)
```

### 4.2 强类型校验

加载结束后调用 `validate_bar_schema(df)`，校验列名、类型、时区、`dt` 单调、(`dt`,`symbol`) 唯一；任何校验失败抛 `BarSchemaError`。

## 5. 多频率与对齐

- **1m 与 1d 不可混读**：策略需要日频特征时，用 `loader.load_bars(freq='1d', ...)` 单独加载，不可在 1m 表上手动 resample（避免与官方收盘价、结算价口径差异）。
- **跨品种对齐**：见 `12-calendar-tradability.md`——A 股与商品期货交易段不同，跨品种回测时由 `Tradability` 决定每根 bar 哪些品种可下单/估值。

## 6. 与 Universe 的关系

`Universe` 决定回测看哪些 symbol，定义在策略/组合层（见 `21-portfolio-construction.md`）。`BarLoader` 不感知 `Universe`；`Backtest` 在初始化时把 `Universe.resolve(t)` 的结果传给 `BarLoader.load_bars`。

## 7. 最小示例

```python
from getrich_backtest.data import PgBarLoader, AssetClass, get_sha_tz
from datetime import datetime

SHA = get_sha_tz()
loader = PgBarLoader.from_env()  # 从环境变量读连接

bars = loader.load_bars(
    symbols=None,
    asset_class=AssetClass.COMMODITY_FUTURE,
    start=datetime(2024, 1, 1, tzinfo=SHA),
    end=datetime(2024, 6, 30, 15, 0, tzinfo=SHA),
    freq="1m",
)

print(bars.schema)
# {'dt': Datetime(time_unit='ms', time_zone='Asia/Shanghai'),
#  'symbol': Categorical, 'asset_class': Categorical, ...}

# 横截面切片
snapshot = bars.filter(pl.col("dt") == datetime(2024, 3, 15, 10, 30, tzinfo=SHA))
```

## 8. 已知限制

- 1m bar 不覆盖**集合竞价**与**收盘集中竞价**的分笔细节；需要竞价层逻辑的策略请扩展 `BarLoader` 加载 `auction` 表。
- 期权 Greeks 不由本层提供，由 `analytics/factor.py` 或外部因子库计算，按需 join 入策略上下文。
- 主连合约的"价差跳变"由 `ContinuousContract` 处理（详见 `11-data-quality.md` §3），`BarLoader` 返回的主连数据是**已处理**过的连续序列。
