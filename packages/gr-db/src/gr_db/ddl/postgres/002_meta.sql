-- Metadata layer.

CREATE TABLE IF NOT EXISTS meta.instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    symbol        VARCHAR(64) NOT NULL,
    asset         VARCHAR(16) NOT NULL,
    exchange      VARCHAR(16) NOT NULL,
    name          VARCHAR(128),
    list_date     DATE,
    delist_date   DATE,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset, exchange, symbol),
    CONSTRAINT chk_instruments_asset
        CHECK (asset IN ('index', 'future', 'option', 'stock', 'etf', 'fund')),
    CONSTRAINT chk_instruments_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_instruments_exchange_not_blank
        CHECK (btrim(exchange) <> '')
);

CREATE INDEX IF NOT EXISTS idx_instruments_asset_exchange_status
    ON meta.instruments (asset, exchange, status);

CREATE TABLE IF NOT EXISTS meta.symbol_map (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    source        VARCHAR(32) NOT NULL,
    source_symbol VARCHAR(128) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_symbol),
    UNIQUE (instrument_id, source),
    CONSTRAINT chk_symbol_map_source_not_blank
        CHECK (btrim(source) <> ''),
    CONSTRAINT chk_symbol_map_symbol_not_blank
        CHECK (btrim(source_symbol) <> '')
);

CREATE TABLE IF NOT EXISTS meta.trading_calendar (
    exchange          VARCHAR(16) NOT NULL,
    trading_day       DATE NOT NULL,
    is_open           BOOLEAN NOT NULL DEFAULT true,
    has_night         BOOLEAN NOT NULL DEFAULT false,
    prev_trading_day  DATE,
    next_trading_day  DATE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, trading_day),
    CONSTRAINT chk_calendar_exchange_not_blank
        CHECK (btrim(exchange) <> ''),
    CONSTRAINT chk_calendar_prev_before
        CHECK (prev_trading_day IS NULL OR prev_trading_day < trading_day),
    CONSTRAINT chk_calendar_next_after
        CHECK (next_trading_day IS NULL OR next_trading_day > trading_day)
);

CREATE INDEX IF NOT EXISTS idx_trading_calendar_open
    ON meta.trading_calendar (exchange, is_open, trading_day);

CREATE TABLE IF NOT EXISTS meta.future_contracts (
    instrument_id   BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    underlying      VARCHAR(64),
    multiplier      NUMERIC(18,4),
    price_tick      NUMERIC(18,6),
    list_date       DATE,
    last_trade_date DATE,
    delivery_date   DATE
);

CREATE TABLE IF NOT EXISTS meta.option_contracts (
    instrument_id   BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    underlying_id   BIGINT REFERENCES meta.instruments(instrument_id),
    option_type     CHAR(1) NOT NULL,
    exercise_style  VARCHAR(16),
    strike          NUMERIC(18,4) NOT NULL,
    multiplier      NUMERIC(18,4),
    list_date       DATE,
    last_trade_date DATE,
    exercise_date   DATE,
    CONSTRAINT chk_option_type CHECK (option_type IN ('C', 'P'))
);

CREATE INDEX IF NOT EXISTS idx_option_contracts_underlying
    ON meta.option_contracts (underlying_id);
