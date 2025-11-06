# ClickHouse 表结构

## MinBarTable（分钟线）

### 表结构

```sql
CREATE TABLE min_bar (
    date UInt32,
    time Int32,
    pre_close Int64,
    open Int64,
    high Int64,
    low Int64,
    close Int64,
    volume Int64,
    turnover Int64,
    open_interest Int64,
    pre_settle_price Int64,
    settle_price Int64,
    symbol String,
    local_time DateTime64(3),
    insert_time DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(local_time)
ORDER BY (symbol, date, local_time)
```

**主键**：`(symbol, date, local_time)` - 支持按合约筛选、日期范围查询、时间顺序
**分区**：按月分区 - 平衡性能与分区数量

### 使用示例

```python
from Data.clickhouse.table.bar import MinBarTable

min_bar = MinBarTable()

# 查询某合约某天的分钟线
df = min_bar.read(
    symbols='SH.600000',
    start_date='2025-01-01',
    end_date='2025-01-31'
)
```

## DayBarTable（日线）

### 表结构

```sql
CREATE TABLE day_bar (
    -- 字段同 min_bar
)
ENGINE = MergeTree()
PARTITION BY toYear(date)
ORDER BY (symbol, date)
```

**主键**：`(symbol, date)` - 日线每天只有一条记录，不需要 local_time
**分区**：按年分区 - 数据量小，按年足够

### 使用示例

```python
from Data.clickhouse.table.bar import DayBarTable

day_bar = DayBarTable()

# 支持整数或字符串日期
df = day_bar.read(
    symbols='SH.600000',
    start_date=20250101,  # 或 '2025-01-01'
    end_date=20250131
)
```

## 设计原则

1. **主键设计**：与最常用查询模式一致
2. **date 在主键中**：优化日期范围查询（最常见的查询）
3. **分区策略**：高密度数据按月，低密度数据按年

## 使用方式

```python
# 方式1：独立客户端（简单脚本）
table = MinBarTable()

# 方式2：共享客户端（多表操作）
client = ClickHouseClient()
table1 = MinBarTable(client=client)
table2 = DayBarTable(client=client)

# 方式3：连接池（高并发）
pool = ClickHouseConnectionPool(min_size=2, max_size=10)
table = MinBarTable(pool=pool)
```
