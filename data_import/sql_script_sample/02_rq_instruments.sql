-- ============================================================
-- RiceQuant 标的信息 (rq)
-- ============================================================

-- CS — 股票
CREATE TABLE IF NOT EXISTS rq.instruments_cs (
    order_book_id    TEXT             PRIMARY KEY,
    symbol           TEXT             NOT NULL,
    abbrev_symbol    TEXT,
    round_lot        DOUBLE PRECISION,
    sector_code      VARCHAR(20),
    sector_code_name TEXT,
    industry_code    VARCHAR(30),
    industry_name    TEXT,
    listed_date      DATE,
    de_listed_date   DATE,
    issue_price      DOUBLE PRECISION,
    type             VARCHAR(20),
    exchange         VARCHAR(20),
    board_type       VARCHAR(20),
    status           VARCHAR(20),
    special_type     VARCHAR(20),
    trading_hours    TEXT,
    market_tplus     INTEGER,
    purchasedate     DATE,
    trading_code     TEXT,
    office_address   TEXT,
    province         VARCHAR(50),
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_cs_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_cs_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_cs_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_cs_issue_price_non_negative CHECK (issue_price IS NULL OR issue_price >= 0),
    CONSTRAINT chk_cs_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_cs_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_cs_exchange_status
    ON rq.instruments_cs (exchange, status, listed_date, de_listed_date);

-- ETF — 交易所交易基金
CREATE TABLE IF NOT EXISTS rq.instruments_etf (
    order_book_id            TEXT             PRIMARY KEY,
    symbol                   TEXT             NOT NULL,
    abbrev_symbol            TEXT,
    round_lot                DOUBLE PRECISION,
    listed_date              DATE,
    de_listed_date           DATE,
    establishment_date       DATE,
    type                     VARCHAR(20),
    exchange                 VARCHAR(20),
    board_type               INTEGER,
    status                   VARCHAR(20),
    trading_hours            TEXT,
    market_tplus             INTEGER,
    least_redeem             DOUBLE PRECISION,
    underlying_order_book_id TEXT,
    underlying_name          TEXT,
    trading_code             TEXT,
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_etf_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_etf_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_etf_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_etf_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_etf_least_redeem_positive CHECK (least_redeem IS NULL OR least_redeem > 0),
    CONSTRAINT chk_etf_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_etf_exchange_status
    ON rq.instruments_etf (exchange, status);

-- LOF — 上市型开放式基金
CREATE TABLE IF NOT EXISTS rq.instruments_lof (
    order_book_id            TEXT             PRIMARY KEY,
    symbol                   TEXT             NOT NULL,
    abbrev_symbol            TEXT,
    round_lot                DOUBLE PRECISION,
    listed_date              DATE,
    de_listed_date           DATE,
    establishment_date       DATE,
    type                     VARCHAR(20),
    exchange                 VARCHAR(20),
    board_type               INTEGER,
    status                   VARCHAR(20),
    trading_hours            TEXT,
    market_tplus             INTEGER,
    least_redeem             DOUBLE PRECISION,
    underlying_order_book_id TEXT,
    underlying_name          TEXT,
    trading_code             TEXT,
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_lof_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_lof_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_lof_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_lof_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_lof_least_redeem_positive CHECK (least_redeem IS NULL OR least_redeem > 0),
    CONSTRAINT chk_lof_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_lof_exchange_status
    ON rq.instruments_lof (exchange, status);

-- INDX — 指数
CREATE TABLE IF NOT EXISTS rq.instruments_indx (
    order_book_id     TEXT             PRIMARY KEY,
    symbol            TEXT             NOT NULL,
    abbrev_symbol     TEXT,
    listed_date       DATE,
    de_listed_date    DATE,
    type              VARCHAR(20),
    exchange          VARCHAR(20),
    status            VARCHAR(20),
    base_date         DATE,
    base_point        DOUBLE PRECISION,
    index_value       DOUBLE PRECISION,
    underlying_symbol TEXT,
    trading_hours     TEXT,
    market_tplus      DOUBLE PRECISION,
    round_lot         DOUBLE PRECISION,
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_indx_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_indx_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_indx_base_point_non_negative CHECK (base_point IS NULL OR base_point >= 0),
    CONSTRAINT chk_indx_index_value_non_negative CHECK (index_value IS NULL OR index_value >= 0),
    CONSTRAINT chk_indx_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_indx_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_indx_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_indx_exchange_status
    ON rq.instruments_indx (exchange, status);

-- Future — 期货
CREATE TABLE IF NOT EXISTS rq.instruments_future (
    order_book_id            TEXT             PRIMARY KEY,
    symbol                   TEXT             NOT NULL,
    type                     VARCHAR(20),
    exchange                 VARCHAR(20),
    product                  VARCHAR(30),
    listed_date              DATE,
    de_listed_date           DATE,
    maturity_date            DATE,
    start_delivery_date      DATE,
    end_delivery_date        DATE,
    contract_multiplier      DOUBLE PRECISION,
    margin_rate              DOUBLE PRECISION,
    round_lot                DOUBLE PRECISION,
    market_tplus             DOUBLE PRECISION,
    underlying_order_book_id TEXT,
    underlying_symbol        TEXT,
    industry_name            TEXT,
    trading_hours            TEXT,
    trading_code             TEXT,
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_future_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_future_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_future_contract_multiplier_positive
        CHECK (contract_multiplier IS NULL OR contract_multiplier > 0),
    CONSTRAINT chk_future_margin_rate_non_negative CHECK (margin_rate IS NULL OR margin_rate >= 0),
    CONSTRAINT chk_future_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_future_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_future_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date),
    CONSTRAINT chk_future_delivery_window
        CHECK (start_delivery_date IS NULL OR end_delivery_date IS NULL OR start_delivery_date <= end_delivery_date)
);

CREATE INDEX IF NOT EXISTS idx_future_product_maturity
    ON rq.instruments_future (product, maturity_date);
CREATE INDEX IF NOT EXISTS idx_future_exchange_delisted
    ON rq.instruments_future (exchange, de_listed_date);

-- Spot — 现货
CREATE TABLE IF NOT EXISTS rq.instruments_spot (
    order_book_id       TEXT             PRIMARY KEY,
    symbol              TEXT             NOT NULL,
    type                VARCHAR(20),
    exchange            VARCHAR(20),
    listed_date         DATE,
    de_listed_date      DATE,
    contract_multiplier DOUBLE PRECISION,
    margin_rate         DOUBLE PRECISION,
    round_lot           DOUBLE PRECISION,
    market_tplus        INTEGER,
    trading_hours       TEXT,
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_spot_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_spot_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_spot_contract_multiplier_positive
        CHECK (contract_multiplier IS NULL OR contract_multiplier > 0),
    CONSTRAINT chk_spot_margin_rate_non_negative CHECK (margin_rate IS NULL OR margin_rate >= 0),
    CONSTRAINT chk_spot_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_spot_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_spot_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_spot_exchange_delisted
    ON rq.instruments_spot (exchange, de_listed_date);

-- Option — 期权
CREATE TABLE IF NOT EXISTS rq.instruments_option (
    order_book_id            TEXT             PRIMARY KEY,
    symbol                   TEXT             NOT NULL,
    type                     VARCHAR(20),
    exchange                 VARCHAR(20),
    listed_date              DATE,
    de_listed_date           DATE,
    maturity_date            DATE,
    underlying_order_book_id TEXT,
    underlying_symbol        TEXT,
    strike_price             DOUBLE PRECISION,
    option_type              VARCHAR(10),
    exercise_type            VARCHAR(10),
    contract_multiplier      DOUBLE PRECISION,
    round_lot                DOUBLE PRECISION,
    market_tplus             DOUBLE PRECISION,
    product_name             TEXT,
    trading_hours            TEXT,
    trading_code             TEXT,
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_option_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_option_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_option_strike_price_positive CHECK (strike_price IS NULL OR strike_price > 0),
    CONSTRAINT chk_option_contract_multiplier_positive
        CHECK (contract_multiplier IS NULL OR contract_multiplier > 0),
    CONSTRAINT chk_option_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_option_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_option_type_valid
        CHECK (option_type IS NULL OR option_type IN ('C', 'P', 'CALL', 'PUT', 'call', 'put')),
    CONSTRAINT chk_option_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_option_underlying_maturity
    ON rq.instruments_option (underlying_order_book_id, maturity_date);
CREATE INDEX IF NOT EXISTS idx_option_exchange_type
    ON rq.instruments_option (exchange, option_type);

-- Convertible — 可转债
CREATE TABLE IF NOT EXISTS rq.instruments_convertible (
    order_book_id  TEXT             PRIMARY KEY,
    symbol         TEXT             NOT NULL,
    type           VARCHAR(20),
    exchange       VARCHAR(20),
    status         VARCHAR(20),
    listed_date    DATE,
    de_listed_date DATE,
    maturity_date  DATE,
    stock_code     TEXT,
    round_lot      DOUBLE PRECISION,
    market_tplus   INTEGER,
    trading_hours  TEXT,
    trading_code   TEXT,
    updated_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_convertible_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_convertible_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_convertible_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_convertible_market_tplus_non_negative CHECK (market_tplus IS NULL OR market_tplus >= 0),
    CONSTRAINT chk_convertible_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_convertible_stock
    ON rq.instruments_convertible (stock_code);
CREATE INDEX IF NOT EXISTS idx_convertible_exchange_status
    ON rq.instruments_convertible (exchange, status);

-- Repo — 回购
CREATE TABLE IF NOT EXISTS rq.instruments_repo (
    order_book_id  TEXT         PRIMARY KEY,
    symbol         TEXT         NOT NULL,
    abbrev_symbol  TEXT,
    type           VARCHAR(20),
    exchange       VARCHAR(20),
    status         VARCHAR(20),
    listed_date    DATE,
    de_listed_date DATE,
    round_lot      DOUBLE PRECISION,
    trading_hours  TEXT,
    trading_code   TEXT,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_repo_order_book_id_not_blank CHECK (btrim(order_book_id) <> ''),
    CONSTRAINT chk_repo_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_repo_round_lot_positive CHECK (round_lot IS NULL OR round_lot > 0),
    CONSTRAINT chk_repo_listed_before_delisted
        CHECK (listed_date IS NULL OR de_listed_date IS NULL OR listed_date <= de_listed_date)
);

CREATE INDEX IF NOT EXISTS idx_repo_exchange_status
    ON rq.instruments_repo (exchange, status);
