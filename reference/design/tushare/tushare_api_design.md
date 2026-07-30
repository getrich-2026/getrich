# Tushare Pro API 读取设计文档

> 文档版本：2026-06-14  
> 覆盖权限范围：基础数据 / 低频行情 / 财务数据 / 宏观经济 / 参考数据 / 港股基础信息

---

## 1. 概述

### 1.1 接入方式

```python
import tushare as ts

ts.set_token("YOUR_TOKEN")   # 全局设置一次即可
pro = ts.pro_api()
```

所有接口均通过 `pro.<api_name>(**params)` 调用，返回 `pandas.DataFrame`。

### 1.2 通用规范

| 项目 | 说明 |
|------|------|
| 股票代码格式 | `ts_code`：`000001.SZ` / `600000.SH` / `300001.SZ` |
| 日期格式 | `YYYYMMDD`（字符串），如 `"20240101"` |
| 月份格式 | `YYYYMM`，如 `"202401"` |
| 季度格式 | `YYYYQX`，如 `"2024Q1"` |
| 单次返回上限 | 默认 5000 行（部分接口可通过分页获取更多） |
| 频率限制 | 根据积分等级限速，建议调用间隔 ≥ 0.3s |

### 1.3 字段筛选

所有接口支持 `fields` 参数，传入逗号分隔的字段名字符串可减少数据量：

```python
df = pro.daily(ts_code="000001.SZ", start_date="20240101",
               fields="ts_code,trade_date,open,high,low,close,vol")
```

---

## 2. 基础数据

### 2.1 股票列表 `stock_basic`

**文档**：https://tushare.pro/document/2?doc_id=25  
**接口**：`pro.stock_basic()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| exchange | str | 否 | 交易所：`SSE`（上交所）/ `SZSE`（深交所）/ `BSE`（北交所） |
| list_status | str | 否 | 上市状态：`L`（上市）/ `D`（退市）/ `P`（暂停上市），默认 `L` |
| is_hs | str | 否 | 是否沪深港通标的：`N`/`H`/`S` |
| fields | str | 否 | 输出字段，逗号分隔 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | TS代码（如 `000001.SZ`） |
| symbol | str | 股票代码（如 `000001`） |
| name | str | 股票名称 |
| area | str | 地域（如 `深圳`） |
| industry | str | 所属行业 |
| fullname | str | 股票全称 |
| enname | str | 英文全称 |
| cnspell | str | 拼音缩写 |
| market | str | 市场类型（主板/创业板/科创板/CDR） |
| exchange | str | 交易所代码 |
| curr_type | str | 交易货币 |
| list_status | str | 上市状态 |
| list_date | str | 上市日期 |
| delist_date | str | 退市日期 |
| is_hs | str | 是否沪深港通（N/H/S） |
| act_name | str | 实控人名称 |
| act_ent_type | str | 实控人企业性质 |

#### 示例

```python
# 获取所有上市A股
df = pro.stock_basic(exchange='', list_status='L',
                     fields='ts_code,symbol,name,area,industry,list_date,market')
```

---

### 2.2 交易日历 `trade_cal`

**文档**：https://tushare.pro/document/2?doc_id=26  
**接口**：`pro.trade_cal()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| exchange | str | 否 | 交易所：`SSE` / `SZSE`，默认 `SSE` |
| start_date | str | 否 | 开始日期（YYYYMMDD） |
| end_date | str | 否 | 结束日期（YYYYMMDD） |
| is_open | str | 否 | 是否交易日：`0` / `1` |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| exchange | str | 交易所 |
| cal_date | str | 日历日期 |
| is_open | int | 是否交易（1=是，0=否） |
| pretrade_date | str | 上一个交易日 |

#### 示例

```python
# 获取2024年所有交易日
df = pro.trade_cal(exchange='SSE', start_date='20240101', end_date='20241231', is_open='1')
```

---

### 2.3 股票曾用名 / ST `namechange`

**文档**：https://tushare.pro/document/2?doc_id=185  
**接口**：`pro.namechange()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码，空则返回全部 |
| start_date | str | 否 | 公告开始日期 |
| end_date | str | 否 | 公告结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | TS代码 |
| name | str | 证券名称 |
| start_date | str | 开始日期 |
| end_date | str | 结束日期 |
| ann_date | str | 公告日期 |
| change_reason | str | 变更原因 |

> **ST筛选技巧**：过滤 `name` 包含 `ST` 即可获取所有ST/\*ST股票的历史名称变更记录。

---

### 2.4 沪港通股票列表 `hs_const`

**文档**：https://tushare.pro/document/2?doc_id=188  
**接口**：`pro.hs_const()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| hs_type | str | 是 | 类型：`SH`（沪港通）/ `SZ`（深港通） |
| is_new | str | 否 | 是否最新：`1`（最新）/ `0`（历史） |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | TS代码 |
| hs_type | str | 沪深港通类型 |
| in_date | str | 纳入日期 |
| out_date | str | 剔除日期 |
| is_new | str | 是否最新 |

---

## 3. 低频行情数据

### 3.1 日线行情 `daily`

**文档**：https://tushare.pro/document/2?doc_id=27  
**接口**：`pro.daily()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 二选一 | 股票代码 |
| trade_date | str | 二选一 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

> 单次最多返回 5000 行。按股票查询可获取全部历史；按日期查询单次只能取某一天全市场数据。

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 交易日期 |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| pre_close | float | 昨收价（除权） |
| change | float | 涨跌额 |
| pct_chg | float | 涨跌幅（%） |
| vol | float | 成交量（手） |
| amount | float | 成交额（千元） |

#### 示例

```python
# 单只股票全历史
df = pro.daily(ts_code='000001.SZ', start_date='20200101', end_date='20241231')

# 某日全市场
df = pro.daily(trade_date='20240101')
```

---

### 3.2 周线行情 `weekly`

**文档**：https://tushare.pro/document/2?doc_id=28  
**接口**：`pro.weekly()`

输入/输出参数与 `daily` 相同，`trade_date` 为每周最后一个交易日。

---

### 3.3 月线行情 `monthly`

**文档**：https://tushare.pro/document/2?doc_id=29  
**接口**：`pro.monthly()`

输入/输出参数与 `daily` 相同，`trade_date` 为每月最后一个交易日。

---

### 3.4 复权因子 `adj_factor`

**文档**：https://tushare.pro/document/2?doc_id=38  
**接口**：`pro.adj_factor()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 交易日期 |
| adj_factor | float | 复权因子 |

> **后复权计算**：`后复权价 = 原价 × adj_factor`  
> **前复权计算**：`前复权价 = 原价 × (adj_factor / 最新adj_factor)`

或直接使用 `ts.pro_bar()` 获取带复权的行情：

```python
df = ts.pro_bar(ts_code='000001.SZ', adj='qfq',   # qfq=前复权, hfq=后复权
                start_date='20200101', end_date='20241231')
```

---

### 3.5 停复牌信息 `suspend_d`

**文档**：https://tushare.pro/document/2?doc_id=32  
**接口**：`pro.suspend_d()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 停复牌日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |
| suspend_type | str | 否 | `S`（停牌）/ `R`（复牌） |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 停复牌日期 |
| suspend_type | str | 停复牌类型（S/R） |
| suspend_reason | str | 停复牌原因 |

---

### 3.6 每日涨跌停价格 `stk_limit`

**文档**：https://tushare.pro/document/2?doc_id=183  
**接口**：`pro.stk_limit()`

获取全市场（含 A/B 股和基金）每日涨跌停价格。每个交易日 **8:40 左右**更新当日数据，可用于盘前构建可交易域。

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

> 单次最多返回 5800 条记录，可循环调取，总量不限制。

#### 输出字段

| 字段 | 类型 | 默认显示 | 说明 |
|------|------|---------|------|
| trade_date | str | Y | 交易日期 |
| ts_code | str | Y | TS股票代码 |
| pre_close | float | N | 昨日收盘价（需在 `fields` 中显式指定） |
| up_limit | float | Y | 涨停价 |
| down_limit | float | Y | 跌停价 |

#### 示例

```python
# 获取单日全市场涨跌停价格
df = pro.stk_limit(trade_date='20190625')

# 获取单只股票的历史涨跌停价格
df = pro.stk_limit(ts_code='002149.SZ', start_date='20190115', end_date='20190615')

# 需要昨收价时显式指定 fields
df = pro.stk_limit(trade_date='20240102',
                   fields='trade_date,ts_code,pre_close,up_limit,down_limit')
```

#### 应用：识别涨跌停与一字板

涨跌停价格由交易所按昨收价和涨跌幅限制（主板 10%、创业板/科创板 20%、ST 股 5%、北交所 30%）四舍五入到分，直接用 `pct_chg` 阈值判断会有误差，用 `stk_limit` 做精确匹配更可靠。

```python
import tushare as ts
import pandas as pd

pro = ts.pro_api()
d = '20240102'

px  = pro.daily(trade_date=d, fields='ts_code,trade_date,open,high,low,close,vol')
lim = pro.stk_limit(trade_date=d, fields='ts_code,trade_date,up_limit,down_limit')

df = px.merge(lim, on=['ts_code', 'trade_date'], how='left')

# 浮点比较留 0.5 分容差
tol = 0.005
df['is_up_limit']   = (df['close'] - df['up_limit']).abs()   < tol
df['is_down_limit'] = (df['close'] - df['down_limit']).abs() < tol
# 一字板：全天最高=最低=涨停价（无法买入）
df['is_one_word_up'] = ((df['low']  - df['up_limit']).abs()   < tol) & (df['vol'] > 0)
df['is_one_word_dn'] = ((df['high'] - df['down_limit']).abs() < tol) & (df['vol'] > 0)
```

#### 回测与实盘中的用法

| 场景 | 用法 |
|------|------|
| 可交易域过滤 | 次日一字涨停/跌停的股票剔除，避免回测中不可成交的虚假收益 |
| 滑点与撮合建模 | 委托价 clip 到 `[down_limit, up_limit]` 区间，模拟交易所价格笼子 |
| 打板/连板因子 | 统计连续涨停天数、封板率、炸板率 |
| 盘前信号生成 | 8:40 后即可拿到当日涨跌停价，早于开盘，可用于当日下单前的风控 |

> **注意**：`stk_limit` 的 `pre_close` 为未复权昨收价。与 `daily` 拼接做长周期回测时，需统一复权口径，或将涨跌停价一并按 `adj_factor` 调整。

---

## 4. 财务数据（三大报表）

> **重要说明**：
> - `ann_date`：公告日期（实际发布日）
> - `f_ann_date`：实际公告日期（修正后）
> - `end_date`：报告期（如 `20231231` 代表2023年年报）
> - `report_type`：报告类型（1=合并报表，2=单季合并，3=调整单季合并，4=调整合并，5=调整前合并，6=母公司，7=单季母公司，8=调整单季母公司，9=调整母公司，10=调整前母公司，11=调整前母公司，12=母公司）
> - 建议使用 `report_type=1`（合并报表）

---

### 4.1 利润表 `income`

**文档**：https://tushare.pro/document/2?doc_id=33  
**接口**：`pro.income()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码 |
| ann_date | str | 否 | 公告日期 |
| f_ann_date | str | 否 | 实际公告日期 |
| start_date | str | 否 | 报告期开始日 |
| end_date | str | 否 | 报告期结束日 |
| period | str | 否 | 报告期（如 `20231231`） |
| report_type | str | 否 | 报告类型，默认 `1` |
| comp_type | str | 否 | 公司类型（1一般，2银行，3保险，4证券） |

#### 核心输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| f_ann_date | str | 实际公告日期 |
| end_date | str | 报告期 |
| report_type | str | 报告类型 |
| end_type | str | 报告期类型（1=年，2=半年，3=季） |
| basic_eps | float | 基本每股收益 |
| diluted_eps | float | 稀释每股收益 |
| total_revenue | float | 营业总收入（元） |
| revenue | float | 营业收入 |
| total_cogs | float | 营业总成本 |
| oper_cost | float | 营业成本 |
| sell_exp | float | 销售费用 |
| admin_exp | float | 管理费用 |
| fin_exp | float | 财务费用 |
| assets_impair_loss | float | 资产减值损失 |
| operate_profit | float | 营业利润 |
| non_oper_income | float | 营业外收入 |
| non_oper_exp | float | 营业外支出 |
| total_profit | float | 利润总额 |
| income_tax | float | 所得税费用 |
| n_income | float | 净利润 |
| n_income_attr_p | float | 归属于母公司的净利润 |
| minority_gain | float | 少数股东损益 |
| ebit | float | 息税前利润 |
| ebitda | float | 息税折旧摊销前利润 |
| rd_exp | float | 研发费用 |
| update_flag | str | 更新标识 |

#### 示例

```python
# 获取某股票近3年年报利润表
df = pro.income(ts_code='000001.SZ', start_date='20210101', end_date='20231231',
                report_type='1',
                fields='ts_code,ann_date,end_date,total_revenue,n_income_attr_p,basic_eps')
```

---

### 4.2 资产负债表 `balancesheet`

**文档**：https://tushare.pro/document/2?doc_id=36  
**接口**：`pro.balancesheet()`

#### 输入参数

与 `income` 相同。

#### 核心输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| f_ann_date | str | 实际公告日期 |
| end_date | str | 报告期 |
| report_type | str | 报表类型 |
| total_share | float | 期末总股本（股） |
| cap_rese | float | 资本公积金 |
| undistr_porfit | float | 未分配利润 |
| surplus_rese | float | 盈余公积金 |
| total_hldr_eqy_exc_min_int | float | 归属于母公司的股东权益合计（不含少数股东） |
| total_hldr_eqy_inc_min_int | float | 股东权益合计（含少数股东） |
| total_liab_hldr_eqy | float | 负债及股东权益总计 |
| lt_borr | float | 长期借款 |
| st_borr | float | 短期借款 |
| notes_payable | float | 应付票据 |
| acct_payable | float | 应付账款 |
| total_cur_liab | float | 流动负债合计 |
| total_non_cur_liab | float | 非流动负债合计 |
| total_liab | float | 负债合计 |
| money_cap | float | 货币资金 |
| notes_receiv | float | 应收票据 |
| accounts_receiv | float | 应收账款 |
| inventories | float | 存货 |
| total_cur_assets | float | 流动资产合计 |
| fix_assets | float | 固定资产净值 |
| goodwill | float | 商誉 |
| total_non_cur_assets | float | 非流动资产合计 |
| total_assets | float | 资产总计 |
| update_flag | str | 更新标识 |

#### 示例

```python
df = pro.balancesheet(ts_code='000001.SZ', period='20231231', report_type='1',
                      fields='ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int')
```

---

### 4.3 现金流量表 `cashflow`

**文档**：https://tushare.pro/document/2?doc_id=44  
**接口**：`pro.cashflow()`

#### 输入参数

与 `income` 相同。

#### 核心输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| f_ann_date | str | 实际公告日期 |
| end_date | str | 报告期 |
| report_type | str | 报表类型 |
| net_profit | float | 净利润 |
| finan_exp | float | 财务费用 |
| c_fr_sale_sg | float | 销售商品、提供劳务收到的现金 |
| recp_tax_rends | float | 收到的税费返还 |
| n_depos_incr_fi | float | 客户存款和同业存放款项净增加额 |
| n_cash_flows_oper_act | float | 经营活动现金流入小计 |
| n_cashflow_act | float | 经营活动现金流量净额 |
| oth_pay_oper_act | float | 支付其他与经营活动有关的现金 |
| pay_all_typ_tax | float | 支付的各项税费 |
| c_pay_acq_const_fiolta | float | 购建固定资产、无形资产和其他长期资产的现金 |
| n_cash_flows_inv_act | float | 投资活动现金流入小计 |
| n_cashflow_inv_act | float | 投资活动现金流量净额 |
| c_recp_borrow | float | 取得借款收到的现金 |
| proc_issue_bonds | float | 发行债券收到的现金 |
| n_cash_flows_fnc_act | float | 筹资活动现金流入小计 |
| n_cashflow_fnc_act | float | 筹资活动现金流量净额 |
| n_incr_cash_cash_equ | float | 现金及现金等价物净增加额 |
| c_cash_equ_beg_period | float | 期初现金及现金等价物余额 |
| c_cash_equ_end_period | float | 期末现金及现金等价物余额 |
| free_cashflow | float | 企业自由现金流量 |
| update_flag | str | 更新标识 |

#### 示例

```python
df = pro.cashflow(ts_code='600519.SH', period='20231231', report_type='1',
                  fields='ts_code,end_date,n_cashflow_act,n_cashflow_inv_act,n_cashflow_fnc_act,free_cashflow')
```

---

## 5. 宏观经济数据

### 5.1 国内生产总值 `cn_gdp`

**文档**：https://tushare.pro/document/2?doc_id=63  
**接口**：`pro.cn_gdp()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| q | str | 否 | 季度（如 `2023Q4`） |
| start_q | str | 否 | 开始季度 |
| end_q | str | 否 | 结束季度 |
| fields | str | 否 | 返回字段 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| quarter | str | 季度（YYYYQX） |
| gdp | float | GDP累计值（亿元） |
| gdp_yoy | float | 当季同比增速（%） |
| pi | float | 第一产业累计值（亿元） |
| pi_yoy | float | 第一产业同比增速（%） |
| si | float | 第二产业累计值（亿元） |
| si_yoy | float | 第二产业同比增速（%） |
| ti | float | 第三产业累计值（亿元） |
| ti_yoy | float | 第三产业同比增速（%） |

---

### 5.2 居民消费价格指数 `cn_cpi`

**文档**：https://tushare.pro/document/2?doc_id=66  
**接口**：`pro.cn_cpi()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| m | str | 否 | 月份（如 `202312`） |
| start_m | str | 否 | 开始月份 |
| end_m | str | 否 | 结束月份 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| month | str | 月份（YYYYMM） |
| nt_val | float | 全国当月值 |
| nt_yoy | float | 全国同比（%） |
| nt_mom | float | 全国环比（%） |
| nt_accu | float | 全国累计值 |
| town_val | float | 城市当月值 |
| town_yoy | float | 城市同比（%） |
| town_mom | float | 城市环比（%） |
| cnt_val | float | 农村当月值 |
| cnt_yoy | float | 农村同比（%） |
| cnt_mom | float | 农村环比（%） |

---

### 5.3 工业品出厂价格指数 `cn_ppi`

**文档**：https://tushare.pro/document/2?doc_id=67  
**接口**：`pro.cn_ppi()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| m | str | 否 | 月份（YYYYMM） |
| start_m | str | 否 | 开始月份 |
| end_m | str | 否 | 结束月份 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| month | str | 月份 |
| ppi_yoy | float | PPI：全部工业品当月同比（%） |
| ppi_mp | float | PPI：全部工业品环比（%） |
| ppi_quart | float | PPI：全部工业品季比（%） |
| ppi_same | float | PPI：全部工业品累计同比（%） |
| ppirm_yoy | float | PPIRM：原材料当月同比（%） |
| ppirm_mp | float | PPIRM：原材料环比（%） |
| ppirm_quart | float | PPIRM：原材料季比（%） |
| ppirm_same | float | PPIRM：原材料累计同比（%） |

---

### 5.4 货币供应量 `cn_m`

**文档**：https://tushare.pro/document/2?doc_id=111  
**接口**：`pro.cn_m()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| m | str | 否 | 月份（YYYYMM） |
| start_m | str | 否 | 开始月份 |
| end_m | str | 否 | 结束月份 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| month | str | 月份 |
| m0 | float | M0（亿元） |
| m0_yoy | float | M0同比增速（%） |
| m0_mom | float | M0环比增速（%） |
| m1 | float | M1（亿元） |
| m1_yoy | float | M1同比增速（%） |
| m1_mom | float | M1环比增速（%） |
| m2 | float | M2（亿元） |
| m2_yoy | float | M2同比增速（%） |
| m2_mom | float | M2环比增速（%） |

---

## 6. 参考数据

### 6.1 股权质押统计 `pledge_stat`

**文档**：https://tushare.pro/document/2?doc_id=208  
**接口**：`pro.pledge_stat()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| end_date | str | 否 | 截止日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| end_date | str | 截止日期 |
| pledge_count | int | 质押次数 |
| unrest_pledge | float | 无限售股质押数量（万股） |
| rest_pledge | float | 限售股份质押数量（万股） |
| total_share | float | 总股本（万股） |
| pledge_ratio | float | 质押比例（%） |

---

### 6.2 股权质押明细 `pledge_detail`

**文档**：https://tushare.pro/document/2?doc_id=209  
**接口**：`pro.pledge_detail()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 是 | 股票代码 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| holder_name | str | 股东名称 |
| pledge_amount | float | 质押数量（万股） |
| start_date | str | 质押开始日期 |
| end_date | str | 质押结束日期 |
| is_release | str | 是否已解押（1=是，0=否） |
| release_date | str | 解押日期 |
| pledgor | str | 质押方（质押给谁） |
| holding_amount | float | 持股总量（万股） |
| pledged_amount | float | 质押总量（万股） |
| p_total_ratio | float | 本次质押占总股本比例（%） |
| h_total_ratio | float | 持股总量占总股本比例（%） |
| is_buyback | str | 是否回购质押（1=是，0=否） |

---

### 6.3 限售股解禁 `share_float`

**文档**：https://tushare.pro/document/2?doc_id=160  
**接口**：`pro.share_float()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| ann_date | str | 否 | 公告日期 |
| float_date | str | 否 | 解禁日期 |
| start_date | str | 否 | 解禁开始日期 |
| end_date | str | 否 | 解禁结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| float_date | str | 解禁日期 |
| float_share | float | 流通股份（万股） |
| float_ratio | float | 流通股份占总股本比例（%） |
| holder_name | str | 股东名称 |
| share_type | str | 股份类型 |

#### 示例

```python
# 获取未来30天内解禁情况
import datetime
today = datetime.date.today().strftime('%Y%m%d')
future = (datetime.date.today() + datetime.timedelta(days=30)).strftime('%Y%m%d')
df = pro.share_float(start_date=today, end_date=future)
```

---

### 6.4 股票回购 `repurchase`

**文档**：https://tushare.pro/document/2?doc_id=161  
**接口**：`pro.repurchase()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| ann_date | str | 否 | 公告日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| end_date | str | 截止日期 |
| proc | str | 进度（预案/董事会预案/股东大会通过/实施中/完成） |
| exp_date | str | 过期日期 |
| vol | float | 回购数量（万股） |
| amount | float | 回购金额（万元） |
| high_limit | float | 回购最高价格（元） |
| low_limit | float | 回购最低价格（元） |

---

### 6.5 大股东增减持 `holder_trade`

**文档**：https://tushare.pro/document/2?doc_id=175  
**接口**：`pro.holder_trade()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| ann_date | str | 否 | 公告日期 |
| start_date | str | 否 | 公告开始日期 |
| end_date | str | 否 | 公告结束日期 |
| trade_type | str | 否 | 交易类型：`IN`（增持）/ `DE`（减持） |
| holder_type | str | 否 | 股东类型：`C`（高管）/ `G`（大股东）/ `P`（大股东及高管） |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| holder_name | str | 股东名称 |
| holder_type | str | 股东类型（G=大股东，C=高管） |
| in_de | str | 增减持类型（IN=增持，DE=减持） |
| change_vol | float | 变动数量（万股） |
| change_ratio | float | 占流通总股数的比例（%） |
| after_share | float | 变动后持股数量（万股） |
| after_ratio | float | 变动后持股比例（%） |
| avg_price | float | 平均交易价格（元） |
| total_share | float | 变动总股本（万股） |
| begin_date | str | 增减持计划开始日期 |
| close_date | str | 增减持计划结束日期 |

---

### 6.6 龙虎榜每日明细 `top_list`

**文档**：https://tushare.pro/document/2?doc_id=105  
**接口**：`pro.top_list()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| trade_date | str | 二选一 | 交易日期 |
| ts_code | str | 二选一 | 股票代码 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | str | 交易日期 |
| ts_code | str | 股票代码 |
| name | str | 股票名称 |
| close | float | 收盘价（元） |
| pct_change | float | 涨跌幅（%） |
| turnover_rate | float | 换手率（%） |
| amount | float | 成交额（元） |
| l_sell | float | 龙虎榜卖出额（元） |
| l_buy | float | 龙虎榜买入额（元） |
| l_amount | float | 龙虎榜成交额（元） |
| net_amount | float | 龙虎榜净买入额（元） |
| net_rate | float | 净买入额占比（%） |
| amount_rate | float | 成交额占比（%） |
| float_values | float | 流通市值（元） |
| reason | str | 上榜理由 |

---

### 6.7 龙虎榜机构明细 `top_inst`

**文档**：https://tushare.pro/document/2?doc_id=106  
**接口**：`pro.top_inst()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| trade_date | str | 二选一 | 交易日期 |
| ts_code | str | 二选一 | 股票代码 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | str | 交易日期 |
| ts_code | str | 股票代码 |
| exalter | str | 营业部名称 |
| buy | float | 买入额（元） |
| buy_rate | float | 买入占总成交比例（%） |
| sell | float | 卖出额（元） |
| sell_rate | float | 卖出占总成交比例（%） |
| net_buy | float | 净买入（元） |

---

### 6.8 融资融券汇总 `margin`

**文档**：https://tushare.pro/document/2?doc_id=58  
**接口**：`pro.margin()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| trade_date | str | 否 | 交易日期 |
| exchange_id | str | 否 | 交易所：`SSE`/`SZSE`/`BSE` |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | str | 交易日期 |
| exchange_id | str | 交易所代码 |
| rzye | float | 融资余额（元） |
| rqye | float | 融券余额（元） |
| rzmre | float | 融资买入额（元） |
| rqyl | float | 融券余量（股） |
| rzche | float | 融资偿还额（元） |
| rqche | float | 融券偿还量（股） |
| rqmre | float | 融券卖出量（股） |
| rzrqye | float | 融资融券余额（元） |
| rzrqyecz | float | 融资融券余额差值（元） |

---

### 6.9 融资融券明细 `margin_detail`

**文档**：https://tushare.pro/document/2?doc_id=59  
**接口**：`pro.margin_detail()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | str | 交易日期 |
| ts_code | str | 股票代码 |
| name | str | 股票名称 |
| rzye | float | 融资余额（元） |
| rqye | float | 融券余额（元） |
| rzmre | float | 融资买入额（元） |
| rqyl | float | 融券余量（股） |
| rzche | float | 融资偿还额（元） |
| rqche | float | 融券偿还量（股） |
| rqmre | float | 融券卖出量（股） |
| rzrqye | float | 融资融券余额（元） |

---

## 7. 港股数据

### 7.1 港股基本信息 `hk_basic`

**文档**：https://tushare.pro/document/2?doc_id=211  
**接口**：`pro.hk_basic()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码（如 `00700.HK`） |
| list_status | str | 否 | 上市状态：`L`/`D`/`P` |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | TS代码（如 `00700.HK`） |
| name | str | 中文名称 |
| fullname | str | 公司全称 |
| enname | str | 英文名称 |
| cn_spell | str | 中文拼音 |
| market | str | 市场类型（主板/创业板） |
| list_status | str | 上市状态 |
| list_date | str | 上市日期 |
| delist_date | str | 退市日期 |
| trade_unit | float | 买卖单位（每手股数） |
| isin | str | ISIN代码 |
| curr_type | str | 货币类型（HKD/USD） |

---

### 7.2 港股日线行情 `hk_daily`

**文档**：https://tushare.pro/document/2?doc_id=221  
**接口**：`pro.hk_daily()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| ts_code | str | 否 | 股票代码 |
| trade_date | str | 否 | 交易日期 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 交易日期 |
| open | float | 开盘价（港元） |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| pre_close | float | 昨收价 |
| change | float | 涨跌额 |
| pct_chg | float | 涨跌幅（%） |
| vol | float | 成交量（股） |
| amount | float | 成交额（港元） |

---

## 8. 期货 / 期权数据

### 8.1 期货合约信息 `fut_basic`

**文档**：https://tushare.pro/document/2?doc_id=135  
**接口**：`pro.fut_basic()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| exchange | str | 是 | 交易所：`CFFEX`/`DCE`/`CZCE`/`SHFE`/`INE`/`GFEX` |
| fut_type | str | 否 | 合约类型：`1`（普通）/ `2`（主力合约） |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 合约代码 |
| symbol | str | 合约简称 |
| exchange | str | 交易所 |
| name | str | 中文简称 |
| fut_code | str | 合约产品代码 |
| multiplier | float | 合约乘数 |
| trade_unit | str | 交易计量单位 |
| per_unit | float | 交易单位（每手） |
| quote_unit | str | 报价单位 |
| list_date | str | 上市日期 |
| delist_date | str | 最后交易日期 |
| d_month | str | 交割月份 |
| last_ddate | str | 最后交割日 |
| trade_time_desc | str | 交易时间说明 |

#### 示例

```python
# 获取中金所所有期货合约
df = pro.fut_basic(exchange='CFFEX', fut_type='1')
```

---

### 8.2 期货日线行情 `fut_daily`

**文档**：https://tushare.pro/document/2?doc_id=138  
**接口**：`pro.fut_daily()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| trade_date | str | 二选一 | 交易日期 |
| ts_code | str | 二选一 | 合约代码 |
| exchange | str | 否 | 交易所 |
| start_date | str | 否 | 开始日期 |
| end_date | str | 否 | 结束日期 |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 合约代码 |
| trade_date | str | 交易日期 |
| pre_close | float | 昨收盘价 |
| pre_settle | float | 昨结算价 |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| settle | float | 结算价 |
| change1 | float | 涨跌1（收盘价 - 昨结算价） |
| change2 | float | 涨跌2（结算价 - 昨结算价） |
| vol | float | 成交量（手） |
| amount | float | 成交金额（万元） |
| oi | float | 持仓量（手） |
| oi_chg | float | 持仓量变化 |
| delv_settle | float | 交割结算价 |

---

### 8.3 期权合约信息 `opt_basic`

**文档**：https://tushare.pro/document/2?doc_id=158  
**接口**：`pro.opt_basic()`

#### 输入参数

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| exchange | str | 否 | 交易所：`SSE`/`SZSE`/`CFFEX`/`DCE`/`CZCE`/`SHFE` |
| call_put | str | 否 | 期权类型：`C`（认购）/ `P`（认沽） |

#### 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 合约代码 |
| exchange | str | 交易所 |
| name | str | 合约名称 |
| per_unit | float | 合约单位 |
| opt_code | str | 标准合约代码 |
| opt_type | str | 合约类型（ETF期权/股指期权） |
| call_put | str | 认购/认沽 |
| exercise_type | str | 行权方式（欧式/美式） |
| exercise_price | float | 行权价格（元） |
| s_month | str | 结算月份 |
| maturity_date | str | 到期日 |
| list_price | float | 挂牌基准价 |
| list_date | str | 首个交易日 |
| delist_date | str | 最后交易日 |
| last_edate | str | 最后行权日 |
| last_ddate | str | 最后交割日 |
| quote_unit | str | 报价单位 |
| min_price_chg | str | 最小价格变动单位 |

---

## 9. 实践建议

### 9.1 批量拉取全市场日线数据

```python
import tushare as ts
import pandas as pd
import time

pro = ts.pro_api("YOUR_TOKEN")

# 获取所有A股代码
stocks = pro.stock_basic(list_status='L', fields='ts_code')
ts_codes = stocks['ts_code'].tolist()

all_data = []
for code in ts_codes:
    df = pro.daily(ts_code=code, start_date='20240101', end_date='20241231')
    if df is not None and not df.empty:
        all_data.append(df)
    time.sleep(0.05)  # 避免频率限制

result = pd.concat(all_data, ignore_index=True)
```

### 9.2 按交易日批量获取（适合高积分账户）

```python
# 获取某日所有股票行情，按日期循环
trade_dates = pro.trade_cal(start_date='20240101', end_date='20241231',
                            is_open='1')['cal_date'].tolist()

all_data = []
for d in trade_dates:
    df = pro.daily(trade_date=d)
    if df is not None:
        all_data.append(df)
    time.sleep(0.1)
```

### 9.3 财务数据获取策略

```python
# 获取最新一期年报，按季度增量更新
def get_latest_financials(ts_code):
    income = pro.income(ts_code=ts_code, report_type='1',
                        fields='ts_code,ann_date,end_date,total_revenue,n_income_attr_p,basic_eps')
    # 只取年报（end_date结尾为1231）
    income = income[income['end_date'].str.endswith('1231')]
    return income.sort_values('end_date', ascending=False)
```

### 9.4 错误处理与重试

```python
import time

def safe_call(func, max_retry=3, **kwargs):
    for i in range(max_retry):
        try:
            df = func(**kwargs)
            if df is not None:
                return df
        except Exception as e:
            if 'limit' in str(e).lower() or '频率' in str(e):
                time.sleep(60)  # 触发频率限制时等待1分钟
            else:
                print(f"Error: {e}")
                time.sleep(1)
    return None
```

---

## 10. 字段单位速查

| 数据类型 | 金额单位 | 股数单位 |
|---------|---------|---------|
| 日线行情 | 千元（amount） | 手（vol） |
| 利润表/资产负债/现金流 | 元 | — |
| 融资融券 | 元 | 股 |
| 龙虎榜 | 元 | — |
| 增减持 | — | 万股 |
| 解禁 | — | 万股 |
| 质押 | — | 万股 |
| 期货行情 | 万元（amount） | 手（vol/oi） |
| 港股行情 | 港元 | 股 |

---

## 11. 权限积分参考

| API | 最低积分 | 备注 |
|-----|---------|------|
| stock_basic | 0 | 免费 |
| trade_cal | 0 | 免费 |
| daily / weekly / monthly | 2000 | 单股全历史 |
| income / balancesheet / cashflow | 2000 | 三大报表 |
| cn_gdp / cn_cpi / cn_ppi / cn_m | 2000 | 宏观数据 |
| namechange / hs_const | 2000 | 基础参考 |
| adj_factor | 2000 | 复权因子 |
| suspend_d | 2000 | 停复牌 |
| stk_limit | 2000 | 每日涨跌停价格，单次 5800 条 |
| share_float / repurchase | 2000 | 解禁/回购 |
| holder_trade | 2000 | 增减持 |
| pledge_stat / pledge_detail | 2000 | 质押数据 |
| top_list / top_inst | 2000 | 龙虎榜 |
| margin / margin_detail | 2000 | 融资融券 |
| hk_basic / hk_daily | 2000 | 港股数据 |
| fut_basic / fut_daily | 2000 | 期货数据 |
| opt_basic | 2000 | 期权数据 |
