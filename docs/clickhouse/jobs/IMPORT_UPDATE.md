# Data Import Job 更新说明

## 更新内容

### 1. 类重命名
- `MinBarImportJob` → `DataImportJob`（保留别名以兼容旧代码）
- 功能扩展：现在支持 MinBar、DayBar、CodeInfo 三种数据类型

### 2. 新增功能

#### CodeInfo 导入
- 自动从 HDB 文件读取合约信息
- 支持与 MinBar 同时导入或单独导入
- 使用 `ReplacingMergeTree` 引擎自动更新

#### DayBar 支持（预留）
- 已初始化 `DayBarTable` 实例
- 可扩展日线数据导入功能

### 3. 优化改进

#### 参数控制更灵活
```python
importer_job.run_full_import(
    start_year=2005,
    end_year=2025,
    symbols=None,
    skip_existing=True,
    import_min_bar=True,      # 新增：控制是否导入分钟线
    import_code_info=True      # 新增：控制是否导入合约信息
)
```

#### 连接管理优化
- 统一使用 `close()` 方法（替代 `close_connection()`）
- 同时关闭所有表连接

#### 代码结构优化
- 更清晰的参数传递
- 移除配置中不必要的 `table_name` 字段

## 使用示例

### 场景 1: 全量导入（包含分钟线和合约信息）
```python
from Data.clickhouse.jobs.daily_import import DataImportJob

importer = DataImportJob(
    hdb_base_path=r"E:\data\bar\bar\min_bar",
    clickhouse_config={
        'host': 'localhost',
        'port': 8123,
        'database': 'default',
        'user': 'default',
        'password': 'getrich',
    },
    max_workers=4
)

# 全量导入
importer.run_full_import(
    start_year=2005,
    end_year=2025,
    skip_existing=True,
    import_min_bar=True,
    import_code_info=True
)

importer.close()
```

### 场景 2: 只导入合约信息
```python
# 适用于需要更新合约信息但不需要重新导入行情数据的场景
importer.run_full_import(
    start_year=2020,
    end_year=2025,
    skip_existing=False,
    import_min_bar=False,
    import_code_info=True
)
```

### 场景 3: 增量导入
```python
# 自动导入数据库最新日期之后的所有数据
importer.run_incremental_import(
    import_min_bar=True,
    import_code_info=True
)
```

### 场景 4: 导入指定日期
```python
from datetime import datetime

target_date = datetime(2025, 11, 3)
importer.run_incremental_import(
    target_date=target_date,
    import_min_bar=True,
    import_code_info=True
)
```

## 向后兼容

旧代码无需修改，`MinBarImportJob` 作为别名仍然可用：

```python
from Data.clickhouse.jobs.daily_import import MinBarImportJob

# 旧代码仍然可以正常工作
importer = MinBarImportJob(...)
importer.run_full_import(...)
```

## 表结构说明

### code_info 表
- **引擎**: ReplacingMergeTree（自动保留最新记录）
- **主键**: symbol
- **字段**: 18个字段，包括证券名称、涨跌停价、上市日期等

### 数据更新策略
- MinBar: 使用 MergeTree，不去重
- CodeInfo: 使用 ReplacingMergeTree，相同 symbol 自动更新
- 建议定期运行 `OPTIMIZE TABLE code_info FINAL` 清理旧版本

## 性能建议

1. **并发控制**: `max_workers` 根据硬件调整
   - 机械硬盘: 2-4
   - SSD + 4核: 4-8
   - SSD + 8核+: 8-16

2. **内存占用**: 每个 worker 约 100-500MB
   - 建议预留 2GB 以上内存

3. **网络优化**: ClickHouse 在本地时性能最佳

## 注意事项

1. CodeInfo 数据会随着每次导入更新（ReplacingMergeTree 特性）
2. 首次全量导入建议先运行一个日期测试
3. 确保 ClickHouse 服务正在运行
4. 数据库磁盘空间至少 50GB+
