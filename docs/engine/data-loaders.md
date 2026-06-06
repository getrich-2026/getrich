# 数据加载器

`BarLoader` 是引擎与数据源之间的**协议层**。所有 `Strategy` 只与 `BarLoader` 接口交互，不感知后端是 PG、DuckDB 还是 DataFrame。

---

## 1. BarLoader 协议

```python
class BarLoader(Protocol):
    """6 个方法，所有 loader 必须实现。"""

    def load_calendar(
        self, start: date, end: date, exchange: Exchange | None = None
    ) -> pl.DataFrame:
        """加载交易日历。返回 [date, is_trading]"""

    def load_instruments(
        self, as_of: date | None = None
    ) -> pl.DataFrame:
        """加载标的元信息。返回 [symbol, asset_class, exchange, multiplier, margin_ratio, lot_size, ...]"""

    def load_corp_actions(
        self, symbols: list[str], start: date, end: date
    ) -> pl.DataFrame:
        """加载公司行为（除权除息）。返回 [symbol, dt, action_type, amount, split_ratio, bonus_ratio, dividend_tax_rate]"""

    def load_factors(
        self, names: list[str], symbols: list[str], start: date, end: date
    ) -> pl.DataFrame:
        """加载因子值。返回 [dt, symbol, factor_name, value]"""

    def load_adj_factors(
        self, symbols: list[str], start: date, end: date
    ) -> pl.DataFrame:
        """加载复权因子。返回 [dt, symbol, adj_factor]"""

    def load_bars(
        self, symbols: list[str], start: date, end: date, freq: str
    ) -> pl.DataFrame:
        """加载 K 线。返回 [dt, symbol, open, high, low, close, volume, ...]"""
```

> 详见 [API 参考](api-reference.md#barloader)。

---

## 2. DataFrameBarLoader（内存版）

适用于单元测试、小数据集、原型验证。

```python
from getrich_backtest import DataFrameBarLoader
import polars as pl

bars = pl.DataFrame({
    "dt": [...],
    "symbol": [...],
    "open": [...], "high": [...], "low": [...], "close": [...],
    "volume": [...],
})

loader = DataFrameBarLoader(
    bars=bars,
    instruments=pl.DataFrame({
        "symbol": [...], "asset_class": [...], "multiplier": [...],
        "margin_ratio": [...], "lot_size": [...],
    }),
    calendar=pl.DataFrame({"date": [...], "is_trading": [...]}),
)
```

**特点**：

- 完全在内存中，零外部依赖
- 自动验证 schema（缺失列会抛 `BarSchemaError`）
- 适合 pytest fixture

---

## 3. PgBarLoader（生产版）

从 PostgreSQL 加载海量数据。**推荐生产环境使用**。

```python
from getrich.libs.postgres.pool import pg_pool
from getrich_backtest import PgBarLoader

# 异步初始化（应用启动时）
await pg_pool.init()

# 构造 loader
loader = PgBarLoader()

# 一次性预热（可选，加速首次查询）
await loader.warmup_cache(
    symbols=["BTCUSDT", "ETHUSDT"],
    start=date(2024, 1, 1),
    end=date(2024, 12, 31),
    freq="1d",
)
```

**依赖的数据库对象**：

| 对象 | 用途 | 命名约定 |
|---|---|---|
| 表 `md_bars_1d` | 日线 K 线 | `(dt, symbol, open, high, low, close, volume, ...)` |
| 表 `md_bars_1m` | 1 分钟线 | 同上 |
| 表 `md_instruments` | 标的信息 | `(symbol, asset_class, multiplier, margin_ratio, lot_size)` |
| 表 `md_calendar` | 交易日历 | `(date, is_trading, exchange)` |
| 表 `md_corp_actions` | 公司行为 | `(symbol, dt, action_type, ...)` |
| 表 `md_factors` | 因子值 | `(dt, symbol, factor_name, value)` |
| 表 `md_adj_factors` | 复权因子 | `(dt, symbol, adj_factor)` |

> **CLAUDE.md §2 铁律**：所有业务表放在 `frontend` schema 下；连接池初始化时强制 `SET search_path='frontend'`。表名/列名规范化详见 [数据库 Schema](../reference/database-schema.md)。

---

## 4. DuckDBBarLoader（分析版）

从 DuckDB 加载数据（通常是 Parquet 文件）。适合：

- 临时分析（`:memory:` 模式）
- 离线研究（`database='/path/to/local.duckdb'`）
- 一致性回测复现

```python
from getrich.libs.quant_duckdb import DuckDB
from getrich_backtest import DuckDBBarLoader

duckdb = DuckDB(database=":memory:")
loader = DuckDBBarLoader(duckdb)

# 加载预注册的 Parquet（必须在外部先 register）
duckdb.register_parquet("bars_1d", "/path/to/bars.parquet")
duckdb.register_df("instruments", instruments_df)
```

**特点**：

- 适合 GB 级别的本地 Parquet 分析
- 支持任意 SQL 查询（`duckdb.execute("SELECT ...")`）
- 列式存储 + 压缩，IO 极快

---

## 5. Polars 长表 schema（必读）

**必读**：所有 K 线 DataFrame 必须符合以下 schema。

### 5.1 必需列

| 列 | dtype | 说明 |
|---|---|---|
| `dt` | `pl.Datetime("ms", "Asia/Shanghai")` | bar 时间戳 |
| `symbol` | `pl.Utf8` | 标的代码 |
| `open` | `pl.Float64` | 开盘价 |
| `high` | `pl.Float64` | 最高价 |
| `low` | `pl.Float64` | 最低价 |
| `close` | `pl.Float64` | 收盘价 |
| `volume` | `pl.Float64` | 成交量 |

### 5.2 可选列

| 列 | dtype | 说明 |
|---|---|---|
| `vwap` | `pl.Float64` | 量加权平均价 |
| `oi` | `pl.Float64` | 持仓量（期货） |
| `amount` | `pl.Float64` | 成交额 |
| `settlement` | `pl.Float64` | 结算价（期货日终） |
| `adj_factor` | `pl.Float64` | 复权因子 |
| `limit_up` | `pl.Float64` | 涨停价 |
| `limit_down` | `pl.Float64` | 跌停价 |
| `is_suspended` | `pl.Boolean` | 是否停牌 |
| `session` | `pl.Utf8` | Session 名称（如 `morning`, `afternoon`, `night`） |
| `asset_class` | `pl.Utf8` | 资产类型（与 `AssetClass` 枚举对应） |
| `exchange` | `pl.Utf8` | 交易所（与 `Exchange` 枚举对应） |

> **CLAUDE.md §3.2 铁律**：列名严格遵循上述英文名，**禁止**任何缩写或变体（如 `vol`、`p`、`c`）。所有列都是 nullable（除 `dt, symbol, OHLCV`），缺失值会触发 `BarSchemaError`。

### 5.3 验证 schema

```python
from getrich_backtest import validate_bar_schema

validate_bar_schema(bars)  # 失败抛 BarSchemaError
```

---

## 6. AdjustmentPolicy（复权策略）

`adj_factor` 决定历史价格的复权方式：

| 策略 | 公式 | 适用场景 |
|---|---|---|
| `pre` | 用 `adj_factor` 调整历史 OHLC | 真实复权（推荐） |
| `post` | 用 1 / `adj_factor` 调整历史 | 不推荐（容易混淆） |
| `none` | 不复权 | 期货 / 数字货币 |

`PgBarLoader.load_bars()` 默认 `pre` 策略；可通过 `adjustment_policy` 参数切换。

---

## 7. iter_bars 流式加载

大数据集（>1M 行）应使用流式接口：

```python
loader = PgBarLoader()

for chunk in loader.iter_bars(
    symbols=["BTCUSDT", "ETHUSDT"],
    start=date(2024, 1, 1),
    end=date(2024, 12, 31),
    freq="1d",
    chunk="month",   # 按月分块
):
    process_chunk(chunk)  # 处理这一块
```

`chunk` 可选 `day` / `week` / `month` / `quarter`。底层用 `_iter_date_chunks` 实现，按时间窗口分块加载。

---

## 8. 扩展自定义 Loader

实现 `BarLoader` 协议即可，零侵入：

```python
import polars as pl
from datetime import date
from getrich_backtest import BarLoader

class CSVBazLoader:
    """从远程 CSV 服务加载（仅示意）。"""

    def load_bars(self, symbols, start, end, freq):
        # 你的实现：HTTP 请求、CSV 解析、Polars 转换
        return pl.DataFrame({...})

    def load_instruments(self, as_of=None):
        return pl.DataFrame({...})

    # ... 其他 5 个方法
```

策略零改动；只需在 `Backtest(bar_loader=CSVBazLoader(...), ...)` 替换。

---

## 9. 常见错误

### 9.1 naive datetime

```python
df = pl.DataFrame({"dt": [datetime(2024, 1, 1)]})  # naive!
validate_bar_schema(df)
# TimezoneError: All datetimes must be Asia/Shanghai-aware.
```

**修复**：

```python
df = pl.DataFrame({"dt": [datetime(2024, 1, 1, tzinfo=get_shanghai_tz())]})
# 或用 Polars：
df = df.with_columns(pl.col("dt").dt.replace_time_zone("Asia/Shanghai"))
```

### 9.2 列名拼错

```python
df = pl.DataFrame({"dt": [...], "symbol": [...], "Open": [...]})  # 大写 O
validate_bar_schema(df)
# BarSchemaError: Missing required column: 'open'
```

**修复**：所有列名小写。

### 9.3 时区漂移

```python
df = df.with_columns(pl.col("dt").dt.convert_time_zone("UTC"))  # 错误！
# 这会把上海时间转成 UTC，dt 字段不再是中国时区
```

**修复**：保持 `Asia/Shanghai` 不变。

### 9.4 dtype 不匹配

```python
df = pl.DataFrame({"dt": [...], "open": pl.Series([1, 2, 3], dtype=pl.Int32), ...})
# BarSchemaError: Column 'open' has dtype Int32, expected Float64
```

**修复**：

```python
df = df.with_columns(pl.col("open").cast(pl.Float64))
```

---

## 下一步

- 写策略：[策略开发](strategies.md)
- 多频率加载：[多频率](multi-frequency.md)
- 完整 API 索引：[API 参考](api-reference.md)
