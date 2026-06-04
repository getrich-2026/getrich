-- Optional TimescaleDB compression and minute-to-day aggregate helpers.
-- Some self-hosted TimescaleDB builds run under the Apache license and do not
-- expose compression or continuous aggregate features. Those features are
-- useful optimizations, not prerequisites for ingestion, so this migration
-- degrades to regular materialized views instead of blocking schema init.

DO $$
BEGIN
    ALTER TABLE market.index_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.index_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.index_bar_1m: %%', SQLERRM;
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
    RAISE NOTICE 'Skipping compression for market.future_bar_1m: %%', SQLERRM;
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
    RAISE NOTICE 'Skipping compression for market.option_bar_1m: %%', SQLERRM;
END $$;

DO $$
BEGIN
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.index_bar_1d_ca
    WITH (timescaledb.continuous) AS
    SELECT instrument_id,
           time_bucket('1 day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           first(open, dt) AS open,
           max(high) AS high,
           min(low) AS low,
           last(close, dt) AS close,
           sum(volume) AS volume,
           sum(amount) AS amount
    FROM market.index_bar_1m
    GROUP BY instrument_id, time_bucket('1 day', dt)
    WITH NO DATA;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Creating regular materialized view market.index_bar_1d_ca: %%', SQLERRM;
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.index_bar_1d_ca AS
    SELECT instrument_id,
           date_trunc('day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           (array_agg(open ORDER BY dt))[1] AS open,
           max(high) AS high,
           min(low) AS low,
           (array_agg(close ORDER BY dt DESC))[1] AS close,
           sum(volume) AS volume,
           sum(amount) AS amount
    FROM market.index_bar_1m
    GROUP BY instrument_id, date_trunc('day', dt)
    WITH NO DATA;
END $$;

DO $$
BEGIN
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.future_bar_1d_ca
    WITH (timescaledb.continuous) AS
    SELECT instrument_id,
           time_bucket('1 day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           first(open, dt) AS open,
           max(high) AS high,
           min(low) AS low,
           last(close, dt) AS close,
           sum(volume) AS volume,
           sum(amount) AS amount,
           last(open_interest, dt) AS open_interest
    FROM market.future_bar_1m
    GROUP BY instrument_id, time_bucket('1 day', dt)
    WITH NO DATA;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Creating regular materialized view market.future_bar_1d_ca: %%', SQLERRM;
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.future_bar_1d_ca AS
    SELECT instrument_id,
           date_trunc('day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           (array_agg(open ORDER BY dt))[1] AS open,
           max(high) AS high,
           min(low) AS low,
           (array_agg(close ORDER BY dt DESC))[1] AS close,
           sum(volume) AS volume,
           sum(amount) AS amount,
           (array_agg(open_interest ORDER BY dt DESC))[1] AS open_interest
    FROM market.future_bar_1m
    GROUP BY instrument_id, date_trunc('day', dt)
    WITH NO DATA;
END $$;

DO $$
BEGIN
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.option_bar_1d_ca
    WITH (timescaledb.continuous) AS
    SELECT instrument_id,
           time_bucket('1 day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           first(open, dt) AS open,
           max(high) AS high,
           min(low) AS low,
           last(close, dt) AS close,
           sum(volume) AS volume,
           sum(amount) AS amount,
           last(open_interest, dt) AS open_interest
    FROM market.option_bar_1m
    GROUP BY instrument_id, time_bucket('1 day', dt)
    WITH NO DATA;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Creating regular materialized view market.option_bar_1d_ca: %%', SQLERRM;
    CREATE MATERIALIZED VIEW IF NOT EXISTS market.option_bar_1d_ca AS
    SELECT instrument_id,
           date_trunc('day', dt) AS bucket_day,
           min(trading_day) AS trading_day,
           (array_agg(open ORDER BY dt))[1] AS open,
           max(high) AS high,
           min(low) AS low,
           (array_agg(close ORDER BY dt DESC))[1] AS close,
           sum(volume) AS volume,
           sum(amount) AS amount,
           (array_agg(open_interest ORDER BY dt DESC))[1] AS open_interest
    FROM market.option_bar_1m
    GROUP BY instrument_id, date_trunc('day', dt)
    WITH NO DATA;
END $$;
