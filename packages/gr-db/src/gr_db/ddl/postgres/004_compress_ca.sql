-- 分钟线按交易日聚合的辅助物化视图；压缩配置已随建表放入 003。
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
