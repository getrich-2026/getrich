-- 036_market_ext.sql
-- market schema 的扩展：复权因子明细表，以及 stock_daily_basic 的归属澄清。
--
-- 对应 getrich-design `dataapi/tushare-api/tushare_integration_plan.md` 的 D7 与 §12.1-3。

CREATE SCHEMA IF NOT EXISTS market;

-- ---------------------------------------------------------------------------
-- market.adj_factor_ts —— 每日单值复权因子的明细序列（D7）
-- ---------------------------------------------------------------------------
-- 为什么既填 market.*_bar_1d.adj_factor 列、又单独建这张表：
--   * canonical 列是给「取一段行情顺手拿复权因子」用的，随行情表的生命周期走；
--   * 这张表不依赖任何行情表，能独立回补、独立比对多个 source 的因子序列。
--     PK 含 source，正是为了让两家供应商的因子能并存后逐日对账 —— 复权因子
--     一旦错了，整段历史价格会系统性偏移，而回测不会报错。
CREATE TABLE IF NOT EXISTS market.adj_factor_ts (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day   DATE NOT NULL,
    adj_factor    NUMERIC(18,8) NOT NULL,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_adj_factor_ts_positive CHECK (adj_factor > 0)
);

SELECT create_hypertable('market.adj_factor_ts', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_adj_factor_ts_trading_day
    ON market.adj_factor_ts USING BRIN (trading_day);

COMMENT ON TABLE market.adj_factor_ts IS
    '每日单值复权因子明细。与 market.<asset>_bar_1d.adj_factor 同语义，但独立于行情表，可多 source 并存对账。';
COMMENT ON COLUMN market.adj_factor_ts.adj_factor IS
    'tushare adj_factor 原值，不做任何缩放。前复权价 = close * adj_factor / 最新 adj_factor。';

-- ---------------------------------------------------------------------------
-- market.stock_daily_basic 的归属澄清（§12.1-3）
-- ---------------------------------------------------------------------------
-- 这张表的 DDL 在 007_insight.sql 里，但 insight 侧从未实现过写入（无 importer、
-- 供应商文档也没映射到这个表名），实际 owner 是 tushare 的 daily_basic。
-- 不把 DDL 迁到本文件：迁移意味着先 DROP 再重建，而 lint_migrations.py 禁
-- DROP COLUMN、checksum 变更还会让文件重放，代价远大于收益。
-- 把这条不一致记在库里，比记在 issue 里更不容易丢。
COMMENT ON TABLE market.stock_daily_basic IS
    '股票每日指标。owner=tushare（接口 daily_basic）；表结构沿用 insight 时代的形状，DDL 仍在 007_insight.sql。tushare 的 pe/pb/ps/dv/股本等列在这里没有对应实体列，存于 raw_payload；面向分析的规整形态见 fundamental.valuation_1d。';
