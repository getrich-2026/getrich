-- 035_strategies_strategy_kind.sql
-- 给 app.strategies 加 strategy_kind，用于区分选股策略与择时策略。
--
-- 背景：前端要按策略类型路由到不同的详情页（选股策略走 /v1/pick-strategies
-- 那套接口，返回标的池；择时策略走 /v1/strategies，返回业绩曲线与信号）。
-- 现有表里没有任何字段能做这个判别。
--
-- 选型（设计文档「个股推荐_数据库设计_P0.md」§3.3 的三个方案）：
--   A 用 strategy_categories 里一个专门分类   —— 零改动，但类型与业务分类耦合，
--     未来选股再分子类（预增 / 双击）会打架；
--   B 加本列                                   —— **已选**，语义最干净；
--   C 由「是否有 pick.batch 记录」推断         —— 新建但未上传数据的策略无法正确路由。
--
-- 可空：存量行不猜类型，由运营显式回填。选股接口只认 strategy_kind = 'pick'，
-- 因此没回填的策略不会误入选股列表。

CREATE SCHEMA IF NOT EXISTS app;

ALTER TABLE app.strategies
    ADD COLUMN IF NOT EXISTS strategy_kind VARCHAR(16);

-- CHECK 用 DO 块包住，重跑迁移时 duplicate_object 直接吞掉（沿用 032 的写法）。
DO $$
BEGIN
    ALTER TABLE app.strategies
        ADD CONSTRAINT chk_strategies_strategy_kind
        CHECK (strategy_kind IS NULL OR strategy_kind IN ('pick', 'timing', 'combo'));
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END $$;

COMMENT ON COLUMN app.strategies.strategy_kind IS
    '策略类型：pick=选股（产出每日标的池，走 /v1/pick-strategies）；timing=择时（产出买卖信号）；combo=组合。NULL 表示未分类，不会出现在选股接口里。';

CREATE INDEX IF NOT EXISTS idx_strategies_kind
    ON app.strategies(strategy_kind)
    WHERE strategy_kind IS NOT NULL;
