-- 待审核方案，不在默认 postgres 迁移扫描目录中；尚未授权正式执行。
-- 2026-11-08 实测 GFEX：Theta约-161.6万、Vega约1.12万、Rho约-2.34万。
-- 只扩大这三列的整数容量，保留八位小数、来源和固定模型契约。
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE market.option_greeks_1d
    ALTER COLUMN theta TYPE NUMERIC(20,8),
    ALTER COLUMN vega TYPE NUMERIC(20,8),
    ALTER COLUMN rho TYPE NUMERIC(20,8);
