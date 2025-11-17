# Copilot Instructions for getrich

## 项目架构概览
- 本项目为量化交易系统，采用模块化设计，核心模块包括：数据、指标、策略、交易、风控。
- 各模块通过 gRPC 进行跨进程通信，接口定义采用 Protocol Buffers，支持流式和一元 RPC。
- 数据存储采用 ClickHouse，针对高频金融数据设计多张表（Tick、分钟线、日线、期权希腊值等），分区与主键策略详见 README。

## 关键目录与文件
- `data/`：行情与金融数据采集、预处理，按品种分模块（如 GetRich_StockData_AK.py、GetRich_FuturesData_AK.py）。
- `OptionLib/`：期权相关分析、定价、风控与可视化工具（如 GetRich_ImpliesVolCal.py、GetRich_StraAnalysis_pricer.py）。
- `README.md`：详细描述架构、数据库设计、gRPC接口示例。

## 开发者工作流
- 数据采集与推送：数据模块采集行情，写入 ClickHouse，并通过 gRPC 流式推送。
- 指标计算：指标模块订阅行情，计算技术指标/希腊值，通过 RPC 提供查询接口。
- 策略开发：策略模块订阅行情与指标，生成信号，经风控模块校验后调用交易模块下单。
- 交易执行：交易模块对接券商接口，执行订单并反馈结果。
- 风控监控：风控模块独立检查每笔订单，监控持仓与资金，生成风险报表。

## 项目约定与模式
- 数据表设计需根据数据频率合理分区，主键排序优先合约+时间。
- 指标计算与策略逻辑分离，指标模块可批量写入常用指标，策略模块按需查询。
- gRPC接口需严格遵循 Protocol Buffers 定义，服务端流用于行情推送，一元 RPC 用于指标查询。
- 代码按品种/功能模块化，便于扩展和维护。

## 外部依赖与集成
- 依赖 ClickHouse 数据库，需预先建表并配置分区策略。
- gRPC 通信需定义并维护 .proto 文件，确保接口兼容。
- 交易接口需对接券商 API，注意异步回报处理。

## 示例：gRPC 接口定义
```protobuf
service MarketDataService {
    rpc SubscribeMarketData(SubscribeRequest) returns (stream MarketTick);
}
service IndicatorService {
    rpc GetIndicator(IndicatorRequest) returns (IndicatorResult);
}
```

## 重要习惯与注意事项
- 所有模块间通信优先使用 gRPC，避免 REST。
- 数据表分区数量控制在合理范围（如 Tick 表按日分区，避免过多小分区）。
- 指标与策略解耦，便于复用和性能优化。
- 代码扩展时遵循现有模块划分和接口规范。

---
如需补充特定开发流程、调试命令或集成细节，请在此文档补充说明。