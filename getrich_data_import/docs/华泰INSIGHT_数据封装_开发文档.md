# 华泰 INSIGHT 二级市场量价数据 · Python 封装层开发文档

> 状态:起草中（随官方文档逐页补充）
> 最后更新:2026-06-05
> 数据来源:华泰证券 INSIGHT 金融数据服务（https://findata-insight.htsc.com:9151）
> 已录入:数据地图、行情权限、通用、股票(全)、指数、期货、期权、基金/ETF、Barra 因子(债券不纳入)

---

## 0. 项目定位与技术选型

| 项 | 决策 |
|---|---|
| 包性质 | 对官方 INSIGHT Python SDK 的**二次封装层**(统一接口、落库、缓存、复权) |
| 数据形态 | **实时订阅(推送)** + **历史查询(请求-响应)** + **异步回放(playback)** 三种范式都做 |
| 当前数据频率 | 日频、分钟频 |
| 落库(当前) | **PostgreSQL + TimescaleDB**(日频/分钟频 hypertable),**DuckDB**(回测本地列存) |
| 落库(未来) | 上 tick / 逐笔后引入 **ClickHouse** |
| 设计原则 | 准确性优先、性能次之;原始数据与衍生数据分离 |

---

## 1. 数据地图(来自 DataDictionaryIntro 入口页)

INSIGHT 数据分 8 大类。**加粗** = 二级市场量价相关。

### 股票数据
- **基础数据**:基础信息、行业分类、**复权因子**、新股上市
- **行情数据**:实时信息、**K线**、**tick**、**逐笔**、行情衍生指标、日交易数据
- 财务 / 融资融券 / 公司 / 特色数据(非量价,略)

### 债券 / 基金 / 指数 / 期货 / 期权
- 行情数据均含:实时、K线、tick、行情衍生指标
- 股票/债券/基金额外有**逐笔**;指数/期货/期权**无逐笔**
- 期货/期权**仅有行情,无基础/合约数据**

### 因子数据
- AI 因子(含 barra 因子)

---

## 2. 行情数据权限与覆盖范围

> ⚠️ **"最近 5 年"只约束「快照原始数据(tick)」,不约束 K 线/日频。**(已确认)
> - 日频 / 分钟频 K 线:**不止 5 年**
> - tick 异步回放 `playback_tick`:可回放 **2017 年至今**
> - tick 同步下载 `get_tick`:**仅近 30 天,且仅沪深**

| 交易所 | 证券类型 | 快照档位 | 快照时间范围 |
|---|---|---|---|
| 上交所/深交所/北交所/新三板 | 股票、基金、债券 | 5 档 | 最近 5 年 |
| 同上 | 指数 | 0 档 | 最近 5 年 |
| 港股通 | 股票 | 1 档 | 最近 5 年 |
| H股全流通 | 股票 | 5 档 | 最近 5 年 |
| 中证/国证指数 | 指数 | 0 档 | 最近 5 年 |
| 华泰证券 | 资金流向 | 0 档 | 最近 5 年 |

> 注:tick 接口返回 10 档买卖盘,但 **6–10 档仅高级版可见**;**逐笔数据整体仅高级版开放**。

---

## 3. 全局约定(最高优先级 — 定错则字段全废)

### 3.1 标的代码体系 `htsc_code`(已明确)
所有接口统一用 `htsc_code`,后缀规则:

| 交易所 | 交易所代码 | 后缀 | 示例 / 备注 |
|---|---|---|---|
| 上交所 | XSHG | `.SH` | 600000.SH |
| 深交所 | XSHE | `.SZ` | 000001.SZ |
| 北交所 | XBSE | `.BJ` | 8 和 4 开头 |
| 港股通 | HKSC | `.HKSC` | 00308.HKSC |
| H股全流通 | HGHQ | `.HGHQ` | 01336.HGHQ |
| 香港交易所(日历用) | XHKG | — | 港股 daily 用 `.HK` |

**期货 / 期权交易所后缀**(实测自返回样例)

| 交易所 | 后缀 | 示例 | 备注 |
|---|---|---|---|
| 中金所 CCFX | `.CF` | IF2312.CF, TS2312.CF | 股指/国债期货;期权 7200.CF |
| 上期所 XSGE | `.SHF` | AG2306.SHF | |
| 大商所 XDCE | `.DCE` | A2305.DCE | 含商品期权 |
| 郑商所 XZCE | `.ZCE` | MA304.ZCE, CF03.ZCE | ⚠️合约年份**仅 1 位**(304=2304?),跨 10 年有歧义 |
| 能源中心 INE | `.INE` | LU03.INE | |
| 股票期权(沪/深) | `.SH` / `.SZ` | 6 位数字代码,如 10004535.SH | 含认购/认沽,代码可能带 `P`(如 6P4500.SH) |

> **决策**:封装层第一步建 symbol 映射表,把 `htsc_code` ↔ 标准代码 ↔ 交易所代码三者打通。注意:① 港股日交易接口用 `.HK` 而非 `.HKSC`;② 郑商所合约 1 位年份需用上下文(上市/交割月)补全为 4 位,否则跨年错位;③ 期权代码无含义,合约要素(行权价/认沽认购/到期)需另建元数据表(见 §3.9)。

### 3.2 复权(已明确,关键)
复权因子接口 `get_adj_factor` 返回三个因子:

| 字段 | 含义 | 用途 |
|---|---|---|
| `xdy` | 当次除权因子 | 单次除权除息比例 |
| `b_xdy` | 逆推累积除权因子 | **前复权**(最新价系数=1,向前调整历史) |
| `f_xdy` | 顺推累计除权因子 | **后复权**(最早价系数=1,向后调整) |

- **稀疏存储**:复权因子表只在发生除权除息的交易日有记录(`begin_date`=除权日)。封装层需做"区间填充"(下一个除权日之前沿用同一因子)。
- **验证口径**:未除权时,前一日 `close` == 次日 `prev_close`;除权日 `当次因子 = 除权前一日close / 除权日prev_close`。
- **决策**:K 线/分钟存**原始未复权价 + 复权因子表**,查询层动态合成前/后复权。不存复权后价格。

**⚠️ 复权价有 4 个来源,需实测交叉验证(后续测试项)**

| 来源 | 提供 | 备注 |
|---|---|---|
| `get_kline(fq=)` | 直接返回复权后 OHLC | SDK 内置复权,口径未知 |
| `get_daily_basic.backward_adjusted_closing_price` | 仅后复权 close | OHLC 其余不复权,易混用 |
| `get_stock_valuation` | **前复权 + 后复权 close** | 字段最全,**暂定首选源** |
| `get_adj_factor` 自算 | 原始价 × 因子 | 口径可控,作为基准对账 |

- 这四者**复权口径不一定一致**(累计方式、基准日、分红是否计入可能不同)。落库前必须写一个**对账脚本**,选一批含多次除权/送转的标的(如 601688.SH),四源逐日比对收盘价,容差内才采信。
- **重点测 `get_stock_valuation` 这个首选源的完整性**:是否覆盖全部 A 股(含北交所/新三板)、历史是否够长、停牌日是否有值、新股上市首日是否缺失。若覆盖不全,需用 `get_adj_factor` 自算兜底。
- 在对账结论出来前,首选源仅为**暂定**,§5 的 `fct_valuation` 不锁死。

### 3.3 时间戳(发现一个坑)
- **K 线 `time` 不是规整时间戳**:它是该周期内"最后一条行情"的时间。例:日 K 的 time 是 `2021-05-14 15:59:03` 而非当日 00:00 或 15:00。**落库时必须额外生成规整的 `trading_day` / `bar_start` 列做主键和聚合**,不能直接拿 `time` 当日期。
- 实时/tick/逐笔 time 精度到毫秒(`HH:MM:SS.ffffff`)。
- **决策**:落库统一存「交易所原始 time」+「规整 bar 时间」双列;时区默认交易所本地时间(待确认 SDK 是否已转)。

### 3.4 交易日历
- `get_trading_days(exchange, trading_day, count)`:`count` 与 `trading_day` **互斥**(不能同时填)。
- 返回是 **numpy.ndarray 且倒序**(最新日期在前)——封装层要排序后再用。
- 各市场日历不同(沪深/港股/期货所),独立维护。

### 3.5 接口三范式(封装层要统一抽象)
| 范式 | 函数形态 | 返回 | 适用 |
|---|---|---|---|
| 历史查询 | `query.get_xxx(...)` | DataFrame | 落库、回测取数 |
| 实时订阅 | `subscribe_xxx_by_id/type` + 回调 `on_xxx` | 推送流 | 实时入库 |
| 异步回放 | `playback_xxx(...)` + 回调 `on_playback_xxx` | 推送流 | 历史 tick/逐笔补录 |

> **决策**:封装层对三者提供统一的 `fetch()`(同步返回 DataFrame)和 `stream()`(回调→队列)两套门面;回放本质是"历史流",内部归到 stream() 并可选落库。

### 3.6 数值类型与 Point-in-Time(新增,关键)
- **财务三大报表所有数值字段类型为 string**(连金额都是字符串)。衍生指标标 int64 但值为小数,特色数据标 int64 但是定点金额。**决策**:封装层建一个统一的 `coerce_numeric()`(str/空串/None → Decimal,价格用 Decimal、量用 int64),所有入库前强制过一遍,并记录原始 NaN。
- **财务接口必须做 point-in-time**:返回含 `pub_date`(发布日)和 `end_date`(报告期末)。**回测取数一律按 `pub_date <= 决策日` 过滤,严禁用 end_date**,否则引入未来函数。落库时 `pub_date` 必须进主键/索引。

### 3.8 跨品种 K线 / tick 字段差异(多品种建表的核心)
`get_kline` / `get_tick` 是全品种共用接口(`security_type` 区分),但**返回字段随品种变化**:

| 品种 | K线额外字段 | num_trades | tick 买卖档位 |
|---|---|---|---|
| 股票/基金/债券 | — | ✅ | 10 档(6–10 仅高级版) |
| 指数 | — | ❌(指数 K 线无 num_trades) | **0 档**(指数无盘口) |
| 期货 | **+ open_interest(持仓量) + settle(结算价)** | ✅ | 5 档 + pre_settle/pre_open_interest |
| 期权 | **+ open_interest + settle** | ✅ | 5 档 + pre_settle/pre_open_interest |

> **决策**:K线、tick 各用**一张超集宽表**,品种特有列(open_interest/settle、bid6–10)设为 nullable,用 `security_type` 区分;不为每个品种单独建表。`settle`/`open_interest` 文档标 int64 但结算价是价格,入库走 §3.6 `coerce_numeric`。

### 3.9 期货/期权合约元数据缺口(最大的坑)
- INSIGHT 对期货/期权**只提供行情,没有任何合约/基础数据接口**(期权连 `get_basic_info` 之外的合约要素都没有)。
- 缺失项:合约乘数、最小变动、保证金、**交割/到期月、行权价、认购认沽、标的资产、主力/次主力标记、连续合约规则**。
- **决策**:这些必须**外部补充**(交易所公开合约规格 / 自建解析)。封装层建独立的 `dim_futures_contract`、`dim_option_contract` 元数据表,与行情按 htsc_code 关联。**期货"主力连续"序列需自行合成**(按持仓量/成交量换月),并明确换月复权规则。
- 期货的 `fq` 复权参数语义存疑:期货无除权,所谓"复权"应是主力连续换月时的价差拼接——`fq` 对期货到底做什么,待实测确认。

### 3.10 其他待确认
| 项 | 状态 |
|---|---|
| 衍生指标字段类型 | 文档把 amv/boll 等标为 int64 但示例值是小数(22.7207)——疑似文档误标,封装层按 float 处理并验证 |
| `get_all_basic_info` 的 lot_size/tick_size/total_share | 示例返回 NaN,可能未填充,需实测 |
| SDK 限流 / 并发 / 单次条数上限 | 未见说明,待确认 |

---

## 4. 接口清单(股票:基础 + 行情)

### 4.1 通用 — 交易日历
- `get_trading_days(exchange, trading_day, count)` → (交易所, ndarray[倒序])

### 4.2 股票 · 基础数据
| 接口 | 入参 | 关键出参 | 备注 |
|---|---|---|---|
| `get_basic_info(htsc_code)` | htsc_code | listing_state, exchange, listing_date, delisting_date | 上市/退市状态;另有港股版含 currency/par_value/board_name |
| 行业分类 | — | — | 已录(枚举表,待整理进附录) |
| `get_adj_factor(htsc_code, begin_date)` | 代码+日期范围 | xdy / b_xdy / f_xdy | 见 §3.2,稀疏 |
| 新股上市 | — | — | 已录(待整理) |

### 4.3 股票 · 行情数据
| 接口 | 类型 | 入参 | 关键出参 | 备注 |
|---|---|---|---|---|
| `get_basic_info` / `get_all_basic_info` | 查询 | 代码 或 类型+交易所 | prev_close, max(涨停), min(跌停), 买卖数量单位/上下限 | 实时快照基础信息 |
| `get_kline(htsc_code, time, frequency, fq)` | 查询 | 代码list, 时间范围, 频率, 复权 | open/close/high/low/**num_trades**/volume/value | time=周期最后行情时间(见 §3.3) |
| `subscribe_kline_by_id/type` | 订阅 | 代码/类型, mode, frequency | 同上(无 num_trades) | frequency 如 ["15s","1min"] |
| `get_tick(htsc_code, trading_day, security_type)` | 查询(同步) | 代码,日期,类型 | last/open/high/low/close + **bid1-10/ask1-10 + size** + volume/value(累计) | **仅近30天、仅沪深** |
| `playback_tick(htsc_code, replay_time, fq)` | 回放(异步) | 代码,时间范围,复权 | 同上 57 字段 | **可回放2017至今**;6-10档仅高级版 |
| `subscribe_tick_by_id/type` | 订阅 | 代码/类型, mode | 同上 | 实时10档 |
| `subscribe_trans_and_order_by_id/type` | 订阅 | 代码/类型, mode | 逐笔成交+逐笔委托(data_type区分) | **仅高级版** |
| `playback_trans_and_order(htsc_code, replay_time, fq)` | 回放 | 代码,时间范围,复权 | 同上 | 历史逐笔补录 |
| `get_derived(htsc_code, trading_day, type)` | 查询 | 代码,日期,指标类型 | amv/ar_br/bias/boll/cr/vma_ma/vr/wr | 按 type 取不同字段集 |
| `get_daily_basic(htsc_code, trading_day)` | 查询 | 代码,日期范围 | OHLC + **backward_adjusted_closing_price** + turnover_rate/amplitude/avg_price/流通市值/总市值/成交笔数 | A股;⚠️只有close给后复权,OHLC不复权 |
| `get_hk_daily_basic(htsc_code, trading_day)` | 查询 | 代码,日期范围 | OHLC+涨跌幅+振幅 | 港股,代码用 .HK |

**逐笔数据双流结构**(高级版):
- 逐笔成交 `transaction`:trade_index, trade_buy_no, trade_sell_no, trade_bs_flag(方向), trade_price, trade_qty, trade_money, app_seq_num, channel_no, trade_type
- 逐笔委托 `order`:order_index, order_type, order_price, order_qty, order_bs_flag, channel_no, order_no, app_seq_num, **traded_qty(仅上交所)**
- ⚠️ 沪深两所机制不同(上交所有 order_no 撤单标识、traded_qty;深交所靠 app_seq_num),**重建订单簿要分所处理**。

### 4.4 股票 · 财务数据(point-in-time 关键)
| 接口 | 入参 | 字段量 | 关键字段 / 备注 |
|---|---|---|---|
| `get_income_statement(htsc_code, end_date, period)` | 代码,报告期范围,季度 | ~63 | 利润表;pub_date(发布日)+ end_date(报告期末) |
| `get_balance_sheet(htsc_code, end_date, period)` | 同上 | ~131 | 资产负债表;含多项占比指标 |
| `get_cashflow_statement(htsc_code, end_date, period)` | 同上 | ~99 | 现金流量表 |
| `get_fin_indicator(htsc_code, end_date, period)` | 同上 | ~135 | 财务指标(ROE/EPS/周转率/利润率等全套) |
| `get_stock_valuation(htsc_code, trading_day)` | 代码,交易日范围 | 19 | **日频估值**:close + **前复权 + 后复权收盘价** + PE/PEttm/PB/PC/PS + 流通/总市值。港股版 `get_hk_stock_valuation` |

> ⚠️ **两个大坑(都进了 §3 全局约定)**:
> 1. 三大报表所有数值字段类型都是 **string**(连金额都是字符串),封装层必须统一做 `str→Decimal/float` 转换并处理空串。
> 2. 财务接口同时返回 `pub_date`(发布日)与 `end_date`(报告期末)。**回测必须按 `pub_date` 对齐做 point-in-time,用 end_date 会引入未来函数。**
> 3. `get_stock_valuation` 同时给前/后复权收盘价,是比 `get_daily_basic` 更完整的日频估值源,优先用它建日频估值表。

### 4.5 股票 · 融资融券
| 接口 | 入参 | 关键字段 |
|---|---|---|
| `get_margin_target(htsc_code, exchange)` | 代码/交易所 | 两融标的列表(htsc_code, name) |
| `get_margin_summary(htsc_code, trading_day)` | 代码,日期范围 | 个股两融:融资买入/余额/偿还、融券卖出量/余量/偿还、两融余额、融资余额占流通市值% |
| `get_margin_detail(exchange, trading_day)` | 交易所,日期范围 | 市场层面两融汇总(同字段,无个股维度) |

### 4.6 股票 · 公司数据
| 接口 | 入参 | 关键字段 / 备注 |
|---|---|---|
| `get_company_info(htsc_code, name)` | 代码/简称 | 公司概况:行业(证监会一级/申万二级)、注册资本、地域、主营等 |
| `get_capital_structure(htsc_code, end_date)` | 代码,结束日范围 | 股本结构(总股本/流通/限售/各类股东持股,含除权除息日) |
| `get_shareholders_top10(htsc_code, change_date)` | 代码,变动期范围 | 十大股东:持股数/占比/增减持/股东代码 |
| `get_shareholders_floating_top10(htsc_code, change_date)` | 同上 | 十大流通股东(注:源文档签名有多余括号,实测确认) |
| `get_dividend(htsc_code, right_reg_date, ex_divi_date, divi_pay_date)` | 代码+三类日期范围 | 分红:股权登记日/除息日/送转比例/派现。港股版 `get_hk_dividend` |
| `get_additional_share(htsc_code, listing_date)` | 代码,上市日范围 | 增发 |
| `get_allotment_share(htsc_code, Ini_pub_date, is_allot_half_year)` | 代码,首次公告日范围,半年内配股 | 配售 |
| `get_frozen_shares(htsc_code, freezing_start_date)` | 代码,冻结起始日范围 | 股权质押/冻结 |
| `get_locked_shares(htsc_code, trading_day)` | 代码,日期范围 | 限售股解禁:新增可上市量/占总股本%/占流通% |
| `get_main_product_info(htsc_code, product_code, product_level)` | 代码,产品码,层级 | 主营产品收入/毛利及占比 |

> 注:分红(`get_dividend`)与股本结构里的 `ex_divi_date` 是验证复权因子的交叉数据源,可用来核对 §3.2 的 xdy。

### 4.7 股票 · 特色数据(日频量价衍生,可入库)
| 接口 | 入参 | 关键字段 / 备注 |
|---|---|---|
| `get_money_flow(htsc_code, trading_day)` | 代码,日期范围 | **资金流向**:超大/大/中/小/主力单 的流入流出 金额(元)+股数。⚠️源文档序号 23 重复(main_inflow_value/qty) |
| `get_trade_distribution(htsc_code, trading_day)` | 代码,日期范围 | **成交分价**:每个价位的成交股数/买卖股数/笔数/每笔均量 |
| `get_chip_distribution(htsc_code, trading_day)` | 代码,日期范围 | **筹码分布**:5/15/50/85/95 分位持仓成本、加权/最大/最小成本、获利胜率、筹码分散度 |
| `get_billboard(type, market)` | 榜名,市场 | 排行榜(涨幅/跌幅榜等),实时快照,value 为 1–10 排序位 |
| `get_change_summary(market, trading_day)` | 市场,日期范围 | 涨跌分析:各涨跌幅区间的只数分布 |

> 资金流向/成交分价/筹码分布字段虽标 int64,但金额/成本本质是定点数,封装层统一转 Decimal 并核对单位(元 vs 万元)。

### 4.8 指数
| 接口 | 类型 | 入参 | 关键出参 / 备注 |
|---|---|---|---|
| `get_index_info(htsc_code, trading_day)` | 查询 | 代码,日期范围 | **日频指数行情**:OHLC + prev_close + volume + value + change + change_rate |
| `get_all_index(trading_day, exchange)` | 查询 | 日期范围,交易所 | 按市场批量取日频指数行情 |
| `get_index_component(htsc_code, name, stock_code, trading_day)` | 查询 | 指数/成分股/日期 | **成分股 + weight + in_date + out_date**(时点成分,回测必备) |
| `get_kline` / `subscribe_kline_*` | 查询/订阅 | 同股票 | OHLC+volume+value,**无 num_trades** |
| `get_tick` / `playback_tick` / `subscribe_tick_*` | 查询/回放/订阅 | 同股票 | **0 档**(无盘口),仅 last/OHLC/累计量额 |
| `get_basic_info` / `get_all_basic_info` | 查询 | 同股票 | 指数实时基础信息 |

> `get_index_component` 的 in_date/out_date 让你能还原任意历史日的成分与权重,**单独建时点成分表**,避免用当前成分回测(幸存者偏差)。

### 4.9 期货(仅行情,合约元数据需外补 — 见 §3.9)
| 接口 | 类型 | 关键出参 / 备注 |
|---|---|---|
| `get_kline` / `subscribe_kline_*` | 查询/订阅 | OHLC + num_trades + volume + value + **open_interest + settle** |
| `get_tick`(同步,近30天) / `playback_tick`(异步) / `subscribe_tick_*` | 查询/回放/订阅 | 5 档盘口 + last/OHLC + **pre_settle/settle + pre_open_interest/open_interest**;tick 仅高级版 |
| `get_basic_info` / `get_all_basic_info` | 查询 | 实时信息(返回字段在文档图片层,未抽取,待实测) |

### 4.10 期权(仅行情,合约要素缺口最大 — 见 §3.9)
| 接口 | 类型 | 关键出参 / 备注 |
|---|---|---|
| `get_kline` / `subscribe_kline_*` | 查询/订阅 | 同期货:OHLC + num_trades + volume + value + open_interest + settle |
| `get_tick` / `playback_tick` / `subscribe_tick_*` | 查询/回放/订阅 | 同期货结构,5 档 + settle/open_interest;仅高级版 |
| `get_basic_info` / `get_all_basic_info` | 查询 | 实时基础信息;**无行权价/认沽认购/到期/标的等合约要素接口** |

> 期权 Greeks、隐含波动率、合约要素 INSIGHT 均不提供,需自算或外部源补充。

### 4.11 基金 / ETF
| 接口 | 类型 | 入参 | 关键出参 / 备注 |
|---|---|---|---|
| `get_fund_info(htsc_code, trading_day)` | 查询 | 代码,日期范围 | **日频基金行情**:OHLC + **后复权close** + unit_nav(净值) + 折价率 + 升贴水/率 + 换手/振幅/笔数 |
| `get_fund_target(htsc_code, exchange, end_date)` | 查询 | 代码,交易所,截止日范围 | **净值衍生**:单位/累计/复权净值 + 1周–5年多窗口净值增长率&排名 + **beta/sharpe/jensen/treynor/R²** |
| `get_public_fund_portfolio(htsc_code, name, exchange, end_date)` | 查询 | 股票代码等 | **个股公募持仓**:某股票被多少基金持有、持仓市值(万元)/股数(万股) |
| `get_kline` / `get_tick` / `get_basic_info` | 查询/订阅 | 同股票 | 基金行情与股票同构(有 num_trades) |
| `subscribe_trans_and_order_*` / `playback_trans_and_order` | 订阅/回放 | 同股票 | 基金**有逐笔**(高级版) |
| `get_etf_component(htsc_code, pub_date, trading_day)` | 查询 | 代码,公告日,交易日 | **ETF 申赎成份券**:成分股 + 数量 + 现金替代标志/金额/申赎替代额 |
| `get_etf_redemption(htsc_code, exchange, trading_day)` | 查询 | 代码,交易所,交易日 | **ETF 申赎清单**:现金差额、最小申赎单位、IOPV 相关、申赎上限 |
| `get_etf_info(query_list)` | 查询 | (交易所,证券类型) 列表 | ETF 实时信息 |

> ETF 申赎成份券 + 申赎清单是 **IOPV / T+0 套利**的核心数据,单独建表。`get_fund_info`(量价+净值)与 `get_fund_target`(净值+风险指标)关系类同股票的 daily_basic vs valuation,后复权 close 一并纳入 §3.2 四源对账。

### 4.12 因子 · Barra(CNE6)
| 接口 | 入参 | 出参 |
|---|---|---|
| `get_factors(htsc_code, factor_name, trading_day)` | 代码, **单个因子名**, 日期范围 | trading_day(string `yyyyMMdd`) + value(**string**) |

Barra CNE6 共 **16 个风格因子**:beta、booktoprice、dividendyield、earningsquality、earningsvariability、earningsyield、growth、investmentquality、leverage、liquidity、longtermreversal、midcap、momentum、profitability、residualvolatility、size。

> ⚠️ 三个注意点:① 接口**一次只取一个因子**(factor_name 单值),拉全 16 个要循环;② 返回 `value` 是 **string**,走 §3.6 `coerce_numeric`;③ `trading_day` 格式是 **`yyyyMMdd` 字符串**,与其它接口的 datetime 不同,解析要特判。**决策**:落库用**长表** `fct_barra_factor(htsc_code, trading_day, factor_name, value)`,查询层 pivot 成宽表。

---

## 5. 落库表结构设计(草案)

### 5.1 PostgreSQL + TimescaleDB(当前:日频/分钟频)
**维度表**
- `dim_symbol`:htsc_code, 标准代码, exchange, security_type, 上市/退市日期(symbol 映射 + 生命周期)
- `dim_trading_calendar`:exchange, trading_day(独立日历)

**行情(量价核心)**
- `fct_adj_factor`:htsc_code, begin_date, xdy, b_xdy, f_xdy(稀疏,查询时区间填充)
- `fct_kline_min`(hypertable):htsc_code, bar_start, frequency, OHLC, num_trades, volume, value, raw_time
- `fct_kline_daily`(hypertable / 连续聚合):同上,trading_day 为时间维
- `fct_daily_basic`(hypertable):get_daily_basic 全字段(含后复权close、换手率、市值)
- `fct_valuation`(hypertable):get_stock_valuation(前/后复权close + PE/PB/PS/PC + 市值)——**暂定**日频估值/复权首选源,待 §3.2 四源对账确认完整性后锁定

**特色(日频衍生,可入库)**
- `fct_money_flow`:超大/大/中/小/主力单 流入流出金额+股数
- `fct_trade_distribution`:成交分价(价位×量×笔数)
- `fct_chip_distribution`:筹码分布(分位成本/获利胜率/分散度)
- `fct_margin`:两融个股汇总(get_margin_summary)

**指数 / 期货 / 期权**
- K 线统一进 `fct_kline_min` / `fct_kline_daily`(超集宽表,open_interest/settle 列 nullable,见 §3.8)
- `fct_index_daily`:get_index_info 日频指数行情
- `fct_index_component`:指数时点成分(weight + in_date/out_date),回测取成分用
- `dim_futures_contract` / `dim_option_contract`:**外部补充**的合约元数据(乘数/保证金/交割月/行权价/认沽认购/标的)
- `fct_futures_continuous`:自合成的主力连续序列(换月规则+拼接价)

**基金 / ETF**
- `fct_fund_daily`:get_fund_info 日频基金行情(OHLC+后复权close+净值+折价/升贴水)
- `fct_fund_nav`:get_fund_target 净值衍生(累计/复权净值 + 风险指标 beta/sharpe 等)
- `fct_public_fund_holding`:get_public_fund_portfolio 个股公募持仓(PIT,按 end_date)
- `dim_etf_basket` / `fct_etf_redemption`:ETF 申赎成份券 + 申赎清单(IOPV/套利用)

**因子**
- `fct_barra_factor`:长表(htsc_code, trading_day, factor_name, value),16 因子,value 转 Decimal;查询层 pivot

**基本面(point-in-time)**
- `fct_income` / `fct_balance` / `fct_cashflow` / `fct_fin_indicator`:三大报表+指标,**主键含 pub_date**,数值统一 Decimal
- `dim_company`、`fct_dividend`、`fct_capital_structure`、`fct_top_holders`、`fct_locked_shares` 等公司事件表(按需)

> 复权在视图/查询函数层合成,不落复权价。财务/事件类按 pub_date 建索引支持 PIT 查询。

### 5.2 DuckDB(回测)
- 从 Timescale / parquet 导出列存快照;复权后宽表按需物化

### 5.3 ClickHouse(未来 tick / 逐笔)
- `tick`:57 字段含 10 档(按 §4.3)
- `trans`(逐笔成交)/ `order`(逐笔委托)分表,分所字段差异用 nullable 兼容

---

## 6. 待确认问题清单(滚动更新)

1. ~~日频K线是否仅5年~~ → **已确认不止5年**;待补:日/分钟 K 线的最早可取日期。
2. ~~复权因子定义~~ → **已明确**(xdy/b_xdy/f_xdy)。
3. ~~标的代码映射~~ → **已明确**;待补:港股 .HK vs .HKSC vs .HGHQ 三者关系。
4. K 线 / tick 的 time 时区:SDK 是否已转北京时间?
5. 衍生指标字段实际类型(文档标 int64,值为小数)。
6. SDK 限流 / 并发 / 单次查询条数上限。
7. 期货/期权合约元数据(主力连续、保证金、交割、行权价、认沽认购)从何获取 → 已确认 INSIGHT 不提供,需外部补充(见 §3.9)。
   - 7a. `fq` 参数对期货/期权语义(无除权,是否指主力连续换月拼接?)。
   - 7b. 郑商所合约 1 位年份补全规则(需上市/交割月上下文)。
   - 7c. 期货/期权 `get_basic_info` 返回字段(文档图片层,需实测)。
8. **复权价多来源一致性(需实测)**:见 §3.2 末尾——`get_kline(fq=)`、`get_daily_basic.backward_adjusted_closing_price`、`get_stock_valuation`(前/后复权)、`get_adj_factor` 自算,四个来源要交叉验证,并确认首选源 `get_stock_valuation` 的标的/历史覆盖是否完整。
9. `get_daily_basic` 的 OHLC 复权口径确认(仅 close 后复权,others 不复权?)。
10. 高级版 vs 标准版的权限边界(逐笔、tick 6-10 档)对应你的账户是哪档。
11. 财务接口 `period` 季度参数的枚举值(Q1/H1/Q3/FY?单季 vs 累计?)。
12. 财务字段为 string 的精度:是否有千分位/单位混排,转换规则需实测。
13. `get_dividend` 的 splitps/bonus_ratio 等"1:X"格式,解析规则确认。
14. 资金流向"主力单"口径(超大+大?),与超大/大/中/小是否重叠计数。

---

## 7. 已录入接口清单(进度)
- ✅ 通用:交易日历
- ✅ 股票·基础:基础信息、行业分类、复权因子、新股上市
- ✅ 股票·行情:实时信息、K线、tick、逐笔、衍生指标、日交易数据
- ✅ 股票·财务:利润表、资产负债表、现金流量表、财务指标、市值数据
- ✅ 股票·两融:融资融券列表、成交概况、交易明细
- ✅ 股票·公司:概况、增发、配售、股本结构、十大股东、十大流通股东、分红、股权质押、限售解禁、主营产品
- ✅ 股票·特色:资金流向、成交分价、筹码分布、排行榜、涨跌分析
- ✅ 指数:基础信息、指数成分股(时点)、K线、tick、实时信息
- ✅ 期货:K线、tick、实时信息(合约元数据需外补)
- ✅ 期权:K线、tick、实时信息(合约要素需外补)
- ✅ 基金/ETF:基础信息、净值衍生、个股公募持仓、K线、tick、逐笔、ETF申赎成份券/清单/实时
- ✅ 因子:Barra CNE6(16 风格因子)
- ⬜ 债券:按需求不纳入
- 📋 数据录入阶段完成 → 下一步:§5 表结构细化为 DDL
