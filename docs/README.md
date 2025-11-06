# getrich 量化交易系统文档# getrich 量化交易系统文档



## 📚 核心文档欢迎使用 getrich 量化交易系统！这里是完整的项目文档。



### 快速开始## 📚 文档导航

- [快速开始指南](./guides/quick-start.md) - 5分钟上手

- [系统架构](./architecture/system-overview.md) - 整体设计### 🚀 快速开始

- [项目README](../README.md) - 项目概览- [安装指南](../INSTALL.md) - 系统安装和环境配置

- [快速开始](./guides/quick-start.md) - 5分钟上手指南

### ClickHouse 数据库- [项目概览](../README.md) - 系统架构和模块介绍

- [快速开始](./clickhouse/quickstart.md) - 数据库操作入门

- [表结构设计](./clickhouse/table/table-design.md) - MinBar 和 DayBar 表### 📖 用户指南



### 代码示例#### ClickHouse 数据库

- `Data/clickhouse/examples.py` - ClickHouse 使用示例- [ClickHouse 快速开始](./clickhouse/quickstart.md) - 数据库操作入门

- `Data/clickhouse/jobs/daily_import.py` - 数据导入任务- [连接池使用指南](./clickhouse/pool-usage.md) - 高性能并发访问

- `OptionLib/` - 期权分析工具- [表操作指南](./clickhouse/table/usage-guide.md) - 表的增删改查

- [数据导入任务](./clickhouse/jobs/README.md) - 批量数据导入

## 📁 目录结构

#### 其他模块

```- [数据采集指南](./guides/data-collection.md) - 行情数据获取和存储

docs/- [策略开发指南](./guides/strategy-development.md) - 交易策略编写

├── guides/- [期权分析指南](./guides/option-analysis.md) - 期权定价和风险分析

│   └── quick-start.md          # 快速开始

├── architecture/### 🏗️ 架构文档

│   └── system-overview.md      # 系统架构- [系统架构](./architecture/system-overview.md) - 整体设计和模块关系

└── clickhouse/- [ClickHouse 架构](./clickhouse/architecture.md) - 数据存储架构设计

    ├── quickstart.md           # ClickHouse 快速开始- [表结构设计](./clickhouse/table/table-design.md) - MinBar 和 DayBar 表设计

    └── table/- [gRPC 通信协议](./architecture/grpc-protocols.md) - 模块间通信接口

        └── table-design.md     # 表结构设计- [数据库设计](./architecture/database-design.md) - 完整表结构和索引策略

```

### 🔧 开发者文档

## 🎯 使用建议- [开发环境搭建](./guides/development-setup.md) - 开发环境配置

- [代码贡献指南](./guides/contributing.md) - 如何参与项目开发

### 开发者- [测试指南](./guides/testing.md) - 单元测试和集成测试

1. 阅读 [快速开始](./guides/quick-start.md)- [部署指南](./guides/deployment.md) - 生产环境部署

2. 理解 [系统架构](./architecture/system-overview.md)

3. 参考代码示例学习### 📋 API 参考

- [ClickHouse API](./api/clickhouse.md) - 数据库操作接口

### 数据分析师- [数据模块 API](./api/data-module.md) - 数据采集和处理接口

1. 学习 [ClickHouse 快速开始](./clickhouse/quickstart.md)- [期权模块 API](./api/option-module.md) - 期权分析工具接口

2. 了解 [表结构设计](./clickhouse/table/table-design.md)- [工具函数 API](./api/utilities.md) - 通用工具函数

3. 运行数据导入任务

### 📝 实现细节
- [ClickHouse 重构记录](./clickhouse/refactor-summary.md) - 架构重构过程
- [连接池实现细节](./clickhouse/pool-implementation.md) - 技术实现说明
- [性能优化指南](./guides/performance-optimization.md) - 系统性能调优
- [故障排查指南](./guides/troubleshooting.md) - 常见问题解决

## 📁 目录结构

```
docs/
├── README.md                    # 本文件，文档导航
├── guides/                      # 用户指南
│   ├── quick-start.md          # 快速开始
│   ├── data-collection.md      # 数据采集
│   ├── strategy-development.md # 策略开发
│   ├── option-analysis.md      # 期权分析
│   ├── development-setup.md    # 开发环境
│   ├── contributing.md         # 贡献指南
│   ├── testing.md             # 测试指南
│   ├── deployment.md          # 部署指南
│   ├── performance-optimization.md # 性能优化
│   └── troubleshooting.md     # 故障排查
├── clickhouse/                 # ClickHouse 专项文档
│   ├── quickstart.md          # 快速开始
│   ├── pool-usage.md          # 连接池使用
│   ├── architecture.md        # 架构设计
│   ├── refactor-summary.md    # 重构记录
│   ├── pool-implementation.md # 实现细节
│   ├── table/                 # 表操作文档
│   │   ├── README.md         # 表模块概览
│   │   ├── table-design.md   # 表结构设计
│   │   └── usage-guide.md    # 使用指南
│   └── jobs/                  # 数据导入任务
│       └── README.md         # 导入任务文档
├── architecture/              # 系统架构文档
│   ├── system-overview.md    # 系统概览
│   ├── grpc-protocols.md     # gRPC 协议
│   └── database-design.md    # 数据库设计
└── api/                       # API 参考文档
    ├── clickhouse.md         # ClickHouse API
    ├── data-module.md        # 数据模块 API
    ├── option-module.md      # 期权模块 API
    └── utilities.md          # 工具函数 API
```

## 🎯 文档使用建议

### 👨‍💻 开发者
1. 从 [快速开始](./guides/quick-start.md) 了解项目
2. 阅读 [系统架构](./architecture/system-overview.md) 理解整体设计
3. 参考 [开发环境搭建](./guides/development-setup.md) 配置环境
4. 查阅 [API 参考](./api/) 了解接口详情

### 📊 数据分析师
1. 从 [ClickHouse 快速开始](./clickhouse/quickstart.md) 入门
2. 学习 [数据采集指南](./guides/data-collection.md) 获取数据
3. 使用 [期权分析指南](./guides/option-analysis.md) 进行分析

### 🚀 策略开发者
1. 阅读 [策略开发指南](./guides/strategy-development.md)
2. 了解 [数据库设计](./architecture/database-design.md)
3. 参考 [性能优化指南](./guides/performance-optimization.md)

### 🔧 运维人员
1. 查看 [部署指南](./guides/deployment.md)
2. 学习 [故障排查指南](./guides/troubleshooting.md)
3. 了解 [性能优化指南](./guides/performance-optimization.md)

## 📞 获取帮助

- 🐛 **问题反馈：** 在 GitHub Issues 提交问题
- 💡 **功能建议：** 在 GitHub Discussions 讨论
- 📖 **文档完善：** 提交 Pull Request 改进文档
- 📧 **直接联系：** 通过项目 README 中的联系方式

---

📝 **文档持续更新中，欢迎贡献！**