-- 0. 建库（保持不变）
CREATE DATABASE IF NOT EXISTS ref;
CREATE DATABASE IF NOT EXISTS market_data;
CREATE DATABASE IF NOT EXISTS strategy;
CREATE DATABASE IF NOT EXISTS trade;
CREATE DATABASE IF NOT EXISTS app;
CREATE DATABASE IF NOT EXISTS rq;

-- 1.1 标的信息表
CREATE TABLE IF NOT EXISTS ref.instruments (
    symbol LowCardinality(String) COMMENT '统一代码, e.g. 000300.SH',
    symbol_raw String COMMENT '交易所原始代码 (可选)',
    exchange LowCardinality(String) COMMENT '交易所, SH,SZ,SHF,CFFEX 等',
    name String COMMENT '标的名称',
    type LowCardinality(String) COMMENT '标的类型, A, S, FU, OP 等',
    und_code String DEFAULT '' COMMENT '衍生品标的资产代码，如IF的标的资产代码是000300.SH',
    und_name String DEFAULT '' COMMENT '衍生品标的资产名称，如IF的标的资产名称是沪深300指数',
    multiplier Float64 DEFAULT 1.0 COMMENT '合约乘数, 股票为1, 期货如300',
    margin_ratio Float32 DEFAULT 0.0 COMMENT '保证金比例',
    strike_price Float64 DEFAULT 0.0 COMMENT '期权行权价',
    option_type LowCardinality(String) DEFAULT '' COMMENT '期权类型, Call/Put',
    exercise_type LowCardinality(String) DEFAULT '' COMMENT '行权方式, American/European',
    currency LowCardinality(String) DEFAULT 'CNY',
    listed_date Date,
    delisted_date Date DEFAULT '2099-12-31',
    source LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (symbol);

-- 1.2 交易日历 (保持原设计，简单好用)
CREATE TABLE IF NOT EXISTS ref.calendar (
    exchange LowCardinality(String),
    trading_day Date,
    is_trading UInt8,
    prev_trading_day Date COMMENT '上一个交易日',
    next_trading_day Date COMMENT '下一个交易日',
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (exchange, trading_day);

-- 1.3 RiceQuant 数据源索引视图
-- 从 rq 数据库的多个 instruments_xx 表中整合数据到 ref.instruments 结构
CREATE VIEW IF NOT EXISTS ref.instruments AS
-- CS (股票)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    '' AS und_code,
    '' AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_cs
UNION ALL
-- ETF (交易所交易基金)
SELECT 
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(underlying_order_book_id, '') AS und_code,
    COALESCE(underlying_name, '') AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_etf
UNION ALL
-- LOF (上市型开放式基金)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(underlying_order_book_id, '') AS und_code,
    COALESCE(underlying_name, '') AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_lof
UNION ALL
-- INDX (指数)
SELECT
    order_book_id AS symbol,
    order_book_id AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(underlying_symbol, '') AS und_code,
    COALESCE(underlying_symbol, '') AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_indx
UNION ALL
-- Future (期货)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(underlying_order_book_id, '') AS und_code,
    COALESCE(underlying_symbol, '') AS und_name,
    COALESCE(contract_multiplier, 1.0) AS multiplier,
    COALESCE(margin_rate, 0.0) AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_future
UNION ALL
-- Spot (现货)
SELECT
    order_book_id AS symbol,
    order_book_id AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    '' AS und_code,
    '' AS und_name,
    COALESCE(contract_multiplier, 1.0) AS multiplier,
    COALESCE(margin_rate, 0.0) AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_spot
UNION ALL
-- Option (期权)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(underlying_order_book_id, '') AS und_code,
    COALESCE(underlying_symbol, '') AS und_name,
    COALESCE(contract_multiplier, 1.0) AS multiplier,
    0.0 AS margin_ratio,
    COALESCE(strike_price, 0.0) AS strike_price,
    COALESCE(option_type, '') AS option_type,
    COALESCE(exercise_type, '') AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_option
UNION ALL
-- Convertible (可转债)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    COALESCE(stock_code, '') AS und_code,
    '' AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_convertible
UNION ALL
-- Repo (回购)
SELECT
    order_book_id AS symbol,
    trading_code AS symbol_raw,
    exchange,
    symbol AS name,
    type,
    '' AS und_code,
    '' AS und_name,
    1.0 AS multiplier,
    0.0 AS margin_ratio,
    0.0 AS strike_price,
    '' AS option_type,
    '' AS exercise_type,
    'CNY' AS currency,
    listed_date,
    COALESCE(de_listed_date, toDate('2099-12-31')) AS delisted_date,
    'RICEQUANT' AS source,
    updated_at
FROM rq.instruments_repo;


CREATE TABLE IF NOT EXISTS market_data.bars_1m (
    symbol LowCardinality(String),
    dt Date CODEC(Delta, ZSTD(1)),      -- 用于分区
    ts String CODEC(ZSTD(1)),           -- K线结束时间 (HH:mm:ss)
    pre_close Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 前收盘价
    open Float64 DEFAULT 0 CODEC(ZSTD(1)),      -- 开盘价
    high Float64 DEFAULT 0 CODEC(ZSTD(1)),      -- 最高价
    low Float64 DEFAULT 0 CODEC(ZSTD(1)),       -- 最低价
    close Float64 DEFAULT 0 CODEC(ZSTD(1)),     -- 收盘价
    volume Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 成交量
    amount Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 成交额
    open_interest Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 持仓量(期货)
    settle Float64 DEFAULT 0 CODEC(ZSTD(1)),    -- 结算价
    pre_settle Float64 DEFAULT 0 CODEC(ZSTD(1)), -- 前结算价
    local_time DateTime64(3) CODEC(Delta, ZSTD),
    source LowCardinality(String) DEFAULT 'UNKNOWN',  -- 数据来源
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, local_time)
SETTINGS index_granularity = 8192, 
         min_bytes_for_wide_part = 0, 
         min_rows_for_wide_part = 0, 
         enable_mixed_granularity_parts = 1;

-- 2.1 日线 (宽表，包含常用衍生字段)
CREATE TABLE IF NOT EXISTS market_data.bars_1d (
    symbol LowCardinality(String),
    dt Date CODEC(Delta, ZSTD(1)),

    pre_close Float64 DEFAULT 0 CODEC(ZSTD(1)),
    open Float64 DEFAULT 0 CODEC(ZSTD(1)),
    high Float64 DEFAULT 0 CODEC(ZSTD(1)),
    low Float64 DEFAULT 0 CODEC(ZSTD(1)),
    close Float64 DEFAULT 0 CODEC(ZSTD(1)),
    volume Float64 DEFAULT 0 CODEC(ZSTD(1)),
    amount Float64 DEFAULT 0 CODEC(ZSTD(1)),
    
    pct_chg Float64 DEFAULT 0 CODEC(ZSTD(1)),
    pct_chg_log Float64 DEFAULT 0 CODEC(ZSTD(1)),
    adj_factor Float64 DEFAULT 1 CODEC(ZSTD(1)),

    limit_up Float64 DEFAULT 0 CODEC(ZSTD(1)),
    limit_down Float64 DEFAULT 0 CODEC(ZSTD(1)),
    turnover_rate Float32 DEFAULT 0 CODEC(ZSTD(1)),

    open_interest Float64 DEFAULT 0 CODEC(ZSTD(1)),
    settle Float64 DEFAULT 0 CODEC(ZSTD(1)),
    pre_settle Float64 DEFAULT 0 CODEC(ZSTD(1)),

    trading_status Enum8('UNKNOWN'=0, 'NORMAL'=1, 'HALTED'=2) DEFAULT 'UNKNOWN',
    source LowCardinality(String) DEFAULT 'UNKNOWN',

    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
SETTINGS index_granularity = 8192, 
         min_bytes_for_wide_part = 0, 
         min_rows_for_wide_part = 0, 
         enable_mixed_granularity_parts = 1;

--- TODO: 检查以下表结构并建表入库
-- 2.2 Tick 快照 (带 TTL)
CREATE TABLE IF NOT EXISTS market_data.ticks (
    symbol LowCardinality(String),
    ts DateTime64(3, 'Asia/Shanghai') CODEC(DoubleDelta, ZSTD(1)),
    price Float64 CODEC(ZSTD(1)),
    volume Float64 CODEC(ZSTD(1)),
    bid1_price Float64,
	bid1_volume Float64,
    ask1_price Float64,
	ask1_volume Float64,
    bs_flag Enum8('Unknown'=0, 'Buy'=1, 'Sell'=2) COMMENT '主动买卖方向',
    source LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',
    received_at DateTime64(3) DEFAULT now64(3) COMMENT '入库物理时间，用于延时监控'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(toDate(ts))       -- 分区按月，避免按 symbol 导致大量小分区
ORDER BY (symbol, ts)
TTL toDateTime(ts) + INTERVAL 30 DAY DELETE       -- 30天自动滚动删除
SETTINGS ttl_only_drop_parts = 1;

-- 4.1 订单表 (支持状态更新)
CREATE TABLE IF NOT EXISTS trade.orders (
    order_id String,                  -- 全局唯一ID
    account_id LowCardinality(String),
    strategy_id LowCardinality(String),
    signal_id String DEFAULT '',      -- 关联 strategy.signals_raw 的 ID
    symbol LowCardinality(String),
    
    -- 状态维
    status Enum8('NEW'=0, 'SUBMITTED'=1, 'PARTIAL'=2, 'FILLED'=3, 'CANCELED'=4, 'REJECTED'=5),
    side Enum8('BUY'=1, 'SELL'=2),
    type Enum8('LIMIT'=1, 'MARKET'=2),
    
    -- 数量维 (Float64)
    price Float64,                    -- 委托价
    qty Float64,                      -- 委托量
    filled_qty Float64 DEFAULT 0,     -- 已成交量
    avg_price Float64 DEFAULT 0,      -- 成交均价
    
    -- 时间与版本控制
    created_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3),
    updated_at DateTime64(3, 'Asia/Shanghai'),
    ver UInt64 DEFAULT 0 COMMENT '版本号, 每次状态变更+1'
) ENGINE = ReplacingMergeTree(ver)    -- 按照 ver 字段保留最新状态
PARTITION BY toYYYYMM(toDate(created_at))
ORDER BY (account_id, symbol, order_id);

-- 4.2 成交明细表 (流水表，不可变，MergeTree 即可)
CREATE TABLE IF NOT EXISTS trade.fills (
    fill_id String,
    order_id String,
    account_id LowCardinality(String),
    symbol LowCardinality(String),
    side Enum8('BUY'=1, 'SELL'=2),
    
    price Float64,
    qty Float64,
    commission Float64 DEFAULT 0,
    source LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '成交来源',
    
    fill_time DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(toDate(fill_time))
ORDER BY (account_id, symbol, fill_time);

-- 4.3 每日持仓快照 (用于归因和对账)
CREATE TABLE IF NOT EXISTS trade.positions_daily (
    date Date,
    account_id LowCardinality(String),
    symbol LowCardinality(String),
    
    long_qty Float64 DEFAULT 0,
    short_qty Float64 DEFAULT 0,
    avg_open_price Float64 DEFAULT 0,
    
    close_price Float64 COMMENT '当日收盘价',
    market_value Float64 COMMENT '市值',
    pnl_unrealized Float64 COMMENT '浮动盈亏',
    
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(date)
ORDER BY (account_id, symbol, date);

-- 3.1 策略原始信号
CREATE TABLE IF NOT EXISTS strategy.signals_raw (
    signal_uuid UUID DEFAULT generateUUIDv4(), -- 新增：唯一ID
    strategy_id LowCardinality(String),
    symbol LowCardinality(String),
    ts DateTime,
    
    action Enum8('NOOP'=0, 'OPEN_LONG'=1, 'OPEN_SHORT'=2, 'CLOSE_LONG'=3, 'CLOSE_SHORT'=4),
    price Float64,
    strength Float32, -- 信号强度仍可用 Float32
    source LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '信号来源',
    
    json_meta String  -- 扩展字段
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (strategy_id, symbol, ts);

-- 3.2 APP展示表 (保持原设计)
CREATE TABLE IF NOT EXISTS app.ui_predictions (
    symbol LowCardinality(String),
    ts DateTime,
    direction Enum8('NEUTRAL'=0, 'BULLISH'=1, 'BEARISH'=2),
    confidence Float32,
    primary_message String,
    strategy_id LowCardinality(String),
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(ts)
ORDER BY (symbol, ts, strategy_id);

