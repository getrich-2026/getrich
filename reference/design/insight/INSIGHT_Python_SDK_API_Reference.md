# 华泰证券 INSIGHT Python SDK — 开发参考文档

> **版本**：适用于 insight-python-win / insight-python-linux（主流版本）  
> **数据字典版本**：Schema 3.2.8 / 3.2.11  
> **维护说明**：官方文档入口 https://findata-insight.htsc.com:9151/insight_help/  
> **申请试用**：联系华泰客户经理或发邮件至 digi_tech_supp@htsc.com

---

## 目录

1. [产品概述](#1-产品概述)
2. [安装与环境](#2-安装与环境)
3. [核心架构](#3-核心架构)
4. [连接与认证](#4-连接与认证)
5. [实时行情订阅（Push 模式）](#5-实时行情订阅push-模式)
6. [数据回放（历史回测）](#6-数据回放历史回测)
7. [Query 数据查询服务](#7-query-数据查询服务)
8. [回调接口说明](#8-回调接口说明)
9. [枚举类型与常量](#9-枚举类型与常量)
10. [数据字段说明](#10-数据字段说明)
11. [倍率转换规则](#11-倍率转换规则)
12. [回放限额规则](#12-回放限额规则)
13. [错误处理](#13-错误处理)
14. [完整使用示例](#14-完整使用示例)
15. [常见问题](#15-常见问题)

---

## 1. 产品概述

INSIGHT 是华泰证券依托大数据存储、实时分析等领域的技术积累，整合接入国内多家交易所高频行情数据，为投资者提供集**行情接入、推送、回测、计算及分析**等功能于一体的行情数据服务解决方案。

**主要能力**：

| 能力 | 说明 |
|------|------|
| 实时行情推送 | 交易所非展示类 Level-2 行情，包含逐笔委托、逐笔成交、快照 |
| 历史数据回放 | 支持 Tick / 分钟 K 线 / 日 K 线历史数据，最早可回放至 2017-01-02 |
| Query 查询服务 | 7×24 小时极速查询：量化因子、财务数据、衍生指标等 |
| 多市场覆盖 | 沪深两市股票、指数、债券、基金、期权；中金所股指/国债期货；商品期货等 |

**两种 Python SDK 形态**：

```
insight-python-win   # Windows 平台
insight-python-linux # Linux 平台（服务器首选）
```

---

## 2. 安装与环境

### 2.1 安装

```bash
# Windows
pip install insight-python-win
# 使用国内镜像加速
pip install insight-python-win -i https://pypi.tuna.tsinghua.edu.cn/simple

# Linux
pip install insight-python-linux
pip install insight-python-linux -i https://pypi.tuna.tsinghua.edu.cn/simple

# 指定安装目录（用于隔离环境）
pip install --target=/opt/insight insight-python-linux
```

### 2.2 验证安装

```python
import insight
print(insight.__version__)
```

### 2.3 环境要求

- Python：3.7 及以上（64-bit）
- 操作系统：Windows 7+（64-bit）/ Linux x86_64
- 网络：需要能访问华泰 INSIGHT 服务器（通常需要托管机房或专线）
- 认证：需从华泰证券获取专用账号（username / password）

---

## 3. 核心架构

INSIGHT Python SDK 由两个独立的服务 SDK 组成，分别承担不同职责：

```
┌─────────────────────────────────────────────────────┐
│                INSIGHT Python SDK                   │
│                                                     │
│  ┌──────────────────────┐  ┌─────────────────────┐  │
│  │   行情服务 SDK       │  │  Query 查询 SDK     │  │
│  │  (MDL / TCP 版本)   │  │  (HTTP/TCP Query)   │  │
│  │                      │  │                     │  │
│  │  - 实时行情推送      │  │  - 历史因子查询     │  │
│  │  - 历史数据回放      │  │  - 财务数据查询     │  │
│  │  - Callback 回调     │  │  - request_query()  │  │
│  └──────────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**核心接口模式**：

- 行情 SDK 采用**事件回调**（Callback）模式，数据到达时触发用户注册的回调函数
- Query SDK 采用**同步请求-响应**模式，调用 `request_query()` 直接返回结果

---

## 4. 连接与认证

### 4.1 创建客户端并连接

```python
from insight.api import InsightClient  # 实际导入路径以安装包为准

# 创建客户端实例
client = InsightClient()

# 连接到主服务器
client.connect(
    host="<服务器IP>",       # str，主服务器地址（由华泰提供）
    port=<端口号>,            # int，服务器端口（由华泰提供）
    username="<账号>",        # str，华泰分配的账号
    password="<密码>",        # str，对应密码
)
```

### 4.2 带备份服务器的高可用连接

生产环境强烈建议配置备份服务器列表，确保行情接入高可用：

```python
client.connect(
    host="192.168.1.100",
    port=10317,
    username="your_username",
    password="your_password",
    backup_servers=[                    # list[str]，格式 "IP:PORT"
        "192.168.1.101:10317",
        "192.168.1.102:10317",
    ],
    worker_num=5,                       # int，处理线程数，默认 5，范围 1-32767
)
```

### 4.3 连接参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `host` | `str` | 是 | 主服务器 IP 地址 |
| `port` | `int` | 是 | 服务器端口 |
| `username` | `str` | 是 | 华泰分配的账号 |
| `password` | `str` | 是 | 账号对应密码 |
| `backup_servers` | `list[str]` | 否 | 备份服务器列表，格式 `"IP:PORT"` |
| `worker_num` | `int` | 否 | 线程池线程数，默认 5 |
| `cert_dir_path` | `str` | 否 | SSL 证书目录路径，不填则自动搜索 |
| `data_version` | `str` | 否 | 数据字典版本，支持 `"3.2.8"` / `"3.2.11"` |
| `received_time` | `bool` | 否 | 是否附加插件收到数据的时间戳，默认 True |
| `output_elapsed` | `bool` | 否 | 是否附加数据处理时延（纳秒），默认 False |

### 4.4 注册回调处理器

```python
# 必须在 subscribe 之前注册回调
client.set_handler(your_handler_instance)
```

### 4.5 断开连接

```python
client.close()        # 断开连接并释放资源
client.unsubscribe()  # 仅取消订阅，不断开连接
```

---

## 5. 实时行情订阅（Push 模式）

### 5.1 subscribe 接口

```python
client.subscribe(
    market_data_types,   # list[str]，行情数据类型列表
    security_id_source,  # str，交易所代码
    security_type,       # str，产品类型
)
```

**参数详解**：

#### market_data_types（行情数据类型）

| 值 | 说明 |
|----|------|
| `"MD_TICK"` | 快照行情（Level-2 盘口 + 成交统计） |
| `"MD_ORDER"` | 逐笔委托（每一笔委托单） |
| `"MD_TRANSACTION"` | 逐笔成交（每一笔成交记录） |
| `"MD_ORDER_TRANSACTION"` | 逐笔合成（Order + Transaction 的合并流，特殊类型） |
| `"MD_SECURITY_LENDING"` | 融券通数据 |

#### security_id_source（交易所代码）

| 值 | 交易所 |
|----|--------|
| `"XSHG"` | 上海证券交易所 |
| `"XSHE"` | 深圳证券交易所 |
| `"CCFX"` | 中国金融期货交易所（中金所） |
| `"XDCE"` | 大连商品交易所 |
| `"XSGE"` | 上海期货交易所 |
| `"XZCE"` | 郑州商品交易所 |
| `"XBSE"` | 北京证券交易所 |
| `"CSI"` | 中证指数公司 |
| `"NEEQ"` | 全国股转系统（新三板） |
| `"HKSC"` | 港股通（沪港通） |
| `"HGHQ"` | 港股通（深港通） |
| `"CNI"` | 国证指数 |

#### security_type（产品类型）

| 值 | 说明 |
|----|------|
| `"StockType"` | 股票 |
| `"FundType"` | 基金（ETF、LOF 等） |
| `"BondType"` | 债券 |
| `"IndexType"` | 指数 |
| `"FuturesType"` | 期货 |
| `"OptionType"` | 期权 |

### 5.2 订阅示例

```python
# 订阅上交所全市场股票快照 + 逐笔
client.subscribe(
    market_data_types=["MD_TICK", "MD_ORDER", "MD_TRANSACTION"],
    security_id_source="XSHG",
    security_type="StockType",
)

# 订阅深交所基金快照
client.subscribe(
    market_data_types=["MD_TICK"],
    security_id_source="XSHE",
    security_type="FundType",
)

# 订阅中金所期货快照
client.subscribe(
    market_data_types=["MD_TICK"],
    security_id_source="CCFX",
    security_type="FuturesType",
)

# 订阅上交所股票期权
client.subscribe(
    market_data_types=["MD_TICK", "MD_ORDER", "MD_TRANSACTION"],
    security_id_source="XSHG",
    security_type="OptionType",
)
```

### 5.3 取消订阅

```python
client.unsubscribe()  # 取消当前所有订阅
```

---

## 6. 数据回放（历史回测）

数据回放功能基于行情 SDK 实现，允许按时间段请求历史行情数据（最早至 2017-01-02）。回放数据通过与实时行情相同的回调接口推送，用于历史数据下载和回测场景。

### 6.1 回放接口

```python
client.subscribe_replay(
    market_data_types,   # list[str]，同实时订阅的数据类型
    security_id_source,  # str，交易所代码
    security_type,       # str，产品类型
    security_ids,        # list[str]，标的代码列表，如 ["600000", "000001"]
    begin_time,          # str，开始时间，格式 "YYYYMMDD HHmmss" 或 "YYYYMMDD"
    end_time,            # str，结束时间，格式同上
)
```

### 6.2 回放示例

```python
# 回放沪市贵州茅台最近 5 个交易日的 Tick 数据
client.subscribe_replay(
    market_data_types=["MD_TICK"],
    security_id_source="XSHG",
    security_type="StockType",
    security_ids=["600519"],
    begin_time="20240101",
    end_time="20240105",
)

# 回放深市一批股票的分钟 K 线（需确认具体 K 线接口参数）
client.subscribe_replay(
    market_data_types=["MD_TICK"],   # K 线通过 Query SDK 获取更方便
    security_id_source="XSHE",
    security_type="StockType",
    security_ids=["000001", "000002", "300750"],
    begin_time="20231201 093000",
    end_time="20231201 150000",
)
```

---

## 7. Query 数据查询服务

Query SDK 提供 7×24 小时的离线数据查询能力，返回 JSON 格式数据。适用于获取历史 K 线、财务数据、量化因子等非实时数据。

### 7.1 连接 Query 服务器

Query 服务使用独立的服务器地址和认证，需单独连接：

```python
from insight.api import QueryClient  # 具体类名以实际 SDK 为准

query_client = QueryClient()
query_client.connect(
    server="<query服务器地址:端口>",   # 格式 "IP:PORT"，由华泰单独提供
    username="<query账号>",
    password="<query密码>",
)
```

### 7.2 request_query 接口

```python
result = query_client.request_query(
    query_type,    # int 或 str，查询类型编号（见数据字典）
    query_params,  # dict，查询参数（见各 queryType 定义）
)
# 返回值：JSON 格式，通常为 dict 或 list
```

### 7.3 通用查询参数

大多数 queryType 支持以下通用参数：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `HTSC_SECURITY_ID` | `str` | 标的代码（华泰标准格式，如 `"600519.SH"` 或 `"600519"`） |
| `START_DATE` | `str` | 查询起始日期，格式 `"YYYYMMDD"` |
| `END_DATE` | `str` | 查询结束日期，格式 `"YYYYMMDD"` |
| `TRADING_DATE` | `str` | 指定单个交易日，格式 `"YYYYMMDD"` |

### 7.4 常用 queryType 示例

> **重要**：具体 queryType 编号和字段需查阅华泰 INSIGHT 官方数据字典。以下为已知示例。

#### AlphaNet 因子查询

```python
result = query_client.request_query(
    query_type=1401010003,       # AlphaNet 因子
    query_params={
        "HTSC_SECURITY_ID": "600519",    # 标的代码
        "START_DATE": "20230101",        # 起始日期
        "END_DATE": "20231231",          # 结束日期
    }
)
```

#### 日 K 线数据（示例）

```python
result = query_client.request_query(
    query_type=<日K线queryType>,
    query_params={
        "HTSC_SECURITY_ID": "000001.SZ",
        "START_DATE": "20230101",
        "END_DATE": "20231231",
        "FIELDS": "open,high,low,close,volume,amount",  # 按需选择字段
    }
)
```

#### 分钟 K 线数据（示例）

```python
result = query_client.request_query(
    query_type=<分钟K线queryType>,
    query_params={
        "HTSC_SECURITY_ID": "600519.SH",
        "START_DATE": "20231201",
        "END_DATE": "20231201",
        "INTERVAL": "1",        # 1分钟，或 5、15、30、60
    }
)
```

### 7.5 结果解析

```python
import json

result = query_client.request_query(query_type=..., query_params={...})

# 结果通常为 JSON 字符串或已解析的 dict/list
if isinstance(result, str):
    data = json.loads(result)
else:
    data = result

# 常见结构示例
for record in data.get("data", []):
    security_id = record.get("HTSC_SECURITY_ID")
    trade_date  = record.get("TRADE_DATE")
    close_price = record.get("CLOSE_PRICE")
    print(f"{security_id} {trade_date}: {close_price}")
```

---

## 8. 回调接口说明

实时行情和回放数据均通过回调推送。需继承基类并重写对应方法：

```python
class InsightHandler:
    """用户需继承此基类并实现所需回调方法"""

    def on_stock_tick(self, tick_data):
        """股票快照回调（StockTick）"""
        pass

    def on_index_tick(self, tick_data):
        """指数快照回调（IndexTick）"""
        pass

    def on_futures_tick(self, tick_data):
        """期货快照回调（FuturesTick）"""
        pass

    def on_fund_tick(self, tick_data):
        """基金快照回调（FundTick）"""
        pass

    def on_bond_tick(self, tick_data):
        """债券快照回调（BondTick）"""
        pass

    def on_option_tick(self, tick_data):
        """期权快照回调（OptionTick）"""
        pass

    def on_order(self, order_data):
        """逐笔委托回调（Order）"""
        pass

    def on_transaction(self, transaction_data):
        """逐笔成交回调（Transaction）"""
        pass

    def on_order_transaction(self, order_transaction_data):
        """逐笔合成回调（OrderTransaction）"""
        pass

    def on_security_lending(self, lending_data):
        """融券通数据回调（SecurityLending）"""
        pass

    def on_status(self, status):
        """连接状态变化回调"""
        pass

    def on_error(self, error_msg):
        """错误回调"""
        pass
```

### 8.1 用户处理器实现示例

```python
class MyMarketHandler(InsightHandler):

    def __init__(self):
        self.tick_count = 0

    def on_stock_tick(self, tick):
        """
        tick 属性（快照数据常用字段）：
          tick.security_id         证券代码
          tick.date_time           行情时间（datetime 对象）
          tick.last_price          最新价（注意倍率，见第 11 节）
          tick.open_price          今开盘价
          tick.high_price          今最高价
          tick.low_price           今最低价
          tick.close_price         今收盘价（收盘后）
          tick.pre_close_price     昨收盘价
          tick.total_volume        成交总量
          tick.total_value         成交总额
          tick.ask_prices[0-9]     卖一到卖十价格（list）
          tick.ask_volumes[0-9]    卖一到卖十量（list）
          tick.bid_prices[0-9]     买一到买十价格（list）
          tick.bid_volumes[0-9]    买一到买十量（list）
          tick.recv_time           SDK 收到数据的时间戳（如开启 received_time）
        """
        self.tick_count += 1
        # 注意：价格字段需除以倍率（通常为 10000），详见第 11 节
        real_price = tick.last_price / 10000
        print(f"[TICK] {tick.security_id} 最新价: {real_price:.4f} | 累计: {self.tick_count}")

    def on_order(self, order):
        """
        order 属性（逐笔委托常用字段）：
          order.security_id        证券代码
          order.date_time          委托时间
          order.order_no           委托编号
          order.order_type         委托类型（'B'=买, 'S'=卖, '...）
          order.price              委托价格（需除以倍率）
          order.volume             委托量
          order.channel            通道号
          order.appl_seq_num       序列号（用于合并逐笔）
        """
        pass

    def on_transaction(self, trans):
        """
        trans 属性（逐笔成交常用字段）：
          trans.security_id        证券代码
          trans.date_time          成交时间
          trans.exec_type          成交类型（'F'=成交, '4'=撤单等）
          trans.trade_price        成交价格（需除以倍率）
          trans.trade_volume       成交量
          trans.bid_appl_seq_num   买方委托序列号
          trans.ask_appl_seq_num   卖方委托序列号
        """
        pass

    def on_status(self, status):
        print(f"[STATUS] 连接状态变化: {status}")

    def on_error(self, error_msg):
        print(f"[ERROR] {error_msg}")
```

---

## 9. 枚举类型与常量

### 9.1 数据类型枚举（EMarketDataType）

```python
class EMarketDataType:
    MD_TICK              = "MD_TICK"             # 快照
    MD_ORDER             = "MD_ORDER"            # 逐笔委托
    MD_TRANSACTION       = "MD_TRANSACTION"      # 逐笔成交
    MD_ORDER_TRANSACTION = "MD_ORDER_TRANSACTION"# 逐笔合成
    MD_SECURITY_LENDING  = "MD_SECURITY_LENDING" # 融券通
```

### 9.2 交易所枚举（ESecurityIDSource）

```python
class ESecurityIDSource:
    XSHG = "XSHG"   # 上交所
    XSHE = "XSHE"   # 深交所
    CCFX = "CCFX"   # 中金所
    XDCE = "XDCE"   # 大商所
    XSGE = "XSGE"   # 上期所
    XZCE = "XZCE"   # 郑商所
    XBSE = "XBSE"   # 北交所
    CSI  = "CSI"    # 中证指数
    NEEQ = "NEEQ"   # 新三板
    HKSC = "HKSC"   # 港股通（沪）
    HGHQ = "HGHQ"   # 港股通（深）
    CNI  = "CNI"    # 国证指数
```

### 9.3 产品类型枚举（ESecurityType）

```python
class ESecurityType:
    StockType   = "StockType"
    FundType    = "FundType"
    BondType    = "BondType"
    IndexType   = "IndexType"
    FuturesType = "FuturesType"
    OptionType  = "OptionType"
```

### 9.4 逐笔委托类型

| 值 | 说明 |
|----|------|
| `'B'` / `1` | 买入委托 |
| `'S'` / `2` | 卖出委托 |
| `'C'` / `'U'` | 撤销委托（视交易所而定） |

### 9.5 逐笔成交类型（ExecType）

| 值 | 说明 |
|----|------|
| `'F'` / `52` | 成交 |
| `'4'` / `52` | 撤单（深交所） |
| `'C'` | 撤销（部分场所） |

---

## 10. 数据字段说明

### 10.1 股票 / 基金 / 债券快照（Tick）核心字段

| 字段名 | 类型 | 说明 | 倍率 |
|--------|------|------|------|
| `security_id` | str | 证券代码 | — |
| `security_id_source` | str | 交易所代码 | — |
| `date_time` | datetime | 行情时间 | — |
| `last_price` | int | 最新价 | ×10,000 |
| `open_price` | int | 今开盘价 | ×10,000 |
| `high_price` | int | 今最高价 | ×10,000 |
| `low_price` | int | 今最低价 | ×10,000 |
| `pre_close_price` | int | 昨收盘价 | ×10,000 |
| `upper_limit_price` | int | 涨停价 | ×10,000 |
| `lower_limit_price` | int | 跌停价 | ×10,000 |
| `total_volume` | int | 成交总量（股） | — |
| `total_value` | int | 成交总额（元） | ×10,000（沪） / ×10（深） |
| `ask_price_[1-10]` | int | 卖[N]价 | ×10,000 |
| `ask_volume_[1-10]` | int | 卖[N]量 | — |
| `bid_price_[1-10]` | int | 买[N]价 | ×10,000 |
| `bid_volume_[1-10]` | int | 买[N]量 | — |

### 10.2 期货快照（FuturesTick）补充字段

| 字段名 | 类型 | 说明 | 倍率 |
|--------|------|------|------|
| `pre_settle_price` | int | 昨结算价 | ×10,000 |
| `settle_price` | int | 今结算价 | ×10,000 |
| `open_interest` | int | 持仓量（手） | — |
| `pre_open_interest` | int | 昨持仓量 | — |

### 10.3 期权快照（OptionTick）补充字段

| 字段名 | 类型 | 说明 | 倍率 |
|--------|------|------|------|
| `settle_price` | int | 结算价 | ×10,000 |
| `pre_settle_price` | int | 昨结算价 | ×10,000 |
| `open_interest` | int | 持仓量 | — |

### 10.4 逐笔委托（Order）核心字段

| 字段名 | 类型 | 说明 | 倍率 |
|--------|------|------|------|
| `security_id` | str | 证券代码 | — |
| `date_time` | datetime | 委托时间 | — |
| `channel` | int | 频道代码 | — |
| `appl_seq_num` | int | 消息序列号 | — |
| `order_type` | str/int | 委托类型 | — |
| `price` | int | 委托价格 | ×10,000 |
| `volume` | int | 委托量（股） | — |
| `order_no` | int | 委托序号 | — |
| `trade_qty` | int | 成交数量（3.2.11 版本新增） | — |

### 10.5 逐笔成交（Transaction）核心字段

| 字段名 | 类型 | 说明 | 倍率 |
|--------|------|------|------|
| `security_id` | str | 证券代码 | — |
| `date_time` | datetime | 成交时间 | — |
| `channel` | int | 频道代码 | — |
| `appl_seq_num` | int | 消息序列号 | — |
| `exec_type` | str/int | 成交类型 | — |
| `trade_price` | int | 成交价格 | ×10,000 |
| `trade_volume` | int | 成交量（股） | — |
| `bid_appl_seq_num` | int | 买方委托序列号 | — |
| `ask_appl_seq_num` | int | 卖方委托序列号 | — |

---

## 11. 倍率转换规则

> ⚠️ **关键**：INSIGHT SDK 返回的所有价格/金额字段均为整数，不进行倍率处理。使用时必须手动转换。

**基本规则**：

| 字段类型 | 倍率 | 转换方式 |
|---------|------|---------|
| 价格（price、open、high、low、close 等） | 10,000 | `real_price = raw_value / 10_000` |
| 成交额（沪市 total_value） | 10,000 | `real_amount = raw_value / 10_000` |
| 成交额（深市 total_value） | 10 | `real_amount = raw_value / 10` |
| 成交量（volume） | 1（无倍率） | 直接使用 |
| 持仓量（期货 open_interest） | 1（无倍率） | 直接使用 |

**转换代码示例**：

```python
PRICE_MULTIPLIER  = 10_000   # 价格倍率（普遍适用）
AMOUNT_MULTIPLIER_SH = 10_000  # 沪市成交额倍率
AMOUNT_MULTIPLIER_SZ = 10      # 深市成交额倍率

def convert_tick(tick, exchange: str) -> dict:
    """将 INSIGHT 原始 Tick 数据转换为实际价格"""
    amount_mult = AMOUNT_MULTIPLIER_SH if exchange == "XSHG" else AMOUNT_MULTIPLIER_SZ
    return {
        "security_id":   tick.security_id,
        "datetime":      tick.date_time,
        "last_price":    tick.last_price / PRICE_MULTIPLIER,
        "open_price":    tick.open_price / PRICE_MULTIPLIER,
        "high_price":    tick.high_price / PRICE_MULTIPLIER,
        "low_price":     tick.low_price  / PRICE_MULTIPLIER,
        "pre_close":     tick.pre_close_price / PRICE_MULTIPLIER,
        "total_volume":  tick.total_volume,   # 无倍率
        "total_amount":  tick.total_value / amount_mult,
        "ask_prices":    [p / PRICE_MULTIPLIER for p in tick.ask_prices],
        "bid_prices":    [p / PRICE_MULTIPLIER for p in tick.bid_prices],
        "ask_volumes":   list(tick.ask_volumes),
        "bid_volumes":   list(tick.bid_volumes),
    }
```

---

## 12. 回放限额规则

INSIGHT 对历史数据回放的时间跨度有严格限制，核心约束为：

```
回放只数 × 回放天数 × 证券权重 ≤ 450
交易时间段内回放（盘中） ≤ 200
```

**各数据类型的证券权重**：

| 数据类型 | 证券权重 | 实际限制（450额度） |
|---------|---------|----------------|
| Tick / Order / Transaction | 1 | 最多 450 只股票×1 天，或 15 只股票×30 天 |
| 分钟 K 线 | 0.05 | 最多 9,000 只股票×1 天，或 100 只股票×90 天 |
| 日 K 线 | 0.005 | 最多 90,000 只股票×1 天，或全市场×365 天 |

**时间范围限制**：

| 数据类型 | 最大时间跨度 | 最早可回放日期 |
|---------|------------|--------------|
| Tick / Transaction / Order | 30 天 | 2017-01-02 |
| 分钟 K 线 | 90 天 | 2017-01-02 |
| 日 K 线 | 365 天 | 2017-01-02 |

**高效使用建议**：

```python
# ✅ 推荐：批量回放，一次订阅多只股票
client.subscribe_replay(
    market_data_types=["MD_TICK"],
    security_id_source="XSHG",
    security_type="StockType",
    security_ids=["600000", "600001", "600002"],  # 批量，效率高
    begin_time="20240101",
    end_time="20240101",  # 控制在权重限制内
)

# ❌ 不推荐：循环单只股票多次调用，浪费额度
for code in stock_list:
    client.subscribe_replay(..., security_ids=[code], ...)  # 低效
```

---

## 13. 错误处理

### 13.1 连接错误

```python
try:
    client.connect(host=..., port=..., username=..., password=...)
except Exception as e:
    print(f"连接失败: {e}")
    # 常见原因：
    # - 网络不通/防火墙拦截
    # - 账号密码错误
    # - 证书路径错误（报 "failed to registHandleAndLogin: create client failed"）
```

### 13.2 序列号检查模式（seqCheckMode）

用于控制逐笔合成（OrderTransaction）数据不连续时的行为：

| 模式 | 值 | 行为 |
|------|----|----|
| `'check'` / `0` | 严格模式 | 数据不连续时停止接收，需人工处理 |
| `'ignoreWithLog'` / `1` | 宽松+日志（默认） | 数据不连续时继续，输出 INFO 日志 |
| `'ignore'` / `2` | 完全忽略 | 数据不连续时继续，不输出日志 |

```python
client.connect(
    ...,
    seq_check_mode=1,   # 推荐生产环境使用 ignoreWithLog
)
```

### 13.3 回调中的异常处理

```python
class RobustHandler(InsightHandler):

    def on_stock_tick(self, tick):
        try:
            self._process_tick(tick)
        except Exception as e:
            import traceback
            print(f"[ERROR] on_stock_tick 处理异常: {e}")
            traceback.print_exc()
            # 不要让回调抛出异常，否则可能影响 SDK 内部状态

    def _process_tick(self, tick):
        # 真正的业务逻辑
        ...
```

---

## 14. 完整使用示例

### 14.1 实时行情接入示例

```python
"""
华泰 INSIGHT 实时行情接入示例
功能：订阅沪深两市全市场股票快照 + 逐笔数据，存储到内存队列
"""
import time
import queue
import threading
from datetime import datetime
from insight.api import InsightClient, InsightHandler  # 导入路径以实际 SDK 为准

PRICE_MULT = 10_000  # 价格倍率

class MarketHandler(InsightHandler):
    """行情处理器"""

    def __init__(self, tick_queue: queue.Queue):
        self.tick_queue = tick_queue
        self.order_queue = queue.Queue(maxsize=100_000)

    def on_stock_tick(self, tick):
        """快照回调 - 转换倍率后入队"""
        record = {
            "type":       "tick",
            "code":       tick.security_id,
            "exchange":   tick.security_id_source,
            "time":       tick.date_time,
            "last":       tick.last_price / PRICE_MULT,
            "open":       tick.open_price / PRICE_MULT,
            "high":       tick.high_price / PRICE_MULT,
            "low":        tick.low_price  / PRICE_MULT,
            "pre_close":  tick.pre_close_price / PRICE_MULT,
            "volume":     tick.total_volume,
            "ask1":       tick.ask_price_1 / PRICE_MULT,
            "bid1":       tick.bid_price_1 / PRICE_MULT,
            "ask1_vol":   tick.ask_volume_1,
            "bid1_vol":   tick.bid_volume_1,
        }
        try:
            self.tick_queue.put_nowait(record)
        except queue.Full:
            pass  # 队列满时丢弃，避免阻塞回调线程

    def on_transaction(self, trans):
        """逐笔成交回调"""
        if trans.exec_type in ('F', 52):  # 有效成交
            record = {
                "type":    "trans",
                "code":    trans.security_id,
                "time":    trans.date_time,
                "price":   trans.trade_price / PRICE_MULT,
                "volume":  trans.trade_volume,
                "seq":     trans.appl_seq_num,
            }
            try:
                self.order_queue.put_nowait(record)
            except queue.Full:
                pass

    def on_order(self, order):
        """逐笔委托回调"""
        pass

    def on_status(self, status):
        print(f"[{datetime.now()}] 连接状态: {status}")

    def on_error(self, error_msg):
        print(f"[{datetime.now()}] 错误: {error_msg}")


def main():
    tick_queue = queue.Queue(maxsize=1_000_000)
    handler = MarketHandler(tick_queue)

    client = InsightClient()
    client.set_handler(handler)

    # 连接（使用实际服务器地址）
    client.connect(
        host="<服务器IP>",
        port=10317,
        username="<账号>",
        password="<密码>",
        backup_servers=["<备份IP>:10317"],
        worker_num=8,
    )

    # 订阅沪深两市股票快照 + 逐笔成交
    client.subscribe(["MD_TICK", "MD_TRANSACTION"], "XSHG", "StockType")
    client.subscribe(["MD_TICK", "MD_TRANSACTION"], "XSHE", "StockType")

    print("行情接入中，按 Ctrl+C 退出...")
    try:
        while True:
            # 消费行情数据
            try:
                data = tick_queue.get(timeout=1)
                # 在此处进行策略计算、存储等操作
                # ...
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        print("正在断开连接...")
    finally:
        client.unsubscribe()
        client.close()


if __name__ == "__main__":
    main()
```

### 14.2 历史数据回放示例

```python
"""
华泰 INSIGHT 历史数据回放示例
功能：回放指定股票池历史 Tick 数据并写入 DuckDB
"""
import duckdb
import threading
from datetime import datetime
from insight.api import InsightClient, InsightHandler

PRICE_MULT = 10_000

class ReplayHandler(InsightHandler):
    """回放数据处理器"""

    def __init__(self, db_path: str):
        self.conn = duckdb.connect(db_path)
        self._init_db()
        self.buffer = []
        self.buffer_lock = threading.Lock()
        self.batch_size = 10_000
        self._done = threading.Event()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tick_data (
                code VARCHAR,
                exchange VARCHAR,
                dt TIMESTAMP,
                last_price DOUBLE,
                open_price DOUBLE,
                high_price DOUBLE,
                low_price  DOUBLE,
                pre_close  DOUBLE,
                total_volume BIGINT,
                total_amount DOUBLE,
                ask1 DOUBLE,
                bid1 DOUBLE,
                ask1_vol BIGINT,
                bid1_vol BIGINT
            )
        """)

    def on_stock_tick(self, tick):
        # 判断是否沪市（影响成交额倍率）
        is_sh = tick.security_id_source == "XSHG"
        amt_mult = 10_000 if is_sh else 10

        row = (
            tick.security_id,
            tick.security_id_source,
            tick.date_time,
            tick.last_price  / PRICE_MULT,
            tick.open_price  / PRICE_MULT,
            tick.high_price  / PRICE_MULT,
            tick.low_price   / PRICE_MULT,
            tick.pre_close_price / PRICE_MULT,
            tick.total_volume,
            tick.total_value / amt_mult,
            tick.ask_price_1 / PRICE_MULT,
            tick.bid_price_1 / PRICE_MULT,
            tick.ask_volume_1,
            tick.bid_volume_1,
        )
        with self.buffer_lock:
            self.buffer.append(row)
            if len(self.buffer) >= self.batch_size:
                self._flush()

    def _flush(self):
        """批量写入 DuckDB（调用时须持有 buffer_lock）"""
        if not self.buffer:
            return
        self.conn.executemany(
            "INSERT INTO tick_data VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            self.buffer
        )
        self.buffer.clear()

    def finalize(self):
        """回放结束后调用，写入剩余数据"""
        with self.buffer_lock:
            self._flush()
        self.conn.close()


def replay_ticks(
    host: str,
    port: int,
    username: str,
    password: str,
    security_ids: list[str],
    begin_date: str,
    end_date: str,
    db_path: str = "ticks.duckdb",
):
    handler = ReplayHandler(db_path)
    client = InsightClient()
    client.set_handler(handler)
    client.connect(host=host, port=port, username=username, password=password)

    client.subscribe_replay(
        market_data_types=["MD_TICK"],
        security_id_source="XSHG",
        security_type="StockType",
        security_ids=security_ids,
        begin_time=begin_date,
        end_time=end_date,
    )

    # 等待回放完成（实际需检测回放结束回调或等待固定时间）
    import time
    time.sleep(60)

    client.unsubscribe()
    client.close()
    handler.finalize()
    print(f"回放完成，数据已写入 {db_path}")


if __name__ == "__main__":
    replay_ticks(
        host="<服务器IP>",
        port=10317,
        username="<账号>",
        password="<密码>",
        security_ids=["600519", "000858", "300750"],
        begin_date="20240101",
        end_date="20240105",
        db_path="./tick_replay.duckdb",
    )
```

### 14.3 Query 数据查询示例

```python
"""
使用 INSIGHT Query SDK 查询历史 K 线数据
"""
import json
import pandas as pd
from insight.api import QueryClient  # 具体类名以实际 SDK 为准

def fetch_daily_kline(
    query_client: QueryClient,
    security_id: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    获取日 K 线数据，返回 DataFrame。
    queryType 需替换为华泰数据字典中对应的编号。
    """
    result = query_client.request_query(
        query_type=<日K线queryType>,   # 从华泰数据字典获取
        query_params={
            "HTSC_SECURITY_ID": security_id,
            "START_DATE": start_date,
            "END_DATE": end_date,
        }
    )

    if isinstance(result, str):
        data = json.loads(result)
    else:
        data = result

    records = data.get("data", [])
    df = pd.DataFrame(records)

    # 数值字段转换（具体字段名以数据字典为准）
    price_cols = ["OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "PRE_CLOSE_PRICE"]
    for col in price_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def main():
    client = QueryClient()
    client.connect(
        server="<query服务器:端口>",
        username="<query账号>",
        password="<query密码>",
    )

    df = fetch_daily_kline(
        query_client=client,
        security_id="600519.SH",
        start_date="20230101",
        end_date="20231231",
    )
    print(df.head())
    print(f"共 {len(df)} 条日 K 线数据")
    client.close()


if __name__ == "__main__":
    main()
```

---

## 15. 常见问题

### Q1：连接时报 "create client failed"

**原因**：证书路径未正确配置。SDK 默认在当前节点 Home 目录和 SDK 安装目录搜索证书。

**解决**：
```python
client.connect(
    ...,
    cert_dir_path="/path/to/cert/dir/",  # 明确指定证书目录
)
```

### Q2：价格数据看起来异常（比正常价格大 10000 倍）

**原因**：忘记做倍率转换。INSIGHT 所有价格字段均为整数，需要手动除以 10,000。

**解决**：所有价格字段使用时统一 `/10_000`，建议封装成工具函数（见第 11 节）。

### Q3：订阅深市和沪市成交额不一致

**原因**：沪市成交额倍率为 10,000，深市为 10。需要根据交易所分别转换。

### Q4：回放数据时报额度超限

**原因**：超过了 `回放只数 × 回放天数 × 证券权重 ≤ 450` 的限制。

**解决**：拆分请求，每次减少股票数量或缩短时间范围（见第 12 节）。

### Q5：逐笔数据出现序列号跳变

**原因**：正常现象，网络抖动或服务器端丢包导致。

**建议**：生产环境使用 `seq_check_mode=1`（ignoreWithLog），监控日志中的跳变情况。

### Q6：SDK 在哪里下载？

INSIGHT Python SDK 通过 pip 安装：
- Windows：`pip install insight-python-win`
- Linux：`pip install insight-python-linux`

也可以从华泰提供的官方文档页面 [https://findata-insight.htsc.com:9151/insight_help/sdk/DemoDownload/](https://findata-insight.htsc.com:9151/insight_help/sdk/DemoDownload/) 下载最新版本。

### Q7：数据字典（queryType 编号）在哪里查？

登录华泰 INSIGHT 文档中心 [https://findata-insight.htsc.com:9151/insight_help/python_dataDictionary/DataDictionaryIntro/](https://findata-insight.htsc.com:9151/insight_help/python_dataDictionary/DataDictionaryIntro/)，根据需要查询的数据类型获取对应的 queryType 编号和参数说明。

---

## 附录：Schema 版本差异

| 版本 | 主要差异 |
|------|---------|
| `3.2.8` | 标准版本，包含完整的 Order、Transaction、Tick 字段 |
| `3.2.11` | 在 `3.2.8` 基础上，Order 数据新增 `TradeQty`（成交数量）字段 |

**指定版本**：
```python
client.connect(
    ...,
    data_version="3.2.11",  # 如需 TradeQty 字段则使用此版本
)
```

---

*文档整理自华泰 INSIGHT 官方资料、DolphinDB 插件文档及社区实践，仅供内部开发参考。具体接口参数以华泰官方数据字典为准。*
