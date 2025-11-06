# getrich 系统架构

## 整体架构

getrich 是模块化的量化交易系统，采用 gRPC 进行模块间通信。

```
数据采集 → ClickHouse → 指标计算 → 策略生成 → 风控检查 → 交易执行
```

## 核心模块

### Data（数据模块）
- 数据采集：股票、期货、期权等多种数据源
- ClickHouse 数据库操作：database.py、pool.py、table/
- 数据推送：通过 gRPC 实时推送

### OptionLib（期权模块）
- 隐含波动率计算
- 期权定价模型（Black-Scholes、Heston等）
- 策略分析与风险管理

## 技术栈

- **Python 3.8+** / pandas / numpy
- **ClickHouse** - 时序数据存储
- **gRPC** - 模块间通信
- **Delta + ZSTD** - 数据压缩

## 数据库设计

| 表名 | 主键 | 分区 |
|------|------|------|
| `min_bar` | (symbol, date, local_time) | 按月 |
| `day_bar` | (symbol, date) | 按年 |

详见：[表结构设计](../clickhouse/table/table-design.md)

## 开发指南

### 添加新数据表
1. 继承 `ClickHouseTable` 基类
2. 实现 `create()` 方法定义表结构
3. 添加业务查询方法

### 开发新策略
1. 订阅行情数据
2. 实现策略逻辑
3. 集成风控检查

## 相关文档
- [快速开始](../guides/quick-start.md)
- [ClickHouse 架构](../clickhouse/architecture.md)
- [API 参考](../api/clickhouse.md)