# HDB使用

一个数据库对应一个文件夹，表对应一个数据文件（hdat）和索引文件（hidx）组成的文件对。

* 数据文件存储**数据类型定义**及**数据记录**，其中记录内容包含的字段及压缩选择在数据类型中定义。
* 索引文件包含代码信息、列表。

## 数据结构定义

每个HDB必须包含CodeInfo表结构，至少包括一个DataItem。

### Codetable 代码表

静态基本信息，包含：symbols, totla_items_num, type_items_nums, data

### DataItem 数据记录

异构的时序数据，具有5个公共字段：

| 字段 | 含义 |
|:-------:|:--------:|
| symbol | 标的代码 |
| trading_day | 交易日 |
| local_time | 本地时间戳 |
| index | 代码索引 |
| time_point_seq_no | 数据条目序号 |
| type_id | 数据类型id |
| data | 自定义数据 |

#### data 自定义数据

由hdb.DataType来描述，主要有两个属性：name, fileds。

通过ReadTask.read()读取到的数据中，**其data部分是一个地址，需要通过hdb.DataType.items_data()方法来解析**。

```python
import hdb
db = hdb.DB(r"X:\hdb_data")
file = db.open_file(r"marketdata\tick_20220506", mode="r")
task = file.open_read_task(symbols=['SH.600000'], types=['SecurityTick'])
items = task.read()
data_type = file.data_types[items['type_id'][0]]
data = data_type.items_data(items['data'])
```

#### hdb.DataField 数据类型中的单个字段信息

主要属性有：name(字段名), type(字段类型), encode_op(压缩操作), size(数组长度), flags(额外压缩字段)

## HBD 读写API

* hdb.Client：连接远程的HDBServer,并创建hdb.Client对象
* hdb.Codetable
* hdb.DB：传入本地HDB文件数据库的存放目录，打开该目录，并创建hdb.DB对象
* hdb.DataField
* hdb.DataFrame
* hdb.File：该对象只能由调用hdb.DB.openfile、hdb.Client.open_file、hdb.DB.create_file三个方法返回。返回后，会把ci_type、data_types、codetable三个属性的信息读取到本地，供后续使用。
* hdb.ReadTask：该对象只能由调用hdb.File.open_read_task返回

### hdb.File 

* File.ci_type: hdb.DataType对象，用来描述文件中的代码基础信息的数据类型，注意这里描述的是数据类型。  
* File.data_types：hdb.DataType对象组成的list，用于描述HDB文件中包含的数据类型。  
* File.codetable：hdb.Codetable对象，描述文件中的代码表信息。  

### code_list_name 部分代码列表名称

|选项|说明|
|:-|:-|
|QSAG  | 全市场A股  |
|SHAG  | 上交所A股  |
|SZAG  | 深交所A股  |
|SHAGZT| 上海A股涨停|
|SZAGZT| 深圳A股涨停|
|QSJJ  | 全市场基金 |
|SHJJ  | 上海基金   |
|SZJJ  | 深圳基金   |
|QSZQ  | 全市场债券 |
|SHZQ  | 上海债券   |
|SZZQ  | 深圳债券   |
|SHNHG | 上海逆回购 |
|SZNHG | 深圳逆回购 |
|SHOP  | 上海期权   |
|SZOP  | 深圳期权   |

###  服务器中文件介绍

| 文件夹       | 文件夹中文件名                                               | 介绍                                                         |
| ------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| marketdata/  | tick_date(例，tick_20200511)                                 | tick数据，包含CodeInfo、(CodeList)、<br>DataItem(SecurityTick、IndexTick、FuturesTick、OptionsTick、SHStepTrade、SZStepTrade、SZStepOrder、OrderQueueItem、SZOptionsTick) |
| bar/         | day_bar_year(例，day_bar_2020);<br>min_bar_date(例，min_bar_20200511) | K线数据（按日，按分钟）                                      |
| baseinfo/    | SecurityInfo_date(例，SecurityInfo_20200511)                 | 详细的证券代码基本信息数据                                   |
| fundmentals/ | qxdata_year(例，qxdata_2020)                                 | 除息数据                                                     |

### 服务器中Tick数据介绍

| Tick数据       | 名字含义         |
| -------------- | ---------------- |
| CodeList       | 代码列表         |
| CodeInfo       | 代码基本信息     |
| SecurityTick   | 证券Tick数据     |
| IndexTick      | 指数Tick数据     |
| FuturesTick    | 期货Tick数据     |
| OptionsTick    | 期权Tick数据     |
| SHStepTrade    | 上海逐笔成交数据 |
| SZStepTrade    | 深圳逐笔成交数据 |
| SZStepOrder    | 深圳逐笔委托数据 |
| OrderQueueItem | 委托队列数据     |
| SZOptionsTick  | 深圳期权Tick数据 |

## 代码示例

1. 获取hdb文件中的数据类型

```python
import hdb
db = hdb.DB(r"Z:\hdb_data")
file = db.open_file(r"marketdata\tick_20220506", mode="r") #数据类型数组
data_types = file.data_types
for data_type in data_types:
    print(data_type.name) ###打印各个类型名称

SecurityTick
IndexTick
FuturesTick
OptionsTick
SHStepTrade
SZStepTrade
SZStepOrder
OrderQueueItem
SZOptionsTick
SHStepOrder
FPSHStepTrade
```

```python
# 获取SecurityTick的各个字段
for field in data_types[0].fields:
    print(field.name)

time
status
pre_close
open
high
low
match
ask_price
ask_vol
bid_price
bid_vol
num_trades
volume
turnover
total_bid_vol
total_ask_vol
weighted_avg_bid_price
weighted_avg_ask_price
iopv
yield_to_maturity
high_limited
low_limited
prefix
syl1
syl2
sd2
trading_phase_code
pre_iopv
```

```python
# 读取代码信息
print(file.ci_type.name) #打印类型名
print(file.ci_type.dtype) #打印基础信息字段

# 读取代码列表
print(file.codetable.symbols)

# 读取代码信息
index = file.codetable.symbols.index("SH.600000") # 获取代码索引
file.ci_type.item_data(file.codetable.data[index])

# 读取数据内容
# ci_type: codeinfo type
codetable_pd = pd.DataFrame(file.ci_type.items_data(file.codetable.data))
codetable_pd["sec_name"] = codetable_pd["sec_name"].map(lambda x: x.decode("gbk"))
```

```python
#读取SZ.300打头的股票快照数据
task = file.open_read_task(symbols=["SZ.300*"], types=["SecurityTick"])
items = task.read()

array([(b'SZ.300003', 23075, 20220506, 1651798222227, 59, 0, 2098824818800),
       (b'SZ.300004', 23077, 20220506, 1651798222227, 61, 0, 2098824819076),
       (b'SZ.300006', 23078, 20220506, 1651798222227, 62, 0, 2098824819352),
       ...,
       (b'SZ.300978', 24236, 20220506, 1651823945641, 15, 0, 2099802949552),
       (b'SZ.300982', 24239, 20220506, 1651823945641, 18, 0, 2099802949828),
       (b'SZ.300999', 24240, 20220506, 1651823945641, 21, 0, 2099802950104)],
dtype=[('symbol', 'S24'), ('index', '<i4'), ('trading_day', '<i4'), ('local_time', '<i8'), ('time_point_seq_no', '<i4'), ('type_id', '<i4'), ('data', '<u8')])

type_id = items[0]["type_id"] #items[0]的type_id字段对应的data_type是SecurityTick
file.data_types[type_id].name # 'SecurityTick'

data = file.data_types[type_id].items_data(items["data"])
```

```python
#把data中的字段分别插入dataframe中
#因为dataframe不支持某一个字段是数组类型，所以需要将该字段拆解成多个单独的字段（比如bid_price包含10档数据）
df = pd.DataFrame()
data_type = file.data_types[items[0]["type_id"]]
for name in data_type.dtype.fields:
    field_type = data.dtype.fields[name][0]
    if 0 == field_type.ndim:
        df[name] = data[name]
    elif 1 == field_type.ndim:
        for idx in range(field_type.shape[0]):
            df[name + '.' + str(idx)] = data[name][:, idx]

df['symbol'] = items['symbol']
df['date'] = items['trading_day']
```

```python
#将上述过程封装后可以调用read_data
def read_data(f, symbols, data_type, begin=None, end=None):
    if (begin is None) and (end is None):
        task = f.open_read_task(symbols=symbols, types=[data_type])
    elif begin is None:
        task = f.open_read_task(end_time=end, symbols=symbols, types=[data_type])
    elif end is None:
        task = f.open_read_task(begin_time=begin, symbols=symbols, types=[data_type])
    else:
        task = f.open_read_task(begin_time=begin, end_time=end, symbols=symbols, types=[data_type])
    items = task.read()
    data_type = f.data_types[items['type_id'][0]]
    data = data_type.items_data(items['data'])
    df = pd.DataFrame()
    for name in data_type.dtype.fields:
        field_type = data.dtype.fields[name][0]
        if 0 == field_type.ndim:
            df[name] = data[name]
        elif 1 == field_type.ndim:
            for idx in range(field_type.shape[0]):
                df[name + '.' + str(idx)] = data[name][:, idx]
    task.close()
    df['symbol'] = items['symbol']
    df['date'] = items['trading_day']
    return df

data = read_data(file, ["SZ.300*"], "SecurityTick")
```

```python
# 读取逐笔成交数据
data = read_data(file, ["SZ.300*"], "SZStepTrade")
```

```python
# 该函数可以获取不复权的k线
def load_min_bar_from_hdb(symbols,
                          db_path,
                          start,
                          end):
    start_date = int(start.strftime("%Y%m%d"))
    end_date = int(end.strftime("%Y%m%d"))
    db = hdb.DB(db_path)
    total_dates = db.get_trading_days(start_date, end_date)
    load_year = None
    load_years = []
    for cur_date in total_dates:
        cur_year = cur_date // 10000
        if cur_year != load_year:
            load_year = cur_year
            load_years.append(str(cur_year))
    ret = []
    for cur_year in load_years:
        file_name = "%s_%s" % ("bar/day_bar", cur_year)
        file = db.open_file(file_name)
        data = read_data(file, symbols, "SecurityKdata", start, end)
        ret.append(data)
        file.close()
    kline_data = pd.concat(ret)
    kline_data["symbol"] = kline_data["symbol"].str.decode("utf8")
#    kline_data["date"] = pd.to_datetime(kline_data["date"], format="%Y%m%d")
    return kline_data

import datetime
start = datetime.date(2022,11,1)
end = datetime.date(2023,1,31)
symbols = ["SZ.123119","SH.600085"]
db_path = "Z:/hdb_data"
kline_data = load_min_bar_from_hdb(symbols, db_path, start, end)
```

```python
# 获取复权因子
def load_adj_factor(data_base_path, symbols, begin_date, end_date, fq, is_from_initial=False):
"""
该方法可以获取指定股票列表，日期在闭区间[begin_date, end_date]内，每天每支标的的复权因子。复权因子乘以不复权价即可得对应的复权价。

Args：
data_base_path：HDB目录
symbols：股票代码列表
begin_date：开始日期，格式：yyyymmdd，例如20220101
end_date：结束日期，格式同上
fq：复权方式，前复权填“pre”，后复权填“post”。
is_from_initial：后复权时，复权价是否从上市首日开始计算，默认值为False

Return：每只标的，在闭区间[begin_date, end_date]内的所有复权因子
"""
    db = hdb.DB(data_base_path)
    total_dates = db.get_trading_days(begin_date, end_date)
    load_year = None
    load_years = []
    is_from_initial
    for cur_date in total_dates:
        cur_year = cur_date // 10000
        if cur_year != load_year:
            load_year = cur_year
            load_years.append(cur_year)
    adj_factors = dict()
    adj_data = dict()
    for cur_year in load_years:
        file_path = "bar\day_bar_%s" % cur_year
        file = db.open_file(file_path, mode="r")
        for symbol in symbols:
            if is_from_initial:
                index =  file.codetable.symbols.index(symbol)
                codeinfo = file.ci_type.item_data(file.codetable.data[index])
                bdate = codeinfo['date'][0]        
                begin_time = max(datetime.datetime(cur_year,1,1,0),datetime.datetime.strptime(str(bdate),"%Y%m%d"))
                if not(symbol in adj_factors.keys()):
                    adj_factors[symbol] = (codeinfo["capital"] / codeinfo["multiplier"])[0]   
            else:
                begin_time = max(datetime.datetime(cur_year,1,1,0),datetime.datetime.strptime(str(begin_date),"%Y%m%d"))
                if not(symbol in adj_factors.keys()):
                    adj_factors[symbol] = 1
            end_time = min(datetime.datetime(cur_year,12,31,23,59,59),datetime.datetime.strptime(str(end_date),"%Y%m%d"))
            data = file.read([symbol],"SecurityKdata",["date","pre_close","close"],begin_time,end_time)
            data_pd = hdb.util.convert_hdbframe_to_pandasframe(data, ["date","pre_close","close"])
            if symbol in adj_data.keys():
                adj_data[symbol] = pd.concat([adj_data[symbol], data_pd])
            else:
                adj_data[symbol] = data_pd
    qfactor = dict()
    for symbol in symbols:
        daybar = adj_data[symbol]
        if fq == "pre":
            daybar["fq_factor"] = daybar["pre_close"]/daybar["close"]
            close = daybar["close"].iloc[-1]
            daybar["fq_factor"] = daybar["fq_factor"].iloc[::-1].cumprod()[::-1]
            daybar["fq_factor"] = daybar["fq_factor"]*close
            daybar["fq_factor"] = daybar["fq_factor"]/daybar["pre_close"]
        elif fq == "post":
            adj_factor = adj_factors[symbol]
            daybar["fq_factor"] = daybar["close"]/daybar["pre_close"]
            daybar["fq_factor"] = daybar["fq_factor"].cumprod()
            pre_close = daybar["pre_close"].iloc[0]
            daybar["fq_factor"] = daybar["fq_factor"]*pre_close*adj_factor
            daybar["fq_factor"] = daybar["fq_factor"]/daybar["close"]
            daybar = daybar[daybar["date"]>=begin_date]
#        qfactor[symbol] = daybar
        qfactor[symbol] = daybar.groupby("date")["fq_factor"].first().to_dict()
    return qfactor

db_path = "Z:/hdb_data"
symbols = ["SH.600085","SZ.000001"]
begin_date = 20210801
end_date = 20230310
fq = "post"
factor = load_adj_factor(db_path, symbols, begin_date, end_date, fq, is_from_initial=True)

#计算sh600085的k线的收盘价的后复权价
sh600085 = kline_data[kline_data["symbol"]=="SH.600085"].copy()
sh600085['close_fq'] = sh600085.apply(lambda x: int(round(factor['SH.600085'][x['date']]*x['close'],-2)),axis=1)
```



