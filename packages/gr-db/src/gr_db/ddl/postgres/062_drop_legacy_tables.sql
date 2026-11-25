-- 062_drop_legacy_tables.sql
-- 清理已废弃且无现行写入方的历史遗留表、视图与空连续聚合视图：
--   1. 007_insight.sql 遗留的 11 张表、8 个视图与 staging schema
--      （market.stock_valuation -> fundamental.valuation_1d；
--        market.stock_adj_factor -> market.adj_factor_ts；
--        market.etf_daily -> market.etf_bar_1d；其余对象无任何源码引用）。
--   2. 006_ops.sql 遗留的 ops.api_keys、ops.users（鉴权统一走 app.users）。
--   3. 023_signals.sql 遗留的 app.signal_batches（全仓零引用）。
--   4. 004_compress_ca.sql 未启用的 5 个空日线连续聚合视图（market.*_bar_1d_ca）。
-- 已记账历史迁移 000~061 原文与 checksum 保持不变；本迁移全部使用 IF EXISTS 保证幂等。

-- 1. 未启用的空连续聚合视图（004_compress_ca.sql）
DROP MATERIALIZED VIEW IF EXISTS market.stock_bar_1d_ca;
DROP MATERIALIZED VIEW IF EXISTS market.etf_bar_1d_ca;
DROP MATERIALIZED VIEW IF EXISTS market.index_bar_1d_ca;
DROP MATERIALIZED VIEW IF EXISTS market.future_bar_1d_ca;
DROP MATERIALIZED VIEW IF EXISTS market.option_bar_1d_ca;

-- 2. 007_insight.sql 遗留视图（先于基表删除）
DROP VIEW IF EXISTS ops.v_dataset_coverage;
DROP VIEW IF EXISTS market.v_stock_valuation;
DROP VIEW IF EXISTS market.v_index_component;
DROP VIEW IF EXISTS market.v_etf_daily;
DROP VIEW IF EXISTS market.v_etf_nav;
DROP VIEW IF EXISTS market.v_fund_daily;
DROP VIEW IF EXISTS market.v_fund_nav;
DROP VIEW IF EXISTS market.v_etf_basket;

-- 3. 007_insight.sql 遗留基表与 staging schema
DROP TABLE IF EXISTS staging.parquet_file;
DROP SCHEMA IF EXISTS staging;
DROP TABLE IF EXISTS ops.dataset_catalog;
DROP TABLE IF EXISTS market.stock_adj_factor;
DROP TABLE IF EXISTS market.stock_valuation;
DROP TABLE IF EXISTS market.index_component;
DROP TABLE IF EXISTS market.etf_daily;
DROP TABLE IF EXISTS market.etf_nav;
DROP TABLE IF EXISTS market.etf_redemption;
DROP TABLE IF EXISTS market.etf_basket;
DROP TABLE IF EXISTS market.fund_daily;
DROP TABLE IF EXISTS market.fund_nav;

-- 4. 006_ops.sql 与 023_signals.sql 零引用遗留表（先删外键子表）
DROP TABLE IF EXISTS ops.api_keys;
DROP TABLE IF EXISTS ops.users;
DROP TABLE IF EXISTS app.signal_batches;
