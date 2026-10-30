-- Historical market facts. PostgreSQL + TimescaleDB is the authority store.

CREATE TABLE IF NOT EXISTS market.index_bar_1d (
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
    CONSTRAINT chk_index_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_index_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_index_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.index_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

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
    price_limit_status VARCHAR(16),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_stock_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_stock_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_stock_1d_factor CHECK (adj_factor > 0),
    CONSTRAINT chk_stock_1d_price_limit_status CHECK (
        price_limit_status IS NULL
        OR price_limit_status IN ('LIMITED', 'NO_LIMIT', 'UNKNOWN')
    ),
    CONSTRAINT chk_stock_1d_price_limit_consistency CHECK (
        (price_limit_status IS DISTINCT FROM 'LIMITED'
            OR (limit_up IS NOT NULL AND limit_down IS NOT NULL))
        AND (price_limit_status IS DISTINCT FROM 'NO_LIMIT'
            OR (limit_up IS NULL AND limit_down IS NULL))
    )
);
SELECT create_hypertable('market.stock_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

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

CREATE TABLE IF NOT EXISTS market.future_bar_1d (
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
    open_interest  BIGINT,
    settle         NUMERIC(20,6),
    pre_settle     NUMERIC(20,6),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    adj_factor     NUMERIC(18,8) NOT NULL DEFAULT 1,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_future_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_future_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_future_1d_oi CHECK (open_interest IS NULL OR open_interest >= 0),
    CONSTRAINT chk_future_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.future_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.option_bar_1d (
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
    open_interest  BIGINT,
    settle         NUMERIC(20,6),
    pre_settle     NUMERIC(20,6),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    adj_factor     NUMERIC(18,8) NOT NULL DEFAULT 1,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_option_1d_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_option_1d_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_option_1d_oi CHECK (open_interest IS NULL OR open_interest >= 0),
    CONSTRAINT chk_option_1d_factor CHECK (adj_factor > 0)
);
SELECT create_hypertable('market.option_bar_1d', 'dt', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.index_bar_1m (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
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
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_index_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_index_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.index_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.index_bar_1m IS 'Minute bars are raw/unadjusted; join market.index_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.stock_bar_1m (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
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
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_stock_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_stock_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.stock_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.stock_bar_1m IS 'Minute bars are raw/unadjusted; join market.stock_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.etf_bar_1m (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
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
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_etf_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_etf_1m_volume CHECK (volume IS NULL OR volume >= 0)
);
SELECT create_hypertable('market.etf_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.etf_bar_1m IS 'Minute bars are raw/unadjusted; join market.etf_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.future_bar_1m (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
    trading_day    DATE NOT NULL,
    open           NUMERIC(20,6),
    high           NUMERIC(20,6),
    low            NUMERIC(20,6),
    close          NUMERIC(20,6),
    pre_close      NUMERIC(20,6),
    volume         BIGINT,
    amount         NUMERIC(24,4),
    open_interest  BIGINT,
    settle         NUMERIC(20,6),
    pre_settle     NUMERIC(20,6),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    is_dominant    BOOLEAN NOT NULL DEFAULT false,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_future_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_future_1m_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_future_1m_oi CHECK (open_interest IS NULL OR open_interest >= 0)
);
SELECT create_hypertable('market.future_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.future_bar_1m IS 'Minute bars are raw/unadjusted; join market.future_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE TABLE IF NOT EXISTS market.option_bar_1m (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
    trading_day    DATE NOT NULL,
    open           NUMERIC(20,6),
    high           NUMERIC(20,6),
    low            NUMERIC(20,6),
    close          NUMERIC(20,6),
    pre_close      NUMERIC(20,6),
    volume         BIGINT,
    amount         NUMERIC(24,4),
    open_interest  BIGINT,
    settle         NUMERIC(20,6),
    pre_settle     NUMERIC(20,6),
    limit_up       NUMERIC(20,6),
    limit_down     NUMERIC(20,6),
    trading_status VARCHAR(16),
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt),
    CONSTRAINT chk_option_1m_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_option_1m_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_option_1m_oi CHECK (open_interest IS NULL OR open_interest >= 0)
);
SELECT create_hypertable('market.option_bar_1m', 'dt', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
COMMENT ON TABLE market.option_bar_1m IS 'Minute bars are raw/unadjusted; join market.option_bar_1d on instrument_id and trading_day for daily adj_factor when adjustment is required.';

CREATE INDEX IF NOT EXISTS idx_index_bar_1d_trading_day ON market.index_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_stock_bar_1d_trading_day ON market.stock_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_etf_bar_1d_trading_day ON market.etf_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_future_bar_1d_trading_day ON market.future_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_option_bar_1d_trading_day ON market.option_bar_1d USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_index_bar_1m_trading_day ON market.index_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_stock_bar_1m_trading_day ON market.stock_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_etf_bar_1m_trading_day ON market.etf_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_future_bar_1m_trading_day ON market.future_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_option_bar_1m_trading_day ON market.option_bar_1m USING brin (trading_day);
CREATE INDEX IF NOT EXISTS idx_index_bar_1m_dt ON market.index_bar_1m USING brin (dt);
CREATE INDEX IF NOT EXISTS idx_stock_bar_1m_dt ON market.stock_bar_1m USING brin (dt);
CREATE INDEX IF NOT EXISTS idx_etf_bar_1m_dt ON market.etf_bar_1m USING brin (dt);
CREATE INDEX IF NOT EXISTS idx_future_bar_1m_dt ON market.future_bar_1m USING brin (dt);
CREATE INDEX IF NOT EXISTS idx_option_bar_1m_dt ON market.option_bar_1m USING brin (dt);

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
CREATE INDEX IF NOT EXISTS idx_option_greeks_1d_trading_day ON market.option_greeks_1d USING brin (trading_day);

COMMENT ON COLUMN market.stock_bar_1d.price_limit_status IS
    '涨跌停价状态。LIMITED：当日有涨跌幅限制，limit_up/limit_down 均有效；NO_LIMIT：当日不设涨跌幅（供应商哨兵值已写为 NULL）；UNKNOWN：涨跌停价缺失、非法或不可信，可保留单边有效值；NULL：未评估（例如未提供该状态的供应商）。回放判断开盘是否达到涨停价时须区分 NO_LIMIT 与 UNKNOWN。';

COMMENT ON CONSTRAINT chk_stock_1d_price_limit_status ON market.stock_bar_1d IS
    'price_limit_status 只允许 LIMITED/NO_LIMIT/UNKNOWN 或 NULL（未评估）。';

COMMENT ON CONSTRAINT chk_stock_1d_price_limit_consistency ON market.stock_bar_1d IS
    'LIMITED 要求两侧涨跌停价都有值；NO_LIMIT 要求两侧都为 NULL，防止哨兵值被当作价格写入。';

-- 分钟超表存储配置；须在 create_hypertable 之后设置。
DO $$
BEGIN
    ALTER TABLE market.index_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.index_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.index_bar_1m: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER TABLE market.stock_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.stock_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.stock_bar_1m: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER TABLE market.etf_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.etf_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.etf_bar_1m: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER TABLE market.future_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.future_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.future_bar_1m: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER TABLE market.option_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.option_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.option_bar_1m: %', SQLERRM;
END $$;
