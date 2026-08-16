-- INSIGHT dataset catalog, Parquet staging manifest, checkpoints, and P1 canonical facts.

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS ops.dataset_catalog (
    provider             VARCHAR(32) NOT NULL,
    dataset_name         VARCHAR(96) NOT NULL,
    phase                VARCHAR(8) NOT NULL,
    status               VARCHAR(16) NOT NULL,
    storage              VARCHAR(24) NOT NULL,
    target               TEXT NOT NULL,
    asset                VARCHAR(16),
    freq                 VARCHAR(8),
    source_method        TEXT,
    permission_tier      VARCHAR(32) NOT NULL DEFAULT 'standard',
    supports_incremental BOOLEAN NOT NULL DEFAULT true,
    description          TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, dataset_name),
    CONSTRAINT chk_dataset_catalog_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_dataset_catalog_name_not_blank CHECK (btrim(dataset_name) <> ''),
    CONSTRAINT chk_dataset_catalog_status CHECK (status IN ('ready', 'planned', 'deprecated')),
    CONSTRAINT chk_dataset_catalog_storage CHECK (storage IN ('postgres', 'timescale', 'parquet_staging', 'config'))
);

CREATE INDEX IF NOT EXISTS idx_dataset_catalog_phase_status
    ON ops.dataset_catalog (provider, phase, status);

CREATE TABLE IF NOT EXISTS ops.import_checkpoint (
    provider       VARCHAR(32) NOT NULL,
    dataset_name   VARCHAR(96) NOT NULL,
    partition_key  TEXT NOT NULL,
    watermark_date DATE,
    watermark_ts   TIMESTAMPTZ,
    state          JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, dataset_name, partition_key),
    CONSTRAINT chk_import_checkpoint_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_import_checkpoint_dataset_not_blank CHECK (btrim(dataset_name) <> ''),
    CONSTRAINT chk_import_checkpoint_partition_not_blank CHECK (btrim(partition_key) <> '')
);

CREATE INDEX IF NOT EXISTS idx_import_checkpoint_updated_at
    ON ops.import_checkpoint (updated_at);

CREATE TABLE IF NOT EXISTS staging.parquet_file (
    file_id            BIGSERIAL PRIMARY KEY,
    provider           VARCHAR(32) NOT NULL,
    dataset_name       VARCHAR(96) NOT NULL,
    asset              VARCHAR(16),
    freq               VARCHAR(8),
    source_path        TEXT NOT NULL,
    content_hash       VARCHAR(128),
    file_size_bytes    BIGINT,
    row_count          BIGINT,
    start_date         DATE,
    end_date           DATE,
    partition_key      TEXT,
    schema_fingerprint VARCHAR(128),
    status             VARCHAR(16) NOT NULL DEFAULT 'written',
    fetch_run_id       BIGINT REFERENCES ops.etl_job_run(run_id),
    load_run_id        BIGINT REFERENCES ops.etl_job_run(run_id),
    metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_at          TIMESTAMPTZ,
    error              TEXT,
    UNIQUE (provider, dataset_name, source_path),
    CONSTRAINT chk_parquet_file_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_parquet_file_dataset_not_blank CHECK (btrim(dataset_name) <> ''),
    CONSTRAINT chk_parquet_file_source_path_not_blank CHECK (btrim(source_path) <> ''),
    CONSTRAINT chk_parquet_file_size CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    CONSTRAINT chk_parquet_file_row_count CHECK (row_count IS NULL OR row_count >= 0),
    CONSTRAINT chk_parquet_file_date_range CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date),
    CONSTRAINT chk_parquet_file_status CHECK (status IN ('written', 'loaded', 'failed', 'superseded'))
);

CREATE INDEX IF NOT EXISTS idx_parquet_file_dataset_range
    ON staging.parquet_file (provider, dataset_name, start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_parquet_file_status
    ON staging.parquet_file (provider, dataset_name, status);

CREATE INDEX IF NOT EXISTS idx_parquet_file_metadata
    ON staging.parquet_file USING gin (metadata);

CREATE TABLE IF NOT EXISTS market.stock_adj_factor (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    begin_date    DATE NOT NULL,
    xdy           NUMERIC(20,10),
    b_xdy         NUMERIC(20,10),
    f_xdy         NUMERIC(20,10),
    source        VARCHAR(32) NOT NULL,
    raw_payload   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, begin_date, source),
    CONSTRAINT chk_stock_adj_factor_positive CHECK (
        (xdy IS NULL OR xdy > 0)
        AND (b_xdy IS NULL OR b_xdy > 0)
        AND (f_xdy IS NULL OR f_xdy > 0)
    )
);
SELECT create_hypertable('market.stock_adj_factor', 'begin_date', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.stock_daily_basic (
    instrument_id                       BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day                         DATE NOT NULL,
    trading_state                       VARCHAR(32),
    open                                NUMERIC(20,6),
    high                                NUMERIC(20,6),
    low                                 NUMERIC(20,6),
    close                               NUMERIC(20,6),
    pre_close                           NUMERIC(20,6),
    backward_adjusted_closing_price     NUMERIC(20,6),
    volume                              BIGINT,
    amount                              NUMERIC(24,4),
    day_change                          NUMERIC(20,6),
    turnover_rate                       NUMERIC(18,8),
    amplitude                           NUMERIC(18,8),
    avg_price                           NUMERIC(20,6),
    avg_volume_per_trade                NUMERIC(24,6),
    avg_amount_per_trade                NUMERIC(24,6),
    float_market_cap                    NUMERIC(28,4),
    total_market_cap                    NUMERIC(28,4),
    num_trades                          BIGINT,
    source                              VARCHAR(32) NOT NULL,
    raw_payload                         JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_stock_daily_basic_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_stock_daily_basic_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_stock_daily_basic_trades CHECK (num_trades IS NULL OR num_trades >= 0)
);
SELECT create_hypertable('market.stock_daily_basic', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.stock_valuation (
    instrument_id          BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day            DATE NOT NULL,
    close                  NUMERIC(20,6),
    front_adjusted_close   NUMERIC(20,6),
    back_adjusted_close    NUMERIC(20,6),
    pe                     NUMERIC(20,8),
    pe_ttm                 NUMERIC(20,8),
    pb                     NUMERIC(20,8),
    pc                     NUMERIC(20,8),
    pc_ttm                 NUMERIC(20,8),
    ps                     NUMERIC(20,8),
    ps_ttm                 NUMERIC(20,8),
    avg_price              NUMERIC(20,6),
    avg_volume_per_trade   NUMERIC(24,6),
    avg_amount_per_trade   NUMERIC(24,6),
    float_market_cap       NUMERIC(28,4),
    total_market_cap       NUMERIC(28,4),
    source                 VARCHAR(32) NOT NULL,
    raw_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source)
);
SELECT create_hypertable('market.stock_valuation', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.index_component (
    index_instrument_id     BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    component_instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day             DATE NOT NULL,
    weight                  NUMERIC(18,10),
    in_date                 DATE,
    out_date                DATE,
    source                  VARCHAR(32) NOT NULL,
    raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_instrument_id, component_instrument_id, trading_day, source),
    CONSTRAINT chk_index_component_weight CHECK (weight IS NULL OR weight >= 0)
);
SELECT create_hypertable('market.index_component', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_index_component_component_day
    ON market.index_component (component_instrument_id, trading_day);

CREATE TABLE IF NOT EXISTS market.etf_daily (
    instrument_id                 BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day                   DATE NOT NULL,
    delisting_date                DATE,
    trading_state                 VARCHAR(32),
    open                          NUMERIC(20,6),
    high                          NUMERIC(20,6),
    low                           NUMERIC(20,6),
    close                         NUMERIC(20,6),
    pre_close                     NUMERIC(20,6),
    backward_adjusted_close       NUMERIC(20,6),
    unit_nav                      NUMERIC(20,8),
    accumulated_nav               NUMERIC(20,8),
    discount_rate                 NUMERIC(18,8),
    premium_rate                  NUMERIC(18,8),
    discount                      NUMERIC(20,8),
    discount_ratio                NUMERIC(18,8),
    day_change                    NUMERIC(20,6),
    day_change_rate               NUMERIC(18,8),
    turnover_rate                 NUMERIC(18,8),
    amplitude                     NUMERIC(18,8),
    volume                        BIGINT,
    amount                        NUMERIC(24,4),
    num_trades                    BIGINT,
    source                        VARCHAR(32) NOT NULL,
    raw_payload                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_etf_daily_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_etf_daily_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_etf_daily_trades CHECK (num_trades IS NULL OR num_trades >= 0)
);
SELECT create_hypertable('market.etf_daily', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.etf_nav (
    instrument_id          BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    end_date               DATE NOT NULL,
    unit_nav               NUMERIC(20,8),
    accumulated_nav        NUMERIC(20,8),
    adjusted_nav           NUMERIC(20,8),
    return_1d              NUMERIC(18,8),
    return_1w              NUMERIC(18,8),
    return_1w_rank         NUMERIC(18,8),
    return_1m              NUMERIC(18,8),
    return_1m_rank         NUMERIC(18,8),
    return_3m              NUMERIC(18,8),
    return_3m_rank         NUMERIC(18,8),
    return_6m              NUMERIC(18,8),
    return_6m_rank         NUMERIC(18,8),
    return_1y              NUMERIC(18,8),
    return_1y_rank         NUMERIC(18,8),
    return_ytd             NUMERIC(18,8),
    return_ytd_rank        NUMERIC(18,8),
    return_3y              NUMERIC(18,8),
    return_5y              NUMERIC(18,8),
    return_since_listing   NUMERIC(18,8),
    nav_volatility         NUMERIC(18,8),
    beta                   NUMERIC(18,8),
    sharpe                 NUMERIC(18,8),
    jensen                 NUMERIC(18,8),
    treynor                NUMERIC(18,8),
    r_squared              NUMERIC(18,8),
    source                 VARCHAR(32) NOT NULL,
    raw_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, end_date, source)
);
SELECT create_hypertable('market.etf_nav', 'end_date', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.fund_daily (
    instrument_id                 BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day                   DATE NOT NULL,
    delisting_date                DATE,
    trading_state                 VARCHAR(32),
    open                          NUMERIC(20,6),
    high                          NUMERIC(20,6),
    low                           NUMERIC(20,6),
    close                         NUMERIC(20,6),
    pre_close                     NUMERIC(20,6),
    backward_adjusted_close       NUMERIC(20,6),
    unit_nav                      NUMERIC(20,8),
    accumulated_nav               NUMERIC(20,8),
    discount_rate                 NUMERIC(18,8),
    premium_rate                  NUMERIC(18,8),
    discount                      NUMERIC(20,8),
    discount_ratio                NUMERIC(18,8),
    day_change                    NUMERIC(20,6),
    day_change_rate               NUMERIC(18,8),
    turnover_rate                 NUMERIC(18,8),
    amplitude                     NUMERIC(18,8),
    volume                        BIGINT,
    amount                        NUMERIC(24,4),
    num_trades                    BIGINT,
    source                        VARCHAR(32) NOT NULL,
    raw_payload                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_fund_daily_ohlc CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_fund_daily_volume CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_fund_daily_trades CHECK (num_trades IS NULL OR num_trades >= 0)
);
SELECT create_hypertable('market.fund_daily', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.fund_nav (
    instrument_id          BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    end_date               DATE NOT NULL,
    unit_nav               NUMERIC(20,8),
    accumulated_nav        NUMERIC(20,8),
    adjusted_nav           NUMERIC(20,8),
    return_1d              NUMERIC(18,8),
    return_1w              NUMERIC(18,8),
    return_1w_rank         NUMERIC(18,8),
    return_1m              NUMERIC(18,8),
    return_1m_rank         NUMERIC(18,8),
    return_3m              NUMERIC(18,8),
    return_3m_rank         NUMERIC(18,8),
    return_6m              NUMERIC(18,8),
    return_6m_rank         NUMERIC(18,8),
    return_1y              NUMERIC(18,8),
    return_1y_rank         NUMERIC(18,8),
    return_ytd             NUMERIC(18,8),
    return_ytd_rank        NUMERIC(18,8),
    return_3y              NUMERIC(18,8),
    return_5y              NUMERIC(18,8),
    return_since_listing   NUMERIC(18,8),
    nav_volatility         NUMERIC(18,8),
    beta                   NUMERIC(18,8),
    sharpe                 NUMERIC(18,8),
    jensen                 NUMERIC(18,8),
    treynor                NUMERIC(18,8),
    r_squared              NUMERIC(18,8),
    source                 VARCHAR(32) NOT NULL,
    raw_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, end_date, source)
);
SELECT create_hypertable('market.fund_nav', 'end_date', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS market.etf_basket (
    etf_instrument_id        BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    component_symbol         VARCHAR(128) NOT NULL,
    component_instrument_id  BIGINT REFERENCES meta.instruments(instrument_id),
    trading_day              DATE NOT NULL,
    pub_date                 DATE,
    sub_component_list       VARCHAR(32),
    component_type           VARCHAR(32),
    quantity                 NUMERIC(24,6),
    unit                     VARCHAR(32),
    cash_substitute_flag     VARCHAR(32),
    cash_substitute_rate     NUMERIC(18,8),
    cash_substitute_amount   NUMERIC(24,4),
    subscription_substitute_amount NUMERIC(24,4),
    redemption_substitute_amount NUMERIC(24,4),
    source                   VARCHAR(32) NOT NULL,
    raw_payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (etf_instrument_id, component_symbol, trading_day, source),
    CONSTRAINT chk_etf_basket_component_not_blank CHECK (btrim(component_symbol) <> '')
);
SELECT create_hypertable('market.etf_basket', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_etf_basket_component_day
    ON market.etf_basket (component_instrument_id, trading_day);

CREATE TABLE IF NOT EXISTS market.etf_redemption (
    instrument_id              BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day                DATE NOT NULL,
    cash_difference            NUMERIC(24,4),
    estimated_cash_difference  NUMERIC(24,4),
    creation_redemption_unit   BIGINT,
    max_cash_ratio             NUMERIC(18,8),
    iopv                       NUMERIC(20,8),
    nav_per_unit               NUMERIC(20,8),
    creation_limit             BIGINT,
    redemption_limit           BIGINT,
    source                     VARCHAR(32) NOT NULL,
    raw_payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, source),
    CONSTRAINT chk_etf_redemption_unit CHECK (creation_redemption_unit IS NULL OR creation_redemption_unit >= 0),
    CONSTRAINT chk_etf_redemption_limits CHECK (
        (creation_limit IS NULL OR creation_limit >= 0)
        AND (redemption_limit IS NULL OR redemption_limit >= 0)
    )
);
SELECT create_hypertable('market.etf_redemption', 'trading_day', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

CREATE OR REPLACE VIEW market.v_stock_daily_basic AS
SELECT
    b.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    b.trading_day,
    b.trading_state,
    b.open,
    b.high,
    b.low,
    b.close,
    b.pre_close,
    b.backward_adjusted_closing_price,
    b.volume,
    b.amount,
    b.day_change,
    b.turnover_rate,
    b.amplitude,
    b.float_market_cap,
    b.total_market_cap,
    b.updated_at
FROM market.stock_daily_basic b
JOIN meta.instruments i
  ON i.instrument_id = b.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = b.instrument_id
 AND sm.source = b.source;

CREATE OR REPLACE VIEW market.v_stock_valuation AS
SELECT
    v.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    v.trading_day,
    v.close,
    v.front_adjusted_close,
    v.back_adjusted_close,
    v.pe,
    v.pe_ttm,
    v.pb,
    v.pc,
    v.pc_ttm,
    v.ps,
    v.ps_ttm,
    v.float_market_cap,
    v.total_market_cap,
    v.updated_at
FROM market.stock_valuation v
JOIN meta.instruments i
  ON i.instrument_id = v.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = v.instrument_id
 AND sm.source = v.source;

CREATE OR REPLACE VIEW market.v_index_component AS
SELECT
    c.source,
    COALESCE(index_sm.source_symbol, index_i.symbol) AS index_source_symbol,
    index_i.instrument_id AS index_instrument_id,
    index_i.exchange AS index_exchange,
    index_i.symbol AS index_symbol,
    index_i.name AS index_name,
    COALESCE(component_sm.source_symbol, component_i.symbol) AS component_source_symbol,
    component_i.instrument_id AS component_instrument_id,
    component_i.asset AS component_asset,
    component_i.exchange AS component_exchange,
    component_i.symbol AS component_symbol,
    component_i.name AS component_name,
    c.trading_day,
    c.weight,
    c.in_date,
    c.out_date,
    c.updated_at
FROM market.index_component c
JOIN meta.instruments index_i
  ON index_i.instrument_id = c.index_instrument_id
JOIN meta.instruments component_i
  ON component_i.instrument_id = c.component_instrument_id
LEFT JOIN meta.symbol_map index_sm
  ON index_sm.instrument_id = c.index_instrument_id
 AND index_sm.source = c.source
LEFT JOIN meta.symbol_map component_sm
  ON component_sm.instrument_id = c.component_instrument_id
 AND component_sm.source = c.source;

CREATE OR REPLACE VIEW market.v_etf_daily AS
SELECT
    d.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    d.trading_day,
    d.delisting_date,
    d.trading_state,
    d.open,
    d.high,
    d.low,
    d.close,
    d.pre_close,
    d.backward_adjusted_close,
    d.unit_nav,
    d.accumulated_nav,
    d.discount_rate,
    d.premium_rate,
    d.discount,
    d.discount_ratio,
    d.day_change,
    d.day_change_rate,
    d.turnover_rate,
    d.amplitude,
    d.volume,
    d.amount,
    d.num_trades,
    d.updated_at
FROM market.etf_daily d
JOIN meta.instruments i
  ON i.instrument_id = d.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = d.instrument_id
 AND sm.source = d.source;

CREATE OR REPLACE VIEW market.v_etf_nav AS
SELECT
    n.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    n.end_date,
    n.unit_nav,
    n.accumulated_nav,
    n.adjusted_nav,
    n.return_1d,
    n.return_1w,
    n.return_1m,
    n.return_3m,
    n.return_6m,
    n.return_1y,
    n.return_ytd,
    n.return_3y,
    n.return_5y,
    n.return_since_listing,
    n.nav_volatility,
    n.beta,
    n.sharpe,
    n.jensen,
    n.treynor,
    n.r_squared,
    n.updated_at
FROM market.etf_nav n
JOIN meta.instruments i
  ON i.instrument_id = n.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = n.instrument_id
 AND sm.source = n.source;

CREATE OR REPLACE VIEW market.v_fund_daily AS
SELECT
    d.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    d.trading_day,
    d.delisting_date,
    d.trading_state,
    d.open,
    d.high,
    d.low,
    d.close,
    d.pre_close,
    d.backward_adjusted_close,
    d.unit_nav,
    d.accumulated_nav,
    d.discount_rate,
    d.premium_rate,
    d.discount,
    d.discount_ratio,
    d.day_change,
    d.day_change_rate,
    d.turnover_rate,
    d.amplitude,
    d.volume,
    d.amount,
    d.num_trades,
    d.updated_at
FROM market.fund_daily d
JOIN meta.instruments i
  ON i.instrument_id = d.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = d.instrument_id
 AND sm.source = d.source;

CREATE OR REPLACE VIEW market.v_fund_nav AS
SELECT
    n.source,
    sm.source_symbol,
    i.instrument_id,
    i.asset,
    i.exchange,
    i.symbol,
    i.name,
    n.end_date,
    n.unit_nav,
    n.accumulated_nav,
    n.adjusted_nav,
    n.return_1d,
    n.return_1w,
    n.return_1m,
    n.return_3m,
    n.return_6m,
    n.return_1y,
    n.return_ytd,
    n.return_3y,
    n.return_5y,
    n.return_since_listing,
    n.nav_volatility,
    n.beta,
    n.sharpe,
    n.jensen,
    n.treynor,
    n.r_squared,
    n.updated_at
FROM market.fund_nav n
JOIN meta.instruments i
  ON i.instrument_id = n.instrument_id
JOIN meta.symbol_map sm
  ON sm.instrument_id = n.instrument_id
 AND sm.source = n.source;

CREATE OR REPLACE VIEW market.v_etf_basket AS
SELECT
    b.source,
    COALESCE(etf_sm.source_symbol, etf_i.symbol) AS etf_source_symbol,
    etf_i.instrument_id AS etf_instrument_id,
    etf_i.exchange AS etf_exchange,
    etf_i.symbol AS etf_symbol,
    etf_i.name AS etf_name,
    b.component_symbol AS component_source_symbol,
    component_i.instrument_id AS component_instrument_id,
    component_i.asset AS component_asset,
    component_i.exchange AS component_exchange,
    component_i.symbol AS component_symbol,
    component_i.name AS component_name,
    b.trading_day,
    b.pub_date,
    b.component_type,
    b.quantity,
    b.unit,
    b.cash_substitute_flag,
    b.cash_substitute_rate,
    b.cash_substitute_amount,
    b.subscription_substitute_amount,
    b.redemption_substitute_amount,
    b.updated_at
FROM market.etf_basket b
JOIN meta.instruments etf_i
  ON etf_i.instrument_id = b.etf_instrument_id
LEFT JOIN meta.instruments component_i
  ON component_i.instrument_id = b.component_instrument_id
LEFT JOIN meta.symbol_map etf_sm
  ON etf_sm.instrument_id = b.etf_instrument_id
 AND etf_sm.source = b.source;

CREATE OR REPLACE VIEW ops.v_dataset_coverage AS
SELECT
    provider,
    dataset_name,
    min(start_date) FILTER (WHERE status = 'loaded') AS loaded_start_date,
    max(end_date) FILTER (WHERE status = 'loaded') AS loaded_end_date,
    COALESCE(sum(row_count) FILTER (WHERE status = 'loaded'), 0) AS loaded_rows,
    count(*) FILTER (WHERE status = 'written') AS written_files,
    count(*) FILTER (WHERE status = 'loaded') AS loaded_files,
    count(*) FILTER (WHERE status = 'failed') AS failed_files,
    max(loaded_at) AS last_loaded_at,
    max(created_at) AS last_staged_at
FROM staging.parquet_file
GROUP BY provider, dataset_name;
