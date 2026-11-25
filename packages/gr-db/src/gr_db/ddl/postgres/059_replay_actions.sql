CREATE SCHEMA IF NOT EXISTS finance;

CREATE TABLE IF NOT EXISTS finance.dividend (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    period_end DATE NOT NULL,
    implementation_date DATE NOT NULL,
    record_date DATE,
    ex_date DATE,
    pay_date DATE,
    share_listing_date DATE,
    cash_per_share NUMERIC CHECK (cash_per_share >= 0 AND cash_per_share < 'Infinity'::numeric),
    shares_per_share NUMERIC CHECK (shares_per_share >= 0 AND shares_per_share < 'Infinity'::numeric),
    source TEXT NOT NULL CHECK (source = 'tushare'),
    raw_sha256 TEXT NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (instrument_id, period_end, implementation_date)
);
COMMENT ON TABLE finance.dividend IS 'DS06 已实施分配方案；来自当前供应商观察，空日期或数值表示缺证，不能据稀疏事件推断历史覆盖。';
COMMENT ON COLUMN finance.dividend.instrument_id IS 'meta.symbol_map 映射的股票标识。';
COMMENT ON COLUMN finance.dividend.period_end IS '源 end_date，分配所属报告期。';
COMMENT ON COLUMN finance.dividend.implementation_date IS '实施公告日 imp_ann_date，仅有日粒度；盘前决策只能使用此前日期已公告的方案。';
COMMENT ON COLUMN finance.dividend.record_date IS '股权登记日。';
COMMENT ON COLUMN finance.dividend.ex_date IS '除权除息日。';
COMMENT ON COLUMN finance.dividend.pay_date IS '现金派息日。';
COMMENT ON COLUMN finance.dividend.share_listing_date IS '送转股上市日。';
COMMENT ON COLUMN finance.dividend.cash_per_share IS '源 cash_div_tax，每股税前现金分红，人民币元；未知保留 NULL。';
COMMENT ON COLUMN finance.dividend.shares_per_share IS '源 stk_div，每股送转股数；未知保留 NULL。';
COMMENT ON COLUMN finance.dividend.source IS '供应商标识，与表归属一致。';
COMMENT ON COLUMN finance.dividend.raw_sha256 IS '供应商原始 Parquet 文件 SHA-256。';

CREATE TABLE IF NOT EXISTS market.stock_delisting (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    delist_date DATE NOT NULL,
    source TEXT NOT NULL CHECK (source = 'tushare'),
    raw_sha256 TEXT NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (instrument_id, delist_date)
);
COMMENT ON TABLE market.stock_delisting IS 'DS07 明确退市截断日期；来源未提供可靠终值，回放不得延用最后收盘价或归零。';
COMMENT ON COLUMN market.stock_delisting.instrument_id IS 'meta.symbol_map 映射的股票标识。';
COMMENT ON COLUMN market.stock_delisting.delist_date IS '源 stock_basic 的退市日期，回放最晚在当日显式截断。';
COMMENT ON COLUMN market.stock_delisting.source IS '供应商标识，与表归属一致。';
COMMENT ON COLUMN market.stock_delisting.raw_sha256 IS '供应商原始 Parquet 文件 SHA-256。';
