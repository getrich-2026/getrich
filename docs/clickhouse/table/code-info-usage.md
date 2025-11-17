# CodeInfoTable 使用示例

## 功能说明

`CodeInfoTable` 用于管理合约/标的的基本信息，包括证券名称、涨跌停价、交易日期等。

## 表结构

```sql
CREATE TABLE code_info (
    sec_type Int32,              -- 证券类型
    sec_name String,             -- 证券名称
    date UInt32,                 -- 日期
    high_limited Int32,          -- 涨停价
    low_limited Int32,           -- 跌停价
    multiplier Int32,            -- 合约乘数
    margin_ratio Int32,          -- 保证金比例
    price_tick Int32,            -- 最小价格变动
    capital Int64,               -- 资本
    cap_change_date UInt32,      -- 资本变更日期
    trade_date_in UInt32,        -- 上市日期
    trade_date_out UInt32,       -- 退市日期
    is_halt Int8,                -- 是否停牌
    margin_unit Int32,           -- 保证金单位
    margin_ratio_param1 Int32,   -- 保证金比例参数1
    margin_ratio_param2 Int32,   -- 保证金比例参数2
    sec_name_ext String,         -- 证券名称扩展
    symbol String,               -- 标的代码（主键）
    insert_time DateTime         -- 插入时间
)
ENGINE = ReplacingMergeTree()
ORDER BY symbol
```

## 基本使用

### 1. 创建表

```python
from Data.clickhouse.table.bar import CodeInfoTable

# 创建 CodeInfoTable 实例
code_info_table = CodeInfoTable()

# 创建表
code_info_table.create(if_not_exists=True)
```

### 2. 插入数据

```python
import pandas as pd

# 准备数据
data = {
    'sec_type': [0, 1],
    'sec_name': ['浦发银行', '工商银行'],
    'date': [20250101, 20250101],
    'high_limited': [30350000, 28900000],
    'low_limited': [22890000, 21800000],
    'multiplier': [0, 0],
    'margin_ratio': [0, 0],
    'price_tick': [0, 0],
    'capital': [0, 0],
    'cap_change_date': [0, 0],
    'trade_date_in': [20050104, 20060427],
    'trade_date_out': [20260714, 20260714],
    'is_halt': [0, 0],
    'margin_unit': [0, 0],
    'margin_ratio_param1': [0, 0],
    'margin_ratio_param2': [0, 0],
    'sec_name_ext': ['', ''],
    'symbol': ['SH.600000', 'SH.601398']
}
df = pd.DataFrame(data)

# 插入数据
code_info_table.insert(df)
```

### 3. 查询数据

```python
# 查询所有数据
all_data = code_info_table.read()

# 查询单个标的
sh600000_info = code_info_table.get_by_symbol('SH.600000')
print(sh600000_info['sec_name'])  # 输出：浦发银行

# 查询多个标的
multiple = code_info_table.read(symbols=['SH.600000', 'SH.601398'])

# 按证券类型筛选
type0_stocks = code_info_table.read(sec_type=0)

# 限制返回数量
first_10 = code_info_table.read(limit=10)
```

### 4. 与 HDB 数据集成

```python
from Data.clickhouse.etl.extract import read_min_bar_from_local
from Data.clickhouse.table.bar import CodeInfoTable

# 从 HDB 文件读取数据
HDB_PATH = r"E:\BaiduNetdiskDownload\data\bar\bar\min_bar\2025"
min_bar_df, code_info_df = read_min_bar_from_local(
    db_path=HDB_PATH,
    file_path="min_bar_20250919",
    symbols=["SH.*", "SZ.*"]
)

# 插入到 ClickHouse
code_info_table = CodeInfoTable()
code_info_table.create(if_not_exists=True)
code_info_table.insert(code_info_df)
```

### 5. 使用连接池（高并发场景）

```python
from Data.clickhouse import ClickHouseConnectionPool
from Data.clickhouse.table.bar import CodeInfoTable

# 创建连接池
pool = ClickHouseConnectionPool(min_size=2, max_size=10)

# 使用连接池
code_info_table = CodeInfoTable(pool=pool)
code_info_table.create()
code_info_table.insert(df)

# 关闭连接池
pool.close()
```

## 特点

1. **自动去重**：使用 `ReplacingMergeTree` 引擎，相同 symbol 的记录会自动保留最新版本
2. **按 symbol 排序**：优化按合约代码查询的性能
3. **灵活查询**：支持按 symbol、sec_type 筛选
4. **继承基类**：复用 `ClickHouseTable` 的通用方法（insert、query、count、truncate、drop 等）

## 注意事项

1. 价格字段（high_limited、low_limited）存储为整数，实际使用时需除以 10000
2. 日期字段使用 UInt32 格式（如 20250101）
3. 使用 `ReplacingMergeTree` 引擎时，需要定期运行 `OPTIMIZE TABLE ... FINAL` 来清理旧版本数据
4. sec_name 需要确保是字符串类型（从 bytes 解码后）
