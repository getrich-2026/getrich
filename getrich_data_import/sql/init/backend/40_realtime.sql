-- Realtime short-retention buffer.

CREATE TABLE IF NOT EXISTS realtime.tick_buffer (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    dt             TIMESTAMPTZ NOT NULL,
    trading_day    DATE,
    last           NUMERIC(20,6),
    volume         BIGINT,
    amount         NUMERIC(24,4),
    bid1           NUMERIC(20,6),
    ask1           NUMERIC(20,6),
    bid_vol1       BIGINT,
    ask_vol1       BIGINT,
    open_interest  BIGINT,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, dt)
);

SELECT create_hypertable('realtime.tick_buffer', 'dt', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
DO $$
BEGIN
    PERFORM add_retention_policy('realtime.tick_buffer', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping retention policy for realtime.tick_buffer: %%', SQLERRM;
END $$;
