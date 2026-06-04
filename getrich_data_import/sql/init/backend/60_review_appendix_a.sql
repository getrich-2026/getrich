-- Code review appendix A schema additions:
-- raw source fields for daily/minute bars plus stock/ETF market tables.

ALTER TABLE market.index_bar_1d ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.index_bar_1d ADD COLUMN IF NOT EXISTS limit_up NUMERIC(20,6);
ALTER TABLE market.index_bar_1d ADD COLUMN IF NOT EXISTS limit_down NUMERIC(20,6);
ALTER TABLE market.index_bar_1d ADD COLUMN IF NOT EXISTS trading_status VARCHAR(16);

ALTER TABLE market.future_bar_1d ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.future_bar_1d ADD COLUMN IF NOT EXISTS pre_settle NUMERIC(20,6);
ALTER TABLE market.future_bar_1d ADD COLUMN IF NOT EXISTS limit_up NUMERIC(20,6);
ALTER TABLE market.future_bar_1d ADD COLUMN IF NOT EXISTS limit_down NUMERIC(20,6);
ALTER TABLE market.future_bar_1d ADD COLUMN IF NOT EXISTS trading_status VARCHAR(16);

ALTER TABLE market.option_bar_1d ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.option_bar_1d ADD COLUMN IF NOT EXISTS pre_settle NUMERIC(20,6);
ALTER TABLE market.option_bar_1d ADD COLUMN IF NOT EXISTS limit_up NUMERIC(20,6);
ALTER TABLE market.option_bar_1d ADD COLUMN IF NOT EXISTS limit_down NUMERIC(20,6);
ALTER TABLE market.option_bar_1d ADD COLUMN IF NOT EXISTS trading_status VARCHAR(16);

ALTER TABLE market.index_bar_1m ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.future_bar_1m ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.future_bar_1m ADD COLUMN IF NOT EXISTS pre_settle NUMERIC(20,6);
ALTER TABLE market.option_bar_1m ADD COLUMN IF NOT EXISTS pre_close NUMERIC(20,6);
ALTER TABLE market.option_bar_1m ADD COLUMN IF NOT EXISTS pre_settle NUMERIC(20,6);

COMMENT ON TABLE market.index_bar_1m IS 'Minute bars are raw/unadjusted; join market.index_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';
COMMENT ON TABLE market.future_bar_1m IS 'Minute bars are raw/unadjusted; join market.future_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';
COMMENT ON TABLE market.option_bar_1m IS 'Minute bars are raw/unadjusted; join market.option_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.stock_bar_1d (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             DATE NOT NULL,
    trading_day    DATE NOT NULL,
    open           NUMERIC(20,6),
    high           NUMERIC(20,6),
    low            NUMERIC(20,6),
    close          NUMERIC(20,6),
    pre_close      NUMERIC(20,6),
    volume         BIGINT,
    amount         NUMERIC(24,4),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    adj_factor     NUMERIC(18,8) NOT NULL DEFAULT 1,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_stock_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_stock_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_stock_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.stock_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.stock_bar_1m (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            TIMESTAMPTZ NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    pre_close     NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_stock_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_stock_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.stock_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.stock_bar_1m IS 'Minute bars are raw/unadjusted; join market.stock_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.etf_bar_1d (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             DATE NOT NULL,
    trading_day    DATE NOT NULL,
    open           NUMERIC(20,6),
    high           NUMERIC(20,6),
    low            NUMERIC(20,6),
    close          NUMERIC(20,6),
    pre_close      NUMERIC(20,6),
    volume         BIGINT,
    amount         NUMERIC(24,4),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    adj_factor     NUMERIC(18,8) NOT NULL DEFAULT 1,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_etf_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_etf_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_etf_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.etf_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.etf_bar_1m (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            TIMESTAMPTZ NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    pre_close     NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_etf_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_etf_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.etf_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.etf_bar_1m IS 'Minute bars are raw/unadjusted; join market.etf_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE INDEX IF NOT EXISTS idx_stock_bar_1d_trading_day ON market.stock_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_stock_bar_1m_trading_day ON market.stock_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_etf_bar_1d_trading_day ON market.etf_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_etf_bar_1m_trading_day ON market.etf_bar_1m USING brin (trading_day);
