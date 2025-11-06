# ClickHouse 模块# ClickHouse 模块文档已迁移



本模块提供 ClickHouse 数据库的连接、连接池和表操作功能。📚 **ClickHouse 相关文档已迁移到统一的文档目录中，以提供更好的阅读体验。**



## 📚 文档已迁移## 🔗 新文档位置



**所有文档已迁移到统一的文档目录：** [`docs/clickhouse/`](../../docs/clickhouse/)- **快速开始：** [docs/clickhouse/quickstart.md](../../docs/clickhouse/quickstart.md)

- **连接池使用指南：** [docs/clickhouse/pool-usage.md](../../docs/clickhouse/pool-usage.md)

### 快速导航- **架构设计：** [docs/clickhouse/architecture.md](../../docs/clickhouse/architecture.md)

- **重构记录：** [docs/clickhouse/refactor-summary.md](../../docs/clickhouse/refactor-summary.md)

- **快速开始**: [docs/clickhouse/quickstart.md](../../docs/clickhouse/quickstart.md)- **实现细节：** [docs/clickhouse/pool-implementation.md](../../docs/clickhouse/pool-implementation.md)

- **连接池使用**: [docs/clickhouse/pool-usage.md](../../docs/clickhouse/pool-usage.md)- **API 参考：** [docs/api/clickhouse.md](../../docs/api/clickhouse.md)

- **表操作指南**: [docs/clickhouse/table/usage-guide.md](../../docs/clickhouse/table/usage-guide.md)

- **表结构设计**: [docs/clickhouse/table/table-design.md](../../docs/clickhouse/table/table-design.md)## 📁 文档组织结构

- **数据导入任务**: [docs/clickhouse/jobs/README.md](../../docs/clickhouse/jobs/README.md)

- **架构设计**: [docs/clickhouse/architecture.md](../../docs/clickhouse/architecture.md)```

docs/

## 🚀 快速示例├── README.md                    # 文档导航首页

├── guides/

### 使用表操作│   └── quick-start.md          # 5分钟快速上手

├── clickhouse/                 # ClickHouse 专项文档

```python│   ├── quickstart.md           # 快速开始

from Data.clickhouse.table.bar import MinBarTable, DayBarTable│   ├── pool-usage.md           # 连接池使用

│   ├── architecture.md         # 架构设计

# 分钟线查询│   ├── refactor-summary.md     # 重构记录

min_bar = MinBarTable()│   └── pool-implementation.md  # 实现细节

df = min_bar.read(├── architecture/               # 系统架构

    symbols='SH.600000',│   └── system-overview.md      # 系统概览

    start_date='2025-01-01',└── api/                        # API 参考

    end_date='2025-01-31'    └── clickhouse.md           # ClickHouse API

)```



# 日线查询## 🚀 快速导航

day_bar = DayBarTable()

df = day_bar.read(### 新用户

    symbols='SH.600000',1. [项目快速开始](../../docs/guides/quick-start.md) - 5分钟上手整个项目

    start_date=20250101,2. [ClickHouse 快速开始](../../docs/clickhouse/quickstart.md) - ClickHouse 模块入门

    end_date=20250131

)### 开发者

```1. [系统架构概览](../../docs/architecture/system-overview.md) - 了解整体设计

2. [ClickHouse 架构](../../docs/clickhouse/architecture.md) - 数据层设计

### 使用连接池3. [API 参考文档](../../docs/api/clickhouse.md) - 接口详情



```python### 高级用户

from Data.clickhouse import ClickHouseConnectionPool1. [连接池使用指南](../../docs/clickhouse/pool-usage.md) - 高性能并发访问

from Data.clickhouse.table.bar import MinBarTable2. [重构记录](../../docs/clickhouse/refactor-summary.md) - 架构演进过程

3. [实现细节](../../docs/clickhouse/pool-implementation.md) - 技术实现说明

# 创建连接池

pool = ClickHouseConnectionPool(## 💡 为什么迁移文档？

    host='localhost',

    database='default',### 旧组织方式的问题

    min_size=2,- ❌ 文档和代码混在一起

    max_size=10- ❌ 可发现性差（需要深入代码目录）

)- ❌ 不符合工程规范

- ❌ 文档类型混杂

# 使用连接池

table = MinBarTable(pool=pool)### 新组织方式的优势

count = table.count()- ✅ 统一的文档入口

```- ✅ 按用途分类组织

- ✅ 符合开源项目最佳实践

## 📂 目录结构- ✅ 更好的可读性和维护性

- ✅ 支持文档网站生成

```

Data/clickhouse/## 📖 本目录内容

├── __init__.py              # 模块导出

├── database.py              # ClickHouse 客户端本目录 (`Data/clickhouse/`) 现在只包含：

├── pool.py                  # 连接池实现

├── api.py                   # API 封装- **代码文件：** 核心功能实现

├── service.py               # 服务层  - `database.py` - ClickHouse 客户端

├── utils.py                 # 工具函数  - `pool.py` - 连接池实现

├── examples.py              # 代码示例  - `table/` - 表操作抽象

├── config/                  # 配置文件  - `api.py`, `service.py`, `utils.py` - 辅助功能

│   └── config.yml  - `examples.py` - 代码示例

├── table/                   # 表操作模块

│   ├── __init__.py- **配置文件：**

│   ├── base.py             # ClickHouseTable 基类  - `config/` - 数据库配置

│   ├── bar.py              # MinBarTable, DayBarTable  - `etl/` - 数据ETL脚本

│   └── test_base.py        # 测试文件  - `jobs/` - 定时任务

├── etl/                     # 数据ETL

│   ├── __init__.py- **此文档：** 指向新文档位置的说明

│   └── extract.py          # HDB 数据提取

└── jobs/                    # 定时任务## 🔧 代码示例

    ├── __init__.py

    ├── daily_import.py     # 数据导入任务代码示例仍保留在 [examples.py](./examples.py) 中，包含：

    └── test_import.py      # 测试脚本

```- 单客户端使用示例

- 连接池使用示例

## 🔗 相关文档- 多线程并发示例

- 性能对比示例

- [完整文档导航](../../docs/README.md)- 错误处理示例

- [系统架构](../../docs/architecture/system-overview.md)

- [API 参考](../../docs/api/clickhouse.md)## 📞 获取帮助


如果你在查找特定的文档内容：

1. **从文档导航开始：** [docs/README.md](../../docs/README.md)
2. **查看完整目录：** `docs/` 文件夹
3. **提交问题：** 如果找不到需要的文档，请在 GitHub Issues 中反馈

---

📚 **感谢理解，新的文档组织将为你提供更好的使用体验！**