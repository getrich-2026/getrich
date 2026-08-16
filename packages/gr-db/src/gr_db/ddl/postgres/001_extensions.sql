-- Extensions and schema bootstrap.
--
-- 七个 schema 的职责划分（见 AGENTS.md §2）：
--   meta      合约、代码映射、交易日历等参考数据
--   market    行情主存：OHLCV / 复权因子 / 估值，TimescaleDB 超表
--   realtime  实时 tick 缓冲
--   staging   入库中转（parquet 文件登记等）
--   ops       运维：ETL 作业、数据质量、表归属、迁移记账
--   app       业务主库：用户、策略、信号、订单、订阅
--   backtest  回测产物：run / metrics / equity / sweep / walk-forward / jobs
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS realtime;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS backtest;

