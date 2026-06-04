-- Historical market facts. PostgreSQL + TimescaleDB is the authority store.

CREATE TABLE IF NOT EXISTS market.index_bar_1d (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            DATE NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    adj_factor    NUMERIC(18,8) NOT NULL DEFAULT 1,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_index_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_index_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_index_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.index_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.future_bar_1d (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            DATE NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    open_interest BIGINT,
    settle        NUMERIC(20,6),
    adj_factor    NUMERIC(18,8) NOT NULL DEFAULT 1,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_future_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_future_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_future_1d_oi CHECK (open_interest IS NULL OR open_interest >= 0),
    CONSTRAINT chk_future_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.future_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.option_bar_1d (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            DATE NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    open_interest BIGINT,
    settle        NUMERIC(20,6),
    adj_factor    NUMERIC(18,8) NOT NULL DEFAULT 1,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_option_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_option_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_option_1d_oi CHECK (open_interest IS NULL OR open_interest >= 0),
    CONSTRAINT chk_option_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.option_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.index_bar_1m (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            TIMESTAMPTZ NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_index_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_index_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.index_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.future_bar_1m (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            TIMESTAMPTZ NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    open_interest BIGINT,
    settle        NUMERIC(20,6),
    is_dominant   BOOLEAN NOT NULL DEFAULT false,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_future_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_future_1m_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_future_1m_oi CHECK (open_interest IS NULL OR open_interest >= 0)
);
SELECT create_hypertable('market.future_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.option_bar_1m (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt            TIMESTAMPTZ NOT NULL,
    trading_day   DATE NOT NULL,
    open          NUMERIC(20,6),
    high          NUMERIC(20,6),
    low           NUMERIC(20,6),
    close         NUMERIC(20,6),
    volume        BIGINT,
    amount        NUMERIC(24,4),
    open_interest BIGINT,
    settle        NUMERIC(20,6),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_option_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_option_1m_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_option_1m_oi CHECK (open_interest IS NULL OR open_interest >= 0)
);
SELECT create_hypertable('market.option_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_index_bar_1d_trading_day ON market.index_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_future_bar_1d_trading_day ON market.future_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_option_bar_1d_trading_day ON market.option_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_index_bar_1m_trading_day ON market.index_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_future_bar_1m_trading_day ON market.future_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_option_bar_1m_trading_day ON market.option_bar_1m USING brin (trading_day);

CREATE TABLE IF NOT EXISTS market.option_greeks_1d (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day    DATE NOT NULL,
    iv             NUMERIC(12,8),
    delta          NUMERIC(12,8),
    gamma          NUMERIC(12,8),
    vega           NUMERIC(12,8),
    theta          NUMERIC(12,8),
    rho            NUMERIC(12,8),
    underlying_px  NUMERIC(20,6),
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day)
);
