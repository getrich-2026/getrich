# Tushare Pro (tushare)

## SDK
- 包名 `tushare`（PyPI 可装，需 token）。
- 初始化：`tushare.pro_api(token)`；token 来自环境变量 `TUSHARE_TOKEN`。
- 封装：`raw/tushare/client.py::TushareProClient`（实现 `TushareClient` 协议）。

所有接口形态统一为 `pro.<api_name>(**params)`，因此 client 只暴露
`query(api_name, **params)` 与 `query_all(api_name, **params)`，不逐个接口写方法。

## 两个必须尊重的供应商约束

1. **单次返回行数上限**（多数接口 5000~6000 行）。超限时 Tushare
   **静默截断**——不报错、不返回总数。`query_all` 以「返回行数 < limit」
   为终止条件按 `offset` 翻页。改动这段逻辑前请先看
   `tests/raw/test_tushare_client.py`，尤其是「整页整除时必须多探一次」那条。
2. **调用频次上限**（按积分分级）。由 `RawContext.sleep_between_requests`
   控制，配置在 `providers.tushare.rate_limit`。低积分账号需调大间隔。

## 真实调用
| 用途 | 调用 | raw 数据集 |
|---|---|---|
| 股票标的 | `stock_basic(list_status="L"/"D"/"P")` | instruments/stock |
| 指数标的 | `index_basic(market=...)` | instruments/index |
| 期货合约 | `fut_basic(exchange=..., fut_type=...)` | instruments/future |
| 交易日历 | `trade_cal(exchange="SSE"/"SZSE", start_date, end_date)` | calendar/\<exchange\> |
| 股票日线 | `daily(start_date, end_date)` | daily/\<YYYY-MM\> |
| 复权因子 | `adj_factor(start_date, end_date)` | adj_factor/\<YYYY-MM\> |
| 涨跌停价 | `stk_limit(start_date, end_date)` | stk_limit/\<YYYY-MM\> |
| 停复牌 | `suspend_d(start_date, end_date)` | suspend_d/\<YYYY-MM\> |
| 指数日线 | `index_daily(start_date, end_date)` | index_daily/\<YYYY-MM\> |
| 期货日线 | `fut_daily(start_date, end_date)` | fut_daily/\<YYYY-MM\> |

`stock_basic` 默认只返回上市中(L)的股票；退市(D)与暂停上市(P)必须显式拉取，
否则历史行情会因为找不到标的而整段丢失。

## 落盘布局
逐日数据集按**自然月**分区：`tushare/<dataset>/<YYYY-MM>.parquet`，每个文件含当月全市场记录。
Tushare 这几个接口都是「按日期区间取全市场」的形态（不需要先有代码清单），
按月分区比按 code 分区省调用次数，也便于断点续传。

`update` 模式会补齐缺失月份，并**重抓最新的已有月份**——当月还在长新数据，
已落盘的文件必然不完整。

## 代码形态
`ts_code` 形如 `600000.SH` / `000001.SZ` / `CU2401.SHF`。
canonical：symbol 保留完整原始代码串，exchange 由后缀映射（`ingest/tushare/symbols.py`）。

Tushare 的交易所后缀**与通行简称不一致**，必须显式映射，不能靠字符串截断猜测：

| ts_code 后缀 | canonical | | ts_code 后缀 | canonical |
|---|---|---|---|---|
| SH | XSHG | | CFX | CFFEX |
| SZ | XSHE | | SHF | SHFE |
| BJ | BSE  | | ZCE | CZCE |
| SI | SW   | | GFE | GFEX |
| CSI | CSI | | DCE / INE | 同名 |

## 单位换算（→ canonical）
**逐接口不同，不可套用**：

| 接口 | vol | amount |
|---|---|---|
| `daily` / `index_daily` | 手 → 股（×100） | 千元 → 元（×1000）|
| `fut_daily` | 手（保持） | 万元 → 元（×10000）|

期货的 `vol` / `oi` 保持「手」——折算成基础单位需要合约乘数，
那属于下游的口径，接入层不做猜测。

## 缺失值处理策略
按目标列**是否允许 NULL** 区分，不搞一刀切：

| 字段 | 缺失时 | 理由 |
|---|---|---|
| `adj_factor` | **抛错中断** | 目标表 NOT NULL；用 1 冒充「未知」会让下游前复权价静默算错 |
| `limit_up` / `limit_down` | 警告 + 留 NULL | 目标表允许 NULL；不该为一个盘前辅助字段阻断整批行情入库 |
| `trading_status` | 无 suspend_d 记录即 NORMAL | 有日线说明当日有行情；S=停牌→HALTED，同日又有 R（盘中复牌）以 R 为准 |
| 未登记的 `ts_code` | 警告 + 跳过该行 | `instrument_id` 是外键，写不进去；但必须让丢弃可见 |

`daily` 与 `stk_limit` 各自返回 `pre_close`，容差 0.011 元（一分钱的舍入）。
超出容差说明两者价格基准不一致，此时**丢弃该行的涨跌停价**（置 NULL），
但保留行情本身——只有附加字段不可信，行情是可信的。

## 数据集 → 目标表
| importer | 目标表 |
|---|---|
| instruments | `meta.instruments` |
| symbol_map | `meta.symbol_map` |
| calendar | `meta.trading_calendar` |
| stock_bar_1d | `market.stock_bar_1d` |
| index_bar_1d | `market.index_bar_1d` |
| future_bar_1d | `market.future_bar_1d` |

入库顺序有严格依赖：`instruments` → `symbol_map` → `*_bar_1d`
（bars 需要 symbol_map 解析 `instrument_id`）。可用 `--only reference` /
`--only bars_1d` / `--only all` 走预置组别。

## 归属冲突
遵循「单表单一 provider」。若 `market.stock_bar_1d` 已被 ricequant/yinhe 占用，
Tushare 入库会抛 `OwnershipError`；确需换源时用 `getrich ingest tushare --force-ownership`。

## 接口字段与用法详解
见 [reference/design/tushare/tushare_api_design.md](../../reference/design/tushare/tushare_api_design.md)。
