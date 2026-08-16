# 华泰 INSIGHT (insight)

## SDK
- 包名 `insight_python`（专用 wheel，需凭证）。
- 登录：`login(market_service(), user, password)`。
- 封装：`raw/insight/client.py::InsightApiClient`（实现 `InsightClient` 协议）。

## 真实调用
| 用途 | 调用 |
|---|---|
| 基础信息 | `get_all_basic_info(security_type=..., exchange=[...])` → DataFrame（含 htsc_code, security_name） |
| 交易日 | `get_trading_days(exchange=..., trading_day=[start_ts, end_ts])` → DataFrame（TradingDate, IfTradingDay） |
| K线 | `get_kline(htsc_code=..., time=[start_ts, end_ts], frequency="daily", fq="none")` → DataFrame |

## 代码形态
`htsc_code` 形如 `600000.SH` / `000001.SZ`，与银河同构。

## 时间
INSIGHT 时间参数为**毫秒时间戳**；raw 层 `_ts()` 由 int8 日期转换。K线时间列 `time`。

## 字段映射（→ canonical）
`time`→dt/trading_day；`value`→amount；`htsc_code`→symbol。

## 实时
INSIGHT 支持实时订阅 → `stream/insight`，写 `realtime.tick_buffer`。

## 数据集 → 目标表
basic_info → `meta.instruments`；trading_days → `meta.trading_calendar`；kline_day → `market.<asset>_bar_1d`。
