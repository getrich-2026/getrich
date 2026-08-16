-- Optional TimescaleDB compression and minute-to-day aggregate helpers.
-- Market-day rollups intentionally group by trading_day instead of natural
-- time_bucket(dt), because futures and options night sessions cross calendar
-- days. Continuous aggregates require a time_bucket on the hypertable time
-- column, so these helpers use regular materialized views for correctness.

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

CREATE MATERIALIZED VIEW IF NOT EXISTS market.index_bar_1d_ca AS
SELECT instrument_id,
       trading_day::timestamptz AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount
FROM market.index_bar_1m
GROUP BY instrument_id, trading_day
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS market.stock_bar_1d_ca AS
SELECT instrument_id,
       trading_day::timestamptz AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount
FROM market.stock_bar_1m
GROUP BY instrument_id, trading_day
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS market.etf_bar_1d_ca AS
SELECT instrument_id,
       trading_day::timestamptz AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount
FROM market.etf_bar_1m
GROUP BY instrument_id, trading_day
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS market.future_bar_1d_ca AS
SELECT instrument_id,
       trading_day::timestamptz AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount,
       last(open_interest, dt) AS open_interest
FROM market.future_bar_1m
GROUP BY instrument_id, trading_day
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS market.option_bar_1d_ca AS
SELECT instrument_id,
       trading_day::timestamptz AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount,
       last(open_interest, dt) AS open_interest
FROM market.option_bar_1m
GROUP BY instrument_id, trading_day
WITH NO DATA;
