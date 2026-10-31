-- 2026-10-31 用户授权：历史 Tushare 的有限估值极端值按原值保留，
-- 不截断、不置空；超过绝对值 1e6 的观察由 ingest 写质量审计，因子层另行处理。
-- 保持四位小数，仅扩大整数容量；不改已记账的 038 校验和。
-- ALTER 需要短暂 ACCESS EXCLUSIVE 锁；忙时快速失败，避免阻塞在线读写。
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE IF EXISTS fundamental.valuation_1d
    ALTER COLUMN pe TYPE NUMERIC(20,4),
    ALTER COLUMN pe_ttm TYPE NUMERIC(20,4),
    ALTER COLUMN ps TYPE NUMERIC(20,4),
    ALTER COLUMN ps_ttm TYPE NUMERIC(20,4);

COMMENT ON COLUMN fundamental.valuation_1d.pe IS
    '市盈率（总市值／净利润）。亏损股源值 NULL 保留；有限极端值不截断，绝对值超过 1e6 记质量审计：极端值保留原值、因子层处理。';
COMMENT ON COLUMN fundamental.valuation_1d.pe_ttm IS
    'TTM 市盈率。亏损股源值 NULL 保留；有限极端值不截断，绝对值超过 1e6 记质量审计：极端值保留原值、因子层处理。';
COMMENT ON COLUMN fundamental.valuation_1d.ps IS
    '市销率（总市值／最新年报营业收入）。有限极端值不截断，绝对值超过 1e6 记质量审计：极端值保留原值、因子层处理。';
COMMENT ON COLUMN fundamental.valuation_1d.ps_ttm IS
    '市销率，营业收入取 TTM。有限极端值不截断，绝对值超过 1e6 记质量审计：极端值保留原值、因子层处理。';
