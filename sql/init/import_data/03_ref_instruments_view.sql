-- ============================================================
-- 统一标的视图 ref.instruments
-- 整合所有 rq 分表，供上层统一查询。
-- 缺失值保留 NULL，避免把未知值误表示为 0 或空字符串。
-- ============================================================

CREATE OR REPLACE VIEW ref.instruments AS
-- CS (股票)
SELECT
    order_book_id::TEXT                           AS symbol,
    trading_code::TEXT                            AS symbol_raw,
    exchange::TEXT                                AS exchange,
    symbol::TEXT                                  AS name,
    type::TEXT                                    AS type,
    NULL::TEXT                                    AS und_code,
    NULL::TEXT                                    AS und_name,
    1.0::DOUBLE PRECISION                         AS multiplier,
    NULL::DOUBLE PRECISION                        AS margin_ratio,
    NULL::DOUBLE PRECISION                        AS strike_price,
    NULL::TEXT                                    AS option_type,
    NULL::TEXT                                    AS exercise_type,
    'CNY'::TEXT                                   AS currency,
    listed_date,
    de_listed_date                                AS delisted_date,
    'RICEQUANT'::TEXT                             AS provider,
    updated_at
FROM rq.instruments_cs
UNION ALL
-- ETF
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    underlying_order_book_id::TEXT,
    underlying_name::TEXT,
    1.0::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_etf
UNION ALL
-- LOF
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    underlying_order_book_id::TEXT,
    underlying_name::TEXT,
    1.0::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_lof
UNION ALL
-- INDX (指数)
SELECT
    order_book_id::TEXT,
    order_book_id::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    NULL::TEXT,
    underlying_symbol::TEXT,
    1.0::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_indx
UNION ALL
-- Future (期货)
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    underlying_order_book_id::TEXT,
    underlying_symbol::TEXT,
    contract_multiplier,
    margin_rate,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_future
UNION ALL
-- Spot (现货)
SELECT
    order_book_id::TEXT,
    order_book_id::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    NULL::TEXT,
    NULL::TEXT,
    contract_multiplier,
    margin_rate,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_spot
UNION ALL
-- Option (期权)
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    underlying_order_book_id::TEXT,
    underlying_symbol::TEXT,
    contract_multiplier,
    NULL::DOUBLE PRECISION,
    strike_price,
    option_type::TEXT,
    exercise_type::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_option
UNION ALL
-- Convertible (可转债)
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    stock_code::TEXT,
    NULL::TEXT,
    1.0::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_convertible
UNION ALL
-- Repo (回购)
SELECT
    order_book_id::TEXT,
    trading_code::TEXT,
    exchange::TEXT,
    symbol::TEXT,
    type::TEXT,
    NULL::TEXT,
    NULL::TEXT,
    1.0::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::DOUBLE PRECISION,
    NULL::TEXT,
    NULL::TEXT,
    'CNY'::TEXT,
    listed_date,
    de_listed_date,
    'RICEQUANT'::TEXT,
    updated_at
FROM rq.instruments_repo;
