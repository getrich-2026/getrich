# 银河 AmazingData (yinhe)

## SDK
- 包名 `AmazingData`（专用 wheel，非 PyPI，需凭证）。
- 登录：`ad.login(username, password, host, port)`。
- 封装：`raw/yinhe/client.py::AmazingDataClient`（实现 `YinheClient` 协议）。

## 真实调用
| 用途 | 调用 |
|---|---|
| 交易日历 | `ad.BaseData().get_calendar(market="SH")` → list[int8] |
| 代码表 | `ad.BaseData().get_code_list(security_type=...)` → list[str] |
| 复权因子 | `ad.BaseData().get_backward_factor(codes, is_local=False)` → DataFrame |
| K线 | `ad.MarketData(calendar).query_kline(codes, begin_date, end_date, period=<int>)` → {code: DataFrame} |

## security_type
- 股票 `EXTRA_STOCK_A_SH_SZ`、ETF `EXTRA_ETF`、指数 `EXTRA_IDNEX_A_SH_SZ`（SDK 原始拼写）。

## 代码形态
`600000.SH` / `000001.SZ`，后缀 SH→XSHG, SZ→XSHE。

## 数据集 → 目标表
calendar → `meta.trading_calendar`；hist_code_list → `meta.instruments`/`meta.symbol_map`；
kline_day → `market.<asset>_bar_1d`；kline_min1 → `market.<asset>_bar_1m`。

## 坑
- int8 日期，需转换。
- query_kline 返回的 DataFrame 列依赖 SDK，ingest transform 用兜底取列。
