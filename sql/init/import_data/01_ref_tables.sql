-- ============================================================
-- 参考数据 (ref)
-- ============================================================

-- 交易日历
CREATE TABLE IF NOT EXISTS ref.calendar (
    exchange         VARCHAR(20)  NOT NULL,
    dt               DATE         NOT NULL,
    is_trading       BOOLEAN      NOT NULL DEFAULT FALSE,
    prev_trading_day DATE,
    next_trading_day DATE,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, dt),
    CONSTRAINT chk_calendar_exchange_not_blank
        CHECK (btrim(exchange) <> ''),
    CONSTRAINT chk_calendar_prev_before_dt
        CHECK (prev_trading_day IS NULL OR prev_trading_day < dt),
    CONSTRAINT chk_calendar_next_after_dt
        CHECK (next_trading_day IS NULL OR next_trading_day > dt)
);

CREATE INDEX IF NOT EXISTS idx_calendar_trading
    ON ref.calendar (exchange, is_trading, dt);

-- 标的代码映射 (多数据源)
CREATE TABLE IF NOT EXISTS ref.symbol_mapping (
    symbol        TEXT        NOT NULL,
    provider      VARCHAR(20) NOT NULL,
    mapped_symbol TEXT        NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, symbol),
    UNIQUE (provider, mapped_symbol),
    CONSTRAINT chk_symbol_mapping_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_symbol_mapping_provider_not_blank
        CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_symbol_mapping_mapped_symbol_not_blank
        CHECK (btrim(mapped_symbol) <> '')
);

CREATE INDEX IF NOT EXISTS idx_symbol_mapping_symbol
    ON ref.symbol_mapping (symbol);
