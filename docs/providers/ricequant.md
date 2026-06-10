# 米筐 rqdatac (ricequant)

## SDK
- 包名 `rqdatac`（需 license 或账号）。
- 初始化：`rqdatac.init("license", key)` 或 `rqdatac.init(user, password)`。
- 封装：`raw/ricequant/client.py::RqdatacClient`（实现 `RicequantClient` 协议）。

## 真实调用
| 用途 | 调用 |
|---|---|
| 标的 | `all_instruments(type="CS"/"ETF"/"Index"/..., market="cn")` → DataFrame |
| 交易日 | `get_trading_dates(start, end, market="cn")` → list[date] |
| 行情 | `get_price(symbols, start, end, frequency="1d", adjust_type="none", market="cn")` → DataFrame |

## type 映射
stock→CS, index→Index, etf→ETF, future→Future, option→Option。

## 代码形态
`order_book_id` 形如 `600000.XSHG` / `000001.XSHE`，后缀已是 canonical exchange。

## 字段映射（→ canonical）
`order_book_id`→symbol；`date`→dt/trading_day；`total_turnover`→amount；
`prev_close`→pre_close；`settlement`→settle；`prev_settlement`→pre_settle。

## 数据集 → 目标表
instruments → `meta.instruments`；bars_1d → `market.<asset>_bar_1d`。
