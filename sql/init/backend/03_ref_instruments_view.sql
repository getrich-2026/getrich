-- ============================================================
-- 统一标的表 re.instruments
-- 整合所有标的类型（股票/ETF/LOF/指数/期货/现货/期权/可转债/回购），
-- 供上层统一查询。缺失值保留 NULL，避免把未知值误表示为 0 或空字符串。
-- 字段对齐原 RiceQuant 分表统一视图的输出列。
-- ============================================================

CREATE TABLE IF NOT EXISTS re.instruments (
    symbol         TEXT             NOT NULL,                   -- 统一代码 (order_book_id)
    symbol_raw     TEXT,                                        -- 数据源原始代码 (trading_code)
    exchange       TEXT,                                        -- 交易所
    name           TEXT,                                        -- 标的名称
    type           TEXT,                                        -- 标的类型: CS/ETF/LOF/INDX/Future/Spot/Option/Convertible/Repo
    und_code       TEXT,                                        -- 标的物代码 (underlying)
    und_name       TEXT,                                        -- 标的物名称 (underlying)
    multiplier     DOUBLE PRECISION,                            -- 合约乘数 (缺失保留 NULL)
    margin_ratio   DOUBLE PRECISION,                            -- 保证金率
    strike_price   DOUBLE PRECISION,                            -- 行权价 (期权)
    option_type    TEXT,                                        -- 期权类型 (C/P)
    exercise_type  TEXT,                                        -- 行权方式
    currency       TEXT             NOT NULL DEFAULT 'CNY',      -- 计价货币
    listed_date    DATE,                                        -- 上市日
    delisted_date  DATE,                                        -- 退市日
    provider       TEXT             NOT NULL DEFAULT 'UNKNOWN',  -- 数据来源
    updated_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),      -- 入库时间
    PRIMARY KEY (symbol),
    CONSTRAINT chk_instruments_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_instruments_multiplier_positive
        CHECK (multiplier IS NULL OR multiplier > 0),
    CONSTRAINT chk_instruments_margin_ratio_non_negative
        CHECK (margin_ratio IS NULL OR margin_ratio >= 0),
    CONSTRAINT chk_instruments_strike_price_positive
        CHECK (strike_price IS NULL OR strike_price > 0),
    CONSTRAINT chk_instruments_listed_before_delisted
        CHECK (listed_date IS NULL OR delisted_date IS NULL OR listed_date <= delisted_date)
);

CREATE INDEX IF NOT EXISTS idx_instruments_type
    ON re.instruments (type);
CREATE INDEX IF NOT EXISTS idx_instruments_exchange
    ON re.instruments (exchange);
CREATE INDEX IF NOT EXISTS idx_instruments_provider
    ON re.instruments (provider);
CREATE INDEX IF NOT EXISTS idx_instruments_und_code
    ON re.instruments (und_code);
