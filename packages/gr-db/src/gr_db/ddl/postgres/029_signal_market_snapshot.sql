-- 021_signal_market_snapshot.sql
-- Per-signal market snapshot table — point-in-time OHLCV + indicators for a
-- signal's underlying symbol at publish time.
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- services/signal.py joins against this table unprefixed.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.signal_market_snapshot (
    signal_id        UUID            NOT NULL,
    symbol           VARCHAR(32)     NOT NULL,
    snapshot_time    TIMESTAMPTZ     NOT NULL,
    open             NUMERIC,
    high             NUMERIC,
    low              NUMERIC,
    close            NUMERIC,
    volume           BIGINT,
    turnover         NUMERIC,
    open_interest    BIGINT,
    basis            NUMERIC,
    indicators       JSONB,
    implied_vol      NUMERIC,
    greeks_snapshot  JSONB,
    PRIMARY KEY (signal_id, snapshot_time)
);

CREATE INDEX IF NOT EXISTS idx_market_snapshot_symbol
    ON app.signal_market_snapshot(symbol, snapshot_time DESC);

COMMENT ON TABLE app.signal_market_snapshot IS
    'Per-signal point-in-time market snapshot — OHLCV, technical indicators,
     and option greeks captured at the moment the signal was published.';
