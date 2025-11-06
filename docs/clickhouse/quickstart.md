# ClickHouse 快速开始# ClickHouse 连接池 - 快速开始



## 基本使用## 5分钟快速上手



### 1. 单表操作### 1. 导入模块



```python```python

from Data.clickhouse.table.bar import MinBarTablefrom Data.clickhouse import ClickHouseClient, ClickHouseConnectionPool

from Data.clickhouse.table import MinBarTable

# 创建表```

table = MinBarTable()

table.create()### 2. 创建连接池



# 插入数据```python

table.insert(dataframe)# 创建连接池（推荐用于高并发场景）

pool = ClickHouseConnectionPool(

# 查询数据    host='localhost',

df = table.read(    port=9000,

    symbols=['SH.600000'],    database='market_data',

    start_date='2025-01-01',    user='default',

    end_date='2025-01-31'    password='',

)    min_size=2,      # 最小连接数

    max_size=10      # 最大连接数

# 关闭连接)

table.close()```

```

### 3. 使用连接池

### 2. 多表共享连接

#### 方式A：通过表操作（最简单）

```python

from Data.clickhouse import ClickHouseClient```python

from Data.clickhouse.table.bar import MinBarTable, DayBarTable# 创建表实例

table = MinBarTable(pool=pool)

# 创建共享客户端

client = ClickHouseClient()# 执行操作（自动管理连接）

count = table.count()

# 多个表共享连接print(f"记录数: {count}")

min_bar = MinBarTable(client=client)

day_bar = DayBarTable(client=client)# 插入数据

table.insert(dataframe)

# 操作

min_bar.insert(df1)# 查询数据

day_bar.insert(df2)result = table.query("SELECT * FROM min_bar LIMIT 10")

```

# 统一关闭

client.close()#### 方式B：直接获取连接

```

```python

### 3. 连接池（高并发）# 使用上下文管理器（推荐）

with pool.connection() as client:

```python    result = client.query("SELECT * FROM min_bar")

from Data.clickhouse import ClickHouseConnectionPool    print(result)

from Data.clickhouse.table.bar import MinBarTable# 连接自动归还到池中



# 创建连接池# 或手动获取/释放

pool = ClickHouseConnectionPool(client = pool.get_connection()

    host='localhost',try:

    min_size=2,    result = client.query("SELECT * FROM min_bar")

    max_size=10finally:

)    pool.release_connection(client)  # 必须释放！

```

# 表使用连接池

table = MinBarTable(pool=pool)### 4. 监控连接池



# 自动管理连接```python

table.insert(df)# 查看统计信息

result = table.query("SELECT * FROM min_bar LIMIT 10")stats = pool.get_statistics()

print(f"总连接数: {stats['total_connections']}")

# 关闭连接池print(f"活动连接: {stats['active_connections']}")

pool.close()print(f"空闲连接: {stats['idle_connections']}")

```print(f"获取请求: {stats['get_requests']}")

print(f"释放次数: {stats['releases']}")

## 三种模式对比

# 检查连接泄漏

| 模式 | 适用场景 | 优点 | 缺点 |if stats['get_requests'] != stats['releases']:

|------|----------|------|------|    print("⚠️ 警告：存在连接泄漏！")

| 独立客户端 | 简单脚本 | 简单直接 | 资源浪费 |```

| 共享客户端 | 多表操作 | 节省资源 | 不支持并发 |

| 连接池 | 高并发 | 连接复用、线程安全 | 配置复杂 |### 5. 维护连接池



## 监控连接池```python

# 清理过期连接

```pythoncleaned = pool.cleanup()

stats = pool.get_statistics()print(f"清理了 {cleaned} 个过期连接")

print(f"总连接数: {stats['total_connections']}")

print(f"活动连接: {stats['active_connections']}")# 收缩连接池（移除多余空闲连接）

shrunk = pool.shrink()

# 检查连接泄漏print(f"收缩了 {shrunk} 个空闲连接")

if stats['get_requests'] != stats['releases']:

    print("⚠️ 警告：可能存在连接泄漏")# 健康检查

```pool.health_check()

print("健康检查完成")

## 下一步```



- 📖 [表操作指南](./table/usage-guide.md)### 6. 关闭连接池

- 📊 [表结构设计](./table/table-design.md)

- 🔧 [数据导入](./jobs/README.md)```python

# 手动关闭
pool.close()

# 或使用上下文管理器自动关闭
with ClickHouseConnectionPool(...) as pool:
    # 使用连接池
    pass
# 自动关闭
```

## 三种连接模式对比

### 模式1：连接池（高并发）

```python
# 适用场景：多线程、Web服务、实时行情处理
pool = ClickHouseConnectionPool(
    host='localhost',
    database='market_data',
    min_size=5,
    max_size=20
)
table = MinBarTable(pool=pool)
# ✅ 支持多线程并发
# ✅ 自动连接复用
# ✅ 连接生命周期管理
```

### 模式2：共享客户端（单线程多表）

```python
# 适用场景：单线程、多表操作、简单脚本
client = ClickHouseClient(host='localhost', database='market_data')
table1 = MinBarTable(client=client)
table2 = TickTable(client=client)
# ✅ 简单直接
# ✅ 节省连接资源
# ❌ 不支持并发
```

### 模式3：独立客户端（隔离）

```python
# 适用场景：完全独立的操作、临时任务
table = MinBarTable(
    host='localhost',
    database='market_data'
)
# ✅ 完全独立
# ✅ 自动管理连接
# ❌ 每个表一个连接
```

## 多线程示例

```python
import threading

pool = ClickHouseConnectionPool(
    host='localhost',
    database='market_data',
    min_size=3,
    max_size=15
)

def worker(thread_id):
    """工作线程"""
    table = MinBarTable(pool=pool)
    for i in range(10):
        count = table.count()
        print(f"线程 {thread_id}: {count} 条记录")

# 创建并启动多个线程
threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()

# 查看统计
stats = pool.get_statistics()
print(f"总请求: {stats['get_requests']}")
print(f"峰值连接: {stats['total_connections']}")

pool.close()
```

## 配置建议

### Web 服务

```python
pool = ClickHouseConnectionPool(
    min_size=5,           # 保持5个热连接
    max_size=50,          # 峰值50个连接
    max_idle_time=180,    # 3分钟空闲超时
    max_lifetime=1800     # 30分钟连接更新
)
```

### 实时行情处理

```python
pool = ClickHouseConnectionPool(
    min_size=10,          # 多品种并行写入
    max_size=20,          # 控制峰值负载
    max_idle_time=60,     # 快速释放空闲
    max_lifetime=3600     # 1小时连接更新
)
```

### 数据分析

```python
pool = ClickHouseConnectionPool(
    min_size=1,           # 最小连接即可
    max_size=5,           # 偶尔并发查询
    max_idle_time=600,    # 10分钟空闲超时
    max_lifetime=7200     # 2小时连接更新
)
```

## 最佳实践

### ✅ DO

```python
# 1. 使用上下文管理器
with pool.connection() as client:
    client.query("SELECT * FROM data")

# 2. 检查连接泄漏
stats = pool.get_statistics()
assert stats['get_requests'] == stats['releases']

# 3. 定期维护
pool.cleanup()
pool.health_check()

# 4. 合理配置超时
client = pool.get_connection(timeout=10)

# 5. 监控统计
if stats['timeouts'] > 100:
    pool.max_size = 20  # 增加最大连接数
```

### ❌ DON'T

```python
# 1. 不要忘记释放连接
client = pool.get_connection()
client.query("SELECT * FROM data")
# 忘记 pool.release_connection(client) ❌

# 2. 不要长时间占用连接
with pool.connection() as client:
    result = client.query("SELECT * FROM data")
    time.sleep(60)  # 连接被占用60秒 ❌

# 3. 不要在循环中创建连接池
for i in range(100):
    pool = ClickHouseConnectionPool(...)  # 错误！❌
    # 应该在循环外创建一次

# 4. 不要超过数据库最大连接限制
pool = ClickHouseConnectionPool(
    max_size=10000  # 太大了 ❌
)
```

## 故障排查

### 问题1：连接超时

**症状：** `TimeoutError: Timeout waiting for connection`

**原因：**
- 所有连接都在使用中
- max_size 设置太小
- 查询执行时间过长

**解决方案：**
```python
# 增加最大连接数
pool.max_size = 20

# 增加超时时间
client = pool.get_connection(timeout=10)

# 优化查询性能
```

### 问题2：连接泄漏

**症状：** `get_requests != releases`

**原因：**
- 忘记释放连接
- 异常处理不当

**解决方案：**
```python
# 始终使用 try/finally
client = pool.get_connection()
try:
    # 操作
    pass
finally:
    pool.release_connection(client)

# 或使用上下文管理器
with pool.connection() as client:
    # 操作
    pass
```

### 问题3：性能不佳

**症状：** 连接池比单客户端慢

**原因：**
- 单线程场景使用连接池
- min_size 设置太大
- 频繁的连接获取/释放

**解决方案：**
```python
# 单线程场景使用单客户端
client = ClickHouseClient(...)
table = MinBarTable(client=client)

# 或减小 min_size
pool.min_size = 1
```

## 下一步

- 📖 阅读完整文档：[pool-usage.md](./pool-usage.md) - 连接池详细使用指南
- 📊 表操作文档：[table/usage-guide.md](./table/usage-guide.md) - 表的增删改查
- 📋 表结构设计：[table/table-design.md](./table/table-design.md) - MinBar 和 DayBar 表设计
- 🔧 数据导入任务：[jobs/README.md](./jobs/README.md) - 批量数据导入
- 🏗️ 了解架构设计：[architecture.md](./architecture.md) - ClickHouse 架构
- ✅ 查看实现总结：[pool-implementation.md](./pool-implementation.md) - 技术实现细节

## 常见问题

**Q: 连接池和单客户端有什么区别？**

A: 连接池管理多个连接，支持并发；单客户端只有一个连接，不支持并发。单线程场景两者性能相当，多线程场景连接池显著更优。

**Q: 什么时候用连接池？**

A: 多线程、Web服务、高并发场景。单线程简单脚本用单客户端即可。

**Q: 如何避免连接泄漏？**

A: 始终使用上下文管理器 `with pool.connection() as client:`，或确保在 `finally` 块中释放连接。

**Q: max_size 应该设置多大？**

A: 一般为峰值并发数的 1.5 倍。过大浪费资源，过小导致超时。根据监控数据动态调整。

**Q: 旧代码需要修改吗？**

A: 不需要。新架构完全向后兼容，旧代码可以继续工作。需要高并发时再迁移到连接池。

---

🎉 **开始使用连接池，享受高性能并发数据访问！**
