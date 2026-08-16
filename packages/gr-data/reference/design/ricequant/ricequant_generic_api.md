# RiceQuant RQData 跨品种通用 API 开发文档

> 适用包：`rqdatac`（RQData Python SDK）
> 文档范围：跨品种通用 API（行情、交易日及合约信息）
> 数据来源：官方文档 https://www.ricequant.com/doc/rqdata/python/generic-api （最后更新 2026/5/15）
> 用途：项目开发参考。本文档统一了函数签名、参数表、返回字段表与示例，便于按字段直接对接数据层（PostgreSQL / ClickHouse / DuckDB）。

---

## 目录

- [1. 安装与初始化](#1-安装与初始化)
- [2. 通用约定](#2-通用约定)
  - [2.1 合约代码（order_book_id）格式](#21-合约代码order_book_id格式)
  - [2.2 日期/时间参数格式](#22-日期时间参数格式)
  - [2.3 market 参数](#23-market-参数)
  - [2.4 返回类型说明](#24-返回类型说明)
  - [2.5 合约类型枚举](#25-合约类型枚举)
- [3. 合约与基础信息](#3-合约与基础信息)
  - [all_instruments — 获取所有合约基础信息](#all_instruments--获取所有合约基础信息)
  - [instruments — 获取合约详细信息](#instruments--获取合约详细信息)
  - [id_convert — 交易所代码转换](#id_convert--交易所代码转换)
- [4. 行情数据](#4-行情数据)
  - [get_price — 获取合约行情数据](#get_price--获取合约行情数据)
  - [get_auction_info — 获取股票合约盘后数据](#get_auction_info--获取股票合约盘后数据)
  - [get_open_auction_info — 获取盘前集合竞价数据](#get_open_auction_info--获取盘前集合竞价数据)
  - [get_ticks — 获取日内 tick 数据（试用版）](#get_ticks--获取日内-tick-数据试用版)
  - [get_live_ticks — 获取日内 tick 数据（支持日内时间切割）](#get_live_ticks--获取日内-tick-数据支持日内时间切割)
  - [current_minute — 获取最近的分钟线数据](#current_minute--获取最近的分钟线数据)
  - [current_snapshot — 获取当前行情快照](#current_snapshot--获取当前行情快照)
  - [get_price_change_rate — 获取历史涨跌幅](#get_price_change_rate--获取历史涨跌幅)
  - [get_live_minute_price_change_rate — 获取当日分钟累计收益率](#get_live_minute_price_change_rate--获取当日分钟累计收益率)
  - [get_vwap — 获取日/分钟级别 vwap 数据](#get_vwap--获取日分钟级别-vwap-数据)
- [5. 交易日历](#5-交易日历)
  - [get_trading_dates — 获取交易日列表](#get_trading_dates--获取交易日列表)
  - [get_previous_trading_date — 获取历史某个交易日](#get_previous_trading_date--获取历史某个交易日)
  - [get_next_trading_date — 获取未来某个交易日](#get_next_trading_date--获取未来某个交易日)
  - [get_latest_trading_date — 获取当前最近一个交易日](#get_latest_trading_date--获取当前最近一个交易日)
  - [get_future_latest_trading_date — 获取当前最近一个期货交易日](#get_future_latest_trading_date--获取当前最近一个期货交易日)
  - [get_trading_hours — 获取合约连续竞价时间段（即将退役）](#get_trading_hours--获取合约连续竞价时间段即将退役)
  - [get_trading_periods — 获取合约连续竞价时间段（新）](#get_trading_periods--获取合约连续竞价时间段新)
- [6. 其他通用数据](#6-其他通用数据)
  - [get_yield_curve — 获取收益率曲线](#get_yield_curve--获取收益率曲线)
- [7. 实时行情推送](#7-实时行情推送)
  - [LiveMarketDataClient — websocket 实时行情推送](#livemarketdataclient--websocket-实时行情推送)

---

## 1. 安装与初始化

### 安装

Python 环境推荐使用 `uv` 管理。

```sh
# 传统方式（清华镜像）
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple rqsdk

# uv 方式
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple rqsdk
```

### 初始化

`rqdatac` 在任何数据查询前必须先 `init`。本项目使用 **L 类 license**（`tcp://` 长连接方式）。

```python
import rqdatac as rq


def init_rq() -> None:
    """初始化 RiceQuant 连接（L license，tcp 长连接）。"""
    rq.init(
        "tcp://license:"
        "iJTkO29NlrZ23X6M5w29Gh_4gShTv46OvOdm9EFZQfKnMg58DCKQBnSV0eay4MoG0ZhzhX_LTms"
        "00WMswme83iOk4ag7Z0OzToI04B67QbOWpicDqD7qxcd7TmK6bAKCTHBz-6wuGI7Zdrp9Z9Iop5BSH"
        "GqYvAm-nXJ-SsCHfoA=dcrc05HTqctrrjbxZjLDlYqv08eY68tPZGYfO_3PosCUVmbfw4WbyLzS6n9BG5"
        "EbP4ZCZ5r89rHrOHYfxY5fL5zOA3SfxO7oDdd3mHhgwPIlGNOKGkQvJhx637sQ2697R-qZThciVWKVD01dD"
        "70rCBuhHAIit26fGOhluTipHGQ=@rqdatad-pro.ricequant.com:16011"
    )
```

> 也可使用 `rq.init('license', '<key>')` 形式（实时推送 `LiveMarketDataClient` 用 `rqdatac.init(username="license", password="<key>")`）。两种 license 的初始化方式本质一致。
> **安全提示**：license key 等同于账号凭证，请通过环境变量或密钥管理注入，不要硬编码进入版本库。

---

## 2. 通用约定

### 2.1 合约代码（order_book_id）格式

| 品种 | 后缀/规则 | 示例 |
| --- | --- | --- |
| 股票 / ETF / 指数（上证） | `.XSHG` | `600000.XSHG`、`000300.XSHG` |
| 股票 / ETF / 指数（深证） | `.XSHE` | `000001.XSHE` |
| 港股 | `.XHKG` | `00700.XHKG` |
| 期货合约 | 交易所代码（郑商所数字补齐，如 `ZC609`→`ZC1609`） | `IF1608`、`RB2010` |
| 期货主力连续合约 | `品种+88` | `IF88` |
| 期货指数连续合约 | `品种+99` | `IF99` |
| ETF 期权 | 数字代码 | `10000615` |
| 商品期权 | 品种+到期+方向+行权价 | `ZN2105C20000` |
| 可转债 | `.XSHE` / `.XSHG` | `128143.XSHE` |
| 回购（Repo） | `.XSHE` / `.XSHG` | `131801.XSHE` |

> 不支持跨国家市场混合调用：传入的 `order_book_id` 列表必须属于同一国家市场。

### 2.2 日期/时间参数格式

绝大多数日期参数同时接受以下类型：`int`（如 `20240105`）、`str`（如 `'2024-01-05'` 或 `'20240105'`）、`datetime.date`、`datetime.datetime`、`pandas.Timestamp`。

`time_slice`、`start_dt`、`end_dt` 等日内切片参数可接受 `str`（`'09:30'`）或 `datetime.time`。

### 2.3 market 参数

`market='cn'`（默认，中国内地市场）；部分接口支持 `market='hk'`（香港市场）。各接口对 `hk` 的支持情况见各自参数表。

### 2.4 返回类型说明

- 多数行情/批量接口返回 **pandas.DataFrame**，通常以 `order_book_id` + `datetime`/`date` 为多级索引（MultiIndex）。
- `current_snapshot` 返回 **Tick 对象**（或 Tick list）。
- `instruments` 返回 **Instrument 对象**（或 list）。
- 交易日相关接口返回 `datetime.date` 或其 list。
- `get_vwap` 返回 **pandas.Series**。
- 部分接口提供 `expect_df` 参数：`True`（默认）返回 DataFrame，`False` 返回 SDK 原生数据结构。

### 2.5 合约类型枚举

`all_instruments(type=...)` 与 `Instrument.type` 使用的合约类型：

| 合约类型 | 说明 |
| --- | --- |
| `CS` | Common Stock，股票 |
| `ETF` | Exchange Traded Fund，交易所交易基金 |
| `LOF` | Listed Open-Ended Fund，上市型开放式基金（分级基金已并入） |
| `INDX` | Index，指数 |
| `Future` | 期货，含股指、国债、商品期货 |
| `Spot` | 现货，目前为上海黄金交易所现货合约 |
| `Option` | 期权，含国内已上市全部期权合约 |
| `Convertible` | 沪深两市场内有交易的可转债 |
| `Repo` | 沪深两市交易所回购合约 |
| `REITs` | 不动产投资信托基金 |
| `FUND` | 除 ETF、LOF、REITs 之外的基金 |

---

## 3. 合约与基础信息

### all_instruments — 获取所有合约基础信息

```python
all_instruments(type=None, date=None, market='cn')
```

获取指定市场的所有合约基础信息，支持按合约类型和日期筛选。可查询股票、ETF、LOF 等合约类型，也支持按指定日期筛选可交易合约。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | type | str | N | 合约类型，如 `type='CS'` 代表股票。默认全部类型。枚举见 [2.5](#25-合约类型枚举) |
| 2 | date | int/str/date/datetime/Timestamp | N | 指定日期，筛选该日可交易的合约 |
| 3 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`pandas.DataFrame` — 所有合约基础信息，字段含义同 [instruments 返回字段](#instruments--获取合约详细信息)。

**示例**

```python
# 全部合约
all_instruments()
# 全部 LOF 基金
all_instruments(type='LOF')
# 全部期货
all_instruments(type='Future')
# 指定日期可交易的期货
all_instruments(type='Future', date='20160412')
# 全部可转债
all_instruments(type='Convertible')
```

---

### instruments — 获取合约详细信息

```python
instruments(order_book_ids, market='cn')
```

获取一个或多个合约最新的详细信息。返回 Instrument 对象（或 list）。

> 注意：不支持跨国家市场同时调用，传入的 `order_book_id` list 必须属于同一国家市场。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码，单个或列表。中国市场代码须以 `.XSHG`/`.XSHE` 结尾（期货无此要求） |
| 2 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回字段 — 股票 / ETF / 指数 Instrument**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_book_id | str | 证券代码，以 `.XSHG`/`.XSHE`/`.XHKG` 结尾 |
| symbol | str | 证券简称，如 `平安银行` |
| abbrev_symbol | str | 名称缩写（A 股为拼音缩写），如 `PAYH` |
| round_lot | int | 一手对应股数，A 股为 100 |
| sector_code | str | 板块缩写代码（全球通用标准） |
| sector_code_name | str | 本地语言板块名 |
| industry_code | str | 国民经济行业分类代码 |
| industry_name | str | 国民经济行业分类名称 |
| listed_date | str | 上市日期 |
| issue_price | float | 发行价（元） |
| de_listed_date | str | 退市日期 |
| type | str | 合约类型：`CS`/`INDX`/`LOF`/`ETF`/`Future` |
| exchange | str | 交易所：`XSHE` 深交所、`XSHG` 上交所 |
| board_type | str | 板块类别：`MainBoard` 主板、`GEM` 创业板、`SME` 中小板、`KSH` 科创板 |
| status | str | 合约状态：`Active` 正常、`Delisted` 终止上市、`TemporarySuspended` 暂停上市 |
| special_type | str | 特别处理：`Normal`、`ST`、`StarST`、`PT`、`Other` |
| trading_hours | str | 最新连续竞价时间，历史请用 `get_trading_hours` |
| market_tplus | str | 交易制度：`0`=T+0、`1`=T+1，往后顺推 |
| cross_market | str | 沪深港通标识（仅港股）：True/False |
| least_redeem | str | 最低申赎份额（仅 ETF） |
| purchasedate | str | 申购日期 |
| base_date | str | 基日（指数专用） |
| base_point | str | 基点（指数专用） |
| fund_type | str | 基金类型（ETF 专用）：`Bond`/`Stock`/`Hybrid`/`Money`/`ShortBond`/`StockIndex`/`BondIndex`/`Related`/`QDII` |
| latest_size | float | 最新基金规模，单位元（ETF 专用） |

> 已废弃字段：`underlying_order_book_id`、`underlying_name`、`concept_names`（股票/ETF 对象中）。

**返回字段 — 期货 Instrument**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_book_id | str | 期货代码（郑商所数字已补齐）；主力连续 `品种+88`，指数连续 `品种+99` |
| symbol | str | 期货简称，如 `沪深 1005` |
| margin_rate | float | 最低保证金率 |
| round_lot | float | 期货全部为 1.0 |
| listed_date | str | 上市日期（主力/指数连续为 `0000-00-00`） |
| de_listed_date | str | 退市日期 |
| maturity_date | str | 到期日（主力/指数连续为 `0000-00-00`） |
| industry_name | str | 行业分类名称 |
| trading_code | str | 交易代码 |
| market_tplus | str | 交易制度 |
| type | str | `Future` |
| contract_multiplier | float | 合约乘数，如沪深 300 股指期货为 300.0 |
| underlying_order_book_id | str | 合约标的代码（除股指 IH/IF/IC 外多为 `null`） |
| underlying_symbol | str | 合约标的名称，如 `IF1005` 的标的为 `IF` |
| exchange | str | `DCE` 大商所、`SHFE` 上期所、`CFFEX` 中金所、`CZCE` 郑商所、`INE` 上海能源中心 |
| trading_hours | str | 最新连续竞价时间 |
| product | str | `Commodity` 商品、`Index` 股指、`Government` 国债 |
| start_delivery_date | str | 开始交割日 |
| end_delivery_date | str | 结束交割日 |

**返回字段 — 期权 Instrument**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_book_id | str | 合约代码，50ETF 期权为数字代码如 `10000615` |
| symbol | str | 合约简称 |
| round_lot | float | 最小下单手数，期权全部为 1.0 |
| listed_date | str | 上市日期 |
| type | str | `Option` |
| contract_multiplier | float | 合约乘数（50ETF 期权仅存分红调整后最新值，历史见日线） |
| underlying_order_book_id | str | 标的代码 |
| underlying_symbol | str | 所属品种 |
| maturity_date | str | 到期日 |
| exchange | str | `DCE`/`SHFE`/`CFFEX`/`CZCE`/`INE` |
| strike_price | float | 行权价（50ETF 期权仅存分红调整后最新值，历史见日线） |
| option_type | str | `C` 认购、`P` 认沽 |
| exercise_type | str | `E` 欧式、`A` 美式 |
| market_tplus | str | 交易制度 |
| product_name | str | ETF 期权字母简称 |

**返回字段 — 现货 Instrument**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_book_id | str | 合约代码 |
| symbol | str | 合约简称 |
| exchange | str | `SGEX` 上海黄金交易所 |
| listed_date | str | 上市日期 |
| de_listed_date | str | 退市日期 |
| type | str | `Spot` |
| trading_hours | str | 最新连续竞价时间 |
| market_tplus | str | 交易制度 |

**返回字段 — 可转债 Instrument**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| order_book_id | str | 合约代码 |
| symbol | str | 合约简称 |
| exchange | str | `XSHE` 深交所、`XSHG` 上交所 |
| listed_date | str | 上市日期 |
| de_listed_date | str | 退市日期 |
| type | str | `Convertible` |
| market_tplus | str | 交易制度 |

**Instrument 对象方法**

| 方法 | 说明 |
| --- | --- |
| `days_from_listed(date=None)` | 合约已上市天数。`date` 支持 str；首次上市当天为 0；未上市/已退市返回 -1 |
| `days_to_expire(date=None)` | 距到期天数；已退市返回 -1 |
| `tick_size()` | 最小价格变动单位（一跳），如 `instruments('IF1608').tick_size()` 返回 0.2 |

**示例**

```python
instruments('000001.XSHE')                       # 单只股票
instruments(['000001.XSHE', '000024.XSHE'])       # 多只股票
instruments('10000615')                           # 期权
instruments('000001.XSHE').days_from_listed('20160801')   # -> 9252
instruments('IF1608').days_to_expire('20160801')          # -> 18
instruments('ZN2105C20000').days_to_expire('20201225')    # -> 122
```

---

### id_convert — 交易所代码转换

```python
id_convert(order_book_ids, to=None)
```

在交易所/其他平台代码与米筐标准合约代码之间转换。目前支持 A 股、期货、期权。例如可将 `000001.SZ`、`000001SZ`、`SZ000001` 转为 `000001.XSHE`。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码（米筐或交易所或其他平台） |
| 2 | to | str | N | `'normal'`：米筐代码→交易所/其他平台代码；不填：交易所/其他平台代码→米筐代码 |

**返回**：传入单个返回标准化字符串；传入列表返回字符串 list。

**示例**

```python
id_convert('000001.XSHE', to='normal')   # -> '000001.SZ'
id_convert('000935.SH')                  # -> '000935.XSHG'
id_convert(['000001.SZ', '000935.SH'])   # -> ['000001.XSHE', '000935.XSHG']
id_convert('AP810')                      # -> 'AP1810'
id_convert('ZC001.CZCE')                 # -> 'ZC2001'  (CTP 代码)
id_convert('m1901-C-2500')               # -> 'M1901C2500'  (CTP 期权)
id_convert('SR901C4400')                 # -> 'SR1901C4400'
```

---

## 4. 行情数据

### get_price — 获取合约行情数据

```python
get_price(order_book_ids, start_date=None, end_date=None, frequency='1d',
          fields=None, adjust_type='pre', skip_suspended=False,
          expect_df=True, time_slice=None, market='cn')
```

获取指定合约的行情数据，支持周线、日线、分钟线和 tick。覆盖股票、期货、期权、可转债、ETF、常见指数等中国市场合约，以及上金所现货（黄金、铂金、白银）。

> **注意事项**
> 1. 周线仅支持 `'1w'`，依据日线合成（前复权用前复权日线合成，不复权用不复权日线合成）。
> 2. 大量获取分钟/tick 数据时，建议以单只合约为单位、设较长时段以提高效率。
> 3. `time_slice` 是先取 `[start_date, end_date]` 全量再切分，注意流量消耗。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码，单个或列表 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期 |
| 4 | frequency | str | N | 默认 `'1d'`。`1m` 分钟线、`1d` 日线、`1w` 周线；分钟/日线可取其他频率如 `'5m'`、`'15m'`、`'60m'` |
| 5 | fields | str / str list | N | 字段名称 |
| 6 | adjust_type | str | N | 复权方案（仅股票/ETF 的日线和分钟线有效，tick 不复权）。默认 `'pre'`。`none` 不复权、`pre` 前复权、`post` 后复权、`pre_volume`、`post_volume`。`pre`/`post` 的 volume 用拆分因子调整，`pre_volume`/`post_volume` 的 volume 用复权因子调整 |
| 7 | skip_suspended | bool | N | 是否跳过停牌。默认 False（用停牌前数据补齐）；True 跳过停牌期 |
| 8 | expect_df | bool | N | 默认 True 返回 DataFrame；False 返回原生结构（周线需 True） |
| 9 | time_slice | str / datetime.time | N | 日内开始、结束时间段，支持分钟/tick 切分 |
| 10 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回字段 — bar 数据（日线/分钟线/周线）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| open / close / high / low | float | 开 / 收 / 高 / 低 |
| limit_up / limit_down | float | 涨停价 / 跌停价 |
| total_turnover | float | 成交额 |
| volume | float | 成交量 |
| num_trades | int | 成交笔数（仅股票/ETF/LOF/可转债；2021-06-25 起） |
| prev_close | float | 昨收（交易所原始值，复权对该字段无效） |
| settlement | float | 结算价（仅期货期权日线） |
| prev_settlement | float | 昨结算价（仅期货期权日线） |
| open_interest | float | 累计持仓量（期货期权） |
| trading_date | Timestamp | 交易日期（仅期货分钟线，对应夜盘） |
| dominant_id | str | 实际合约 order_book_id（期货 888 主力连续） |
| strike_price | float | 行权价（仅期权日线） |
| contract_multiplier | float | 合约乘数（仅期权日线） |
| iopv | float | 场内基金实时估算净值 |
| day_session_open | float | 日盘开盘价（仅期货期权日线） |

**返回字段 — tick 数据**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| datetime | Timestamp | 交易所时间戳 |
| open / high / low | float | 当日开 / 高 / 低 |
| last | float | 最新价 |
| prev_close | float | 昨收 |
| total_turnover | float | 当天累计成交额 |
| volume | float | 当天累计成交量 |
| num_trades | int | 成交笔数（仅股票/ETF/LOF/可转债） |
| limit_up / limit_down | float | 涨 / 跌停价 |
| open_interest | float | 累计持仓量 |
| a1~a5 / a1_v~a5_v | float | 卖一至五档价 / 量 |
| b1~b5 / b1_v~b5_v | float | 买一至五档价 / 量 |
| change_rate | float | 涨跌幅 |
| trading_date | Timestamp | 交易日期（对应期货夜盘） |
| prev_settlement | float | 昨结算价（仅期货） |
| iopv | float | 场内基金实时估算净值 |

**示例**

```python
import datetime

# 期货分钟线 + 夜盘时间切片
get_price('AG2209', '20220512', '20220513', frequency='1m',
          time_slice=('23:55', '09:05'))

# 股票分钟线 + datetime.time 切片
get_price('000001.XSHE', '20220512', '20220513', frequency='1m',
          time_slice=(datetime.time(10, 0), datetime.time(11, 0)))

# 不复权周线
get_price('000001.XSHE', '2015-04-01', '2015-04-12', frequency='1w', adjust_type='none')

# 分钟线指定字段
get_price('000001.XSHE', '2015-04-01', '2015-04-12', fields='close', frequency='1m')

# 历史 tick（单只 / 多只）
get_price('000001.XSHE', '20240105', '20240105', frequency='tick')
get_price(['000001.XSHE', '000002.XSHE'], '2019-04-01', '2019-04-01', frequency='tick')
get_price('IF1608', '20160801', '20160801', 'tick')      # 期货 tick

# 15 / 60 分钟线
get_price('000001.XSHE', '2015-04-01', '2015-04-01', frequency='15m')
get_price('000300.XSHG', 20240105, 20240108, frequency='60m')

# 期权 / 可转债 / 回购 日线
get_price('10000615', '20161125', '20161130', frequency='1d')
get_price('128143.XSHE', 20240105, 20240105, frequency='1d')
get_price('131801.XSHE', 20190522, 20190522, frequency='1d')
```

---

### get_auction_info — 获取股票合约盘后数据

```python
get_auction_info(order_book_ids, start_date=None, end_date=None,
                 frequency='1d', fields=None, market='cn')
```

获取股票合约盘后固定价格交易数据。支持科创板、创业板等，频率支持日线、分钟线、tick。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码；获取 tick 时只支持单个合约 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期 |
| 4 | frequency | str | N | 默认 `'1d'`，仅支持 `'1d'`/`'1m'`/`'tick'` |
| 5 | fields | str / str list | N | 字段名称 |
| 6 | market | str | N | 默认 `'cn'` |

**返回字段**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| close | float | 收盘价 |
| volume | float | 成交量 |
| total_turnover | float | 成交额 |
| bid_vol | int | 申买入量（tick 专用） |
| ask_vol | int | 申卖出量（tick 专用） |

**示例**

```python
get_auction_info(['688012.XSHG', '688011.XSHG'], '20190722', '20190722', '1d')
get_auction_info('688012.XSHG', '20190722', '20190722', '1m')
get_auction_info('688012.XSHG', '20190722', '20190722', 'tick')
```

---

### get_open_auction_info — 获取盘前集合竞价数据

```python
get_open_auction_info(order_book_ids, start_date=None, end_date=None,
                      fields=None, market='cn')
```

获取盘前集合竞价结束后交易所撮合产生的 level1 快照数据。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期，不指定默认取当天 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期，不指定默认取开始日期当天 |
| 4 | fields | str / str list | N | 字段名称，默认全部 |
| 5 | market | str | N | 默认 `'cn'` |

**返回字段（tick）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| datetime | Timestamp | 时间戳 |
| open / high / low | float | 当日开 / 高 / 低 |
| last | float | 最新价 |
| prev_settlement | float | 昨结算价 |
| volume | float | 成交量 |
| limit_up / limit_down | float | 涨 / 跌停价 |
| open_interest | float | 累计持仓量 |
| a1~a5 / a1_v~a5_v | float | 卖一至五档价 / 量 |
| b1~b5 / b1_v~b5_v | float | 买一至五档价 / 量 |
| change_rate | float | 涨跌幅 |
| trading_date | Timestamp | 交易日期（对应期货夜盘） |
| iopv / prev_iopv | float | 场内基金实时 / 前估算净值 |

**示例**

```python
get_open_auction_info('000001.XSHE', '20190102', '20190105')
get_open_auction_info(['000001.XSHE', '000002.XSHE'], '20190102', '20190105')
```

---

### get_ticks — 获取日内 tick 数据（试用版）

```python
get_ticks(order_book_id, start_date=None, end_date=None, expect_df=True, market='cn')
```

获取当日给定合约的 level1 tick 快照行情，**不支持历史数据**。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_id | str | Y | 合约代码（单个） |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期，仅支持当日 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期，仅支持当日 |
| 4 | expect_df | bool | N | 默认 True 返回 DataFrame；False 返回原生结构 |
| 5 | market | str | N | 默认 `'cn'` |

**返回字段（tick）**：同 [get_price tick 字段](#get_price--获取合约行情数据)，另含 `prev_iopv`（场内基金前估算净值）。

**示例**

```python
df = get_ticks('000001.XSHE')        # 股票当日 tick
get_ticks('10002725', expect_df=False)   # ETF 期权当日 tick，返回原生结构
```

---

### get_live_ticks — 获取日内 tick 数据（支持日内时间切割）

```python
get_live_ticks(order_book_ids, start_dt=None, end_dt=None, fields=None, market='cn')
```

获取当前交易日的 level1 tick 快照行情，**不支持历史数据**。支持股票、期货、期权、ETF、常见指数及上金所现货。

> **注意**：`start_dt` 与 `end_dt` 需同时传入或同时不传。不传时：查询时点在交易日 T 日 19:30 之前返回 T 日 tick，19:30 之后返回 T+1 日 tick。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | start_dt | int/str/date/datetime/Timestamp | N | 开始时间，自然日时间戳，细化到秒 |
| 3 | end_dt | int/str/date/datetime/Timestamp | N | 结束时间，自然日时间戳，细化到秒 |
| 4 | fields | str / str list | N | 字段名称 |
| 5 | market | str | N | 默认 `'cn'` |

**返回字段（tick）**：同 [get_ticks](#get_ticks--获取日内-tick-数据试用版)。

---

### current_minute — 获取最近的分钟线数据

```python
current_minute(order_book_ids, skip_suspended=False, fields=None, market='cn')
```

获取给定合约当日最新的 1 分钟 K 线，不支持历史数据。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | skip_suspended | bool | N | 是否跳过停牌，默认不跳过 |
| 3 | fields | list | N | 返回字段，默认全部 |
| 4 | market | str | N | 默认 `'cn'` |

**返回字段（分钟）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| open / high / low / close | float | 此分钟开 / 高 / 低 / 收 |
| volume | int | 此分钟成交量 |
| total_turnover | float | 此分钟成交额 |
| open_interest | float | 累计持仓量（期货期权） |
| trading_date | int | 交易日期（期货，对应夜盘） |
| iopv | float | 场内基金实时估算净值 |

**示例**

```python
current_minute(['000001.XSHE', '600000.XSHG'])
current_minute(order_book_ids=['A2511', '10009217'])
```

---

### current_snapshot — 获取当前行情快照

```python
current_snapshot(order_book_ids, market='cn')
```

获取合约当前的 level1 行情快照（也支持集合竞价数据）。返回 **Tick 对象**（或 Tick list）。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | market | str | N | 默认 `'cn'`，目前仅支持中国市场 |

**返回 — Tick 对象属性**

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| datetime | Timestamp | 时间戳 |
| order_book_id | str | 合约代码 |
| open / high / low | float | 当日开 / 高 / 低 |
| last | float | 最新价 |
| prev_settlement | float | 昨结算价 |
| prev_close | float | 昨收 |
| volume | float | 成交量 |
| total_turnover | float | 成交额 |
| limit_up / limit_down | float | 涨 / 跌停价 |
| open_interest | float | 累计持仓量 |
| trading_phase_code | str | 停牌标识：`T` 正常、`H` 临时停牌、`P` 全天停牌（目前仅深交所股票） |
| asks / ask_vols | list | 卖出报盘价 / 量，`asks[0]` 为卖一档 |
| bids / bid_vols | list | 买入报盘价 / 量，`bids[0]` 为买一档 |
| iopv / prev_iopv | float | 场内基金实时 / 前估算净值 |
| close | float | 当日收盘价（现货专用，约 15:30 可取，>0 判断是否已有值） |
| settlement | float | 当日结算价（现货专用） |

**示例**

```python
current_snapshot('90000337')                       # 期权
current_snapshot('000001.XSHE')                     # 股票
current_snapshot('RB2010')                          # 期货
current_snapshot(['000001.XSHE', '600000.XSHG'])    # 多个，返回 Tick list
```

---

### get_price_change_rate — 获取历史涨跌幅

```python
get_price_change_rate(order_book_ids, start_date=None, end_date=None,
                      expect_df=True, market='cn')
```

获取历史涨跌幅，目前支持股票、期货、指数、可转债。**涨跌幅基于后复权价格**。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期；不传则默认返回最近三个月 |
| 4 | expect_df | bool | N | 默认 True 返回 DataFrame |
| 5 | market | str | N | 默认 `'cn'` |

**返回**：`pandas.DataFrame`，列为各合约的日度涨跌幅。

**示例**

```python
get_price_change_rate(['000001.XSHE', '000300.XSHG'], '20150801', '20150807')
```

---

### get_live_minute_price_change_rate — 获取当日分钟累计收益率

```python
rqdatac.get_live_minute_price_change_rate(order_book_ids)
```

获取股票和指数的当日分钟累计收益率。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码（股票、指数） |

**返回字段**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| change_rate | float | 当前分钟累计收益率 |

**示例**

```python
rqdatac.get_live_minute_price_change_rate(['000001.XSHE', '600000.XSHG'])
```

---

### get_vwap — 获取日/分钟级别 vwap 数据

```python
rqdatac.get_vwap(order_book_ids, start_date=None, end_date=None, frequency='1d')
```

获取成交量加权平均价格（VWAP），支持历史与实时查询。支持股票、期货、期权、ETF、可转债，日级与分钟级。返回 **pandas.Series**。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / str list | Y | 合约代码 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期 |
| 4 | frequency | str | N | 默认 `'1d'`。`1m` 分钟、`1d` 日；分钟可取其他频率如 `'5m'` |

**返回**：`pandas.Series`（VWAP）。

**示例**

```python
rqdatac.get_vwap('000001.XSHE', 20240101, 20240201)          # 日级
rqdatac.get_vwap('IF2403', 20240201, 20240201, '1m')         # 分钟级
```

---

## 5. 交易日历

### get_trading_dates — 获取交易日列表

```python
get_trading_dates(start_date, end_date, market='cn')
```

获取指定市场在起止日期范围内的交易日列表。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | start_date | int/str/date/datetime/Timestamp | Y | 开始日期 |
| 2 | end_date | int/str/date/datetime/Timestamp | Y | 结束日期 |
| 3 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`datetime.date list`。

**示例**

```python
get_trading_dates(start_date='20160505', end_date='20160505')
# -> [datetime.date(2016, 5, 5)]
```

---

### get_previous_trading_date — 获取历史某个交易日

```python
get_previous_trading_date(date, n=1, market='cn')
```

获取指定日期之前的第 n 个交易日。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | date | int/str/date/datetime/Timestamp | Y | 指定日期 |
| 2 | n | int | N | 往前第 n 个交易日，默认 1（前一交易日） |
| 3 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`datetime.date`。

**示例**

```python
get_previous_trading_date('20160502', n=1)   # -> datetime.date(2016, 4, 29)
```

---

### get_next_trading_date — 获取未来某个交易日

```python
get_next_trading_date(date, n=1, market='cn')
```

获取指定日期之后的第 n 个交易日。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | date | int/str/date/datetime/Timestamp | Y | 指定日期 |
| 2 | n | int | N | 未来第 n 个交易日，默认 1（下一交易日） |
| 3 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`datetime.date`。

**示例**

```python
get_next_trading_date(date='2016-05-01', n=1)   # -> datetime.date(2016, 5, 3)
```

---

### get_latest_trading_date — 获取当前最近一个交易日

```python
get_latest_trading_date(market='cn')
```

获取当前最近一个交易日：当天为交易日则返回当天，为节假日则返回上一个交易日。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`datetime.date`。

**示例**

```python
get_latest_trading_date()   # -> datetime.date(2019, 11, 22)
```

---

### get_future_latest_trading_date — 获取当前最近一个期货交易日

```python
get_future_latest_trading_date(market='cn')
```

获取当前最近一个期货交易日：夜盘集合竞价开始即视为新交易日；当天为节假日则返回下一个交易日。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | market | str | N | 默认 `'cn'` |

**返回**：`datetime.date`。

**示例**

```python
get_future_latest_trading_date()   # -> datetime.date(2023, 6, 21)
```

---

### get_trading_hours — 获取合约连续竞价时间段（即将退役）

```python
get_trading_hours(order_book_id, date=None, expected_fmt='str',
                  frequency='1m', market='cn')
```

获取合约连续竞价交易时间段。返回格式可选 `str`/`time`/`datetime`，频率支持 `1m` 与 `tick`。

> **注意**：该 API 即将退役，建议改用 [get_trading_periods](#get_trading_periods--获取合约连续竞价时间段新)。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_id | str | Y | 合约代码 |
| 2 | date | int/str/date/datetime/Timestamp | N | 指定日期（部分合约当前与历史时间段不同） |
| 3 | expected_fmt | str | N | 返回类型，默认 `'str'`；可选 `'str'`/`'time'`（datetime.time）/`'datetime'`（datetime.datetime） |
| 4 | frequency | str | N | 默认 `'1m'`（米筐分钟线时间段起始）；`'tick'` 返回交易所给出的交易时间 |
| 5 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：字符串（或对应格式）的交易时间。

**示例**

```python
get_trading_hours('000001.XSHE')                              # '09:31-11:30,13:01-15:00'
get_trading_hours('000001.XSHE', expected_fmt='time')         # datetime.time 列表
get_trading_hours('A2511', date=20251113, expected_fmt='datetime')   # datetime.datetime 列表（含夜盘）
```

---

### get_trading_periods — 获取合约连续竞价时间段（新）

```python
get_trading_periods(order_book_ids, start_date=None, end_date=None,
                    frequency='1m', market='cn')
```

获取合约连续竞价交易时间段，支持按时间范围查询一个或多个合约。频率支持 `1m` 与 `tick`。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | order_book_ids | str / list | Y | 合约代码，单个或多个 |
| 2 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 3 | end_date | int/str/date/datetime/Timestamp | N | 结束日期；不指定 start_date 则默认返回最近三个月 |
| 4 | frequency | str | N | 默认 `'1m'`；`'tick'` 返回交易所给出的交易时间 |
| 5 | market | str | N | `'cn'`（默认）/ `'hk'` |

**返回**：`pandas.DataFrame`（索引 `order_book_id` + `date`，列 `trading_hours`）。

**示例**

```python
get_trading_periods('000001.XSHE', 20250901, 20250910, '1m')
get_trading_periods(['000001.XSHE', 'IF2512'], 20250901, 20250902, '1m')
```

---

## 6. 其他通用数据

### get_yield_curve — 获取收益率曲线

```python
get_yield_curve(start_date=None, end_date=None, tenor=None, market='cn')
```

获取一段时间内的收益率曲线，目前仅支持中国市场。数据为 2002 年至今的中债国债收益率曲线。

**参数**

| 序号 | 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | start_date | int/str/date/datetime/Timestamp | N | 开始日期 |
| 2 | end_date | int/str/date/datetime/Timestamp | N | 结束日期；不传 start_date 则默认返回最近三个月 |
| 3 | tenor | str | N | 标准期限，默认全部。`'0S'` 隔夜、`'1M'` 1 个月、`'1Y'` 1 年等 |
| 4 | market | str | N | 默认 `'cn'`，目前仅支持中国市场 |

**返回**：`pandas.DataFrame` — 查询时段内无风险收益率曲线（列为各标准期限 `0S`/`1M`/`2M`/`3M`/`6M`/`9M`/`1Y`/`2Y`…`10Y`）。

**示例**

```python
get_yield_curve(start_date='20130104', end_date='20140104')
```

---

## 7. 实时行情推送

考虑到主动轮询 API 获取实时行情不便，米筐提供 Python SDK 与 websocket 接口用于实时行情推送，**语言中性**，可用任意语言接入。

**实时数据资产类别**：中国 A 股（主板、创业板、科创板）、场内基金（ETF、LOF）、可转债、中国期货（股指、国债、商品）、中国期权（ETF、股指、商品）、国债逆回购、现货（黄金、铂金、白银等）。

**实时数据频率**：Level1 tick（五档深度行情）；以及 1/3/5/15/30/60 等任意频率的分钟行情合成（30、60 分钟线按时间切片，例如 10:15–10:30 休市时 60 分钟线会出现 10:15 的时间戳）。

**适用场景与优点**：驱动实盘/模拟交易、作为已有实时行情的备份；相较 RQData 拉取型 API 推送更及时、效率更高、可靠性高。

### LiveMarketDataClient — websocket 实时行情推送

通过 `from rqdatac import LiveMarketDataClient` 引入，提供阻塞与非阻塞两种调用方式。

**订阅频道命名规则**

| 频道前缀 | 含义 | 示例 |
| --- | --- | --- |
| `tick_` | tick 行情 | `tick_000001.XSHE` |
| `bar_` | 1 分钟行情 | `bar_000001.XSHE` |
| `bar_..._Nm` | N 分钟行情（改后缀即可） | `bar_000001.XSHE_3m` |

**示例**

```python
import rqdatac
from rqdatac import LiveMarketDataClient

rqdatac.init(username="license", password="邮件中一大串 license 的 key")
client = LiveMarketDataClient()

# 订阅
client.subscribe('tick_000001.XSHE')                       # 单支 tick
client.subscribe('bar_000001.XSHE')                        # 1 分钟行情
client.subscribe(['tick_000001.XSHE', 'tick_000002.XSHE']) # 多支 tick
# client.subscribe('bar_000001.XSHE_3m')                   # 3 分钟行情

# 取消订阅
client.unsubscribe('tick_000002.XSHE')

# 监听行情（阻塞方式）
for market in client.listen():
    print(market)
```

---

## 附录：开发对接建议

- **统一索引**：行情类接口多为 `(order_book_id, datetime/date)` 的 MultiIndex DataFrame，入库前可 `reset_index()` 拆分为列，便于写入 ClickHouse/DuckDB 的列式表。
- **复权策略**：落库建议保存不复权原始数据（`adjust_type='none'`）+ 复权因子，查询时动态复权，避免历史数据因复权基准变化而需全量回刷。
- **频率分层**：tick/分钟数据量大，建议单合约、分时段拉取并分区存储（按 `trading_date` 分区）；日线可批量多合约一次拉取。
- **夜盘归属**：期货分钟/tick 含 `trading_date` 字段，注意夜盘数据归属于下一交易日，入库分区以 `trading_date` 为准。
- **实时/历史边界**：`get_ticks`、`get_live_ticks`、`current_minute`、`current_snapshot`、`get_live_minute_price_change_rate` 仅当日有效，历史回补需用 `get_price`。
- **代码标准化**：外部数据源代码先经 `id_convert` 转为米筐标准 `order_book_id` 再对接，保证主键一致。


