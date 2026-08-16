-- Active: 1773109768346@@192.168.1.216@8123@default
-- ============================================================
-- GetRich Quant Platform — 分布式集群初始化 Schema
-- 集群: quant_cluster (2-shard, ClickHouse Keeper)
-- 命名规范: 本地表 = xxx_local, 分布式表 = xxx
-- 宏变量: {shard}, {replica} 由 macros.xml 注入
-- ============================================================

-- 0. 建库 (ON CLUSTER 自动在所有节点创建)
CREATE DATABASE IF NOT EXISTS ref ON CLUSTER 'quant_cluster';
CREATE DATABASE IF NOT EXISTS market_data ON CLUSTER 'quant_cluster';
CREATE DATABASE IF NOT EXISTS rq ON CLUSTER 'quant_cluster';

-- ============================================================
-- 1. 参考数据 (ref) — 小表，全量复制，不需要 CODEC
-- ============================================================

-- 1.1 交易日历
CREATE TABLE IF NOT EXISTS ref.calendar_local ON CLUSTER 'quant_cluster' (
    exchange LowCardinality(String) COMMENT '交易所',
    dt Date COMMENT '日期',
    is_trading UInt8 COMMENT '是否交易日',
    prev_trading_day Nullable(Date) COMMENT '上一个交易日',
    next_trading_day Nullable(Date) COMMENT '下一个交易日',
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3) COMMENT '数据更新时间'
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/ref/calendar', '{replica}', updated_at
)
ORDER BY (exchange, dt);

CREATE TABLE IF NOT EXISTS ref.calendar ON CLUSTER 'quant_cluster'
AS ref.calendar_local
ENGINE = Distributed('quant_cluster', 'ref', 'calendar_local', rand());

-- 1.2 标的映射表 (支持多数据源映射)
CREATE TABLE IF NOT EXISTS ref.symbol_mapping_local ON CLUSTER 'quant_cluster' (
    symbol String COMMENT '标准代码, 如 RB2405',
    provider LowCardinality(String) COMMENT '数据源标识, 如 hdb, rq, wind',
    mapped_symbol String COMMENT '数据源对应的代码',
    update_time DateTime DEFAULT now() COMMENT '更新时间'
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/ref/symbol_mapping', '{replica}', update_time
)
ORDER BY (provider, symbol)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS ref.symbol_mapping ON CLUSTER 'quant_cluster'
AS ref.symbol_mapping_local
ENGINE = Distributed('quant_cluster', 'ref', 'symbol_mapping_local', rand());

-- ============================================================
-- 2. RiceQuant 标的信息 (rq) — 小表，全量复制，不需要 CODEC
-- ============================================================

-- 2.1 CS (Common Stock - 股票)
CREATE TABLE IF NOT EXISTS rq.instruments_cs_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 证券代码
    symbol String, -- 证券简称
    abbrev_symbol String, -- 证券名称缩写
    round_lot Float64, -- 一手股数
    sector_code LowCardinality(String), -- 板块缩写代码
    sector_code_name LowCardinality(String), -- 板块代码名
    industry_code LowCardinality(String), -- 国民经济行业分类代码
    industry_name LowCardinality(String), -- 国民经济行业分类名称
    listed_date Date, -- 上市日期
    issue_price Float64, -- 发行价
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    exchange LowCardinality(String), -- 交易所
    board_type LowCardinality(String), -- 板块类别
    status LowCardinality(String), -- 合约状态
    special_type LowCardinality(String), -- 特别处理状态
    trading_hours String, -- 交易时间
    market_tplus Int32, -- 交易制度
    purchasedate Date, -- 申购日期
    trading_code String, -- 交易代码
    office_address String, -- 办公地址
    province LowCardinality(String), -- 省份
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_cs', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_cs ON CLUSTER 'quant_cluster'
AS rq.instruments_cs_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_cs_local', rand());

-- 2.2 ETF (Exchange Traded Fund - 交易所交易基金)
CREATE TABLE IF NOT EXISTS rq.instruments_etf_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 证券代码
    symbol String, -- 证券简称
    abbrev_symbol String, -- 证券名称缩写
    round_lot Float64, -- 一手股数
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    exchange LowCardinality(String), -- 交易所
    status LowCardinality(String), -- 合约状态
    trading_hours String, -- 交易时间
    market_tplus Int32, -- 交易制度
    least_redeem Float64, -- 最低申赎份额
    underlying_order_book_id String, -- 追踪基准合约代码
    underlying_name String, -- 追踪基准合约名称
    establishment_date Date, -- 成立日期
    trading_code String, -- 交易代码
    board_type Int32, -- 板块类别
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_etf', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_etf ON CLUSTER 'quant_cluster'
AS rq.instruments_etf_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_etf_local', rand());

-- 2.3 LOF (Listed Open-Ended Fund - 上市型开放式基金)
CREATE TABLE IF NOT EXISTS rq.instruments_lof_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 证券代码
    symbol String, -- 证券简称
    abbrev_symbol String, -- 证券名称缩写
    round_lot Float64, -- 一手股数
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    exchange LowCardinality(String), -- 交易所
    status LowCardinality(String), -- 合约状态
    trading_hours String, -- 交易时间
    market_tplus Int32, -- 交易制度
    underlying_order_book_id String, -- 追踪基准合约代码
    underlying_name String, -- 追踪基准合约名称
    establishment_date Date, -- 成立日期
    trading_code String, -- 交易代码
    board_type Int32, -- 板块类别
    least_redeem Float64, -- 最低申赎份额
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_lof', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_lof ON CLUSTER 'quant_cluster'
AS rq.instruments_lof_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_lof_local', rand());

-- 2.4 INDX (Index - 指数)
CREATE TABLE IF NOT EXISTS rq.instruments_indx_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 证券代码
    symbol String, -- 证券简称
    abbrev_symbol String, -- 证券名称缩写
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    exchange LowCardinality(String), -- 交易所
    base_date Date, -- 基日
    base_point Float64, -- 基点
    trading_hours String, -- 交易时间
    market_tplus Float64, -- 交易制度
    round_lot Float64, -- 一手股数
    status LowCardinality(String), -- 合约状态
    `index` Float64, -- 指数值
    underlying_symbol String, -- 标的名称
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_indx', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_indx ON CLUSTER 'quant_cluster'
AS rq.instruments_indx_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_indx_local', rand());

-- 2.5 Future (Futures - 期货)
CREATE TABLE IF NOT EXISTS rq.instruments_future_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 期货代码
    symbol String, -- 期货简称
    margin_rate Float64, -- 最低保证金率
    round_lot Float64, -- 一手股数
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    industry_name LowCardinality(String), -- 行业分类名称
    trading_code String, -- 交易代码
    market_tplus Float64, -- 交易制度
    type LowCardinality(String), -- 合约类型
    contract_multiplier Float64, -- 合约乘数
    underlying_order_book_id String, -- 合约标的代码
    underlying_symbol String, -- 合约标的名称
    maturity_date Date, -- 到期日
    exchange LowCardinality(String), -- 交易所
    trading_hours String, -- 交易时间
    product LowCardinality(String), -- 合约种类
    start_delivery_date Date, -- 开始交割日
    end_delivery_date Date, -- 结束交割日
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_future', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_future ON CLUSTER 'quant_cluster'
AS rq.instruments_future_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_future_local', rand());

-- 2.6 Spot (Spot - 现货)
CREATE TABLE IF NOT EXISTS rq.instruments_spot_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 合约代码
    symbol String, -- 合约简称
    exchange LowCardinality(String), -- 交易所
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    trading_hours String, -- 交易时间
    market_tplus Int32, -- 交易制度
    contract_multiplier Float64, -- 合约乘数
    margin_rate Float64, -- 保证金率
    round_lot Float64, -- 一手股数
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_spot', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_spot ON CLUSTER 'quant_cluster'
AS rq.instruments_spot_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_spot_local', rand());

-- 2.7 Option (Option - 期权)
CREATE TABLE IF NOT EXISTS rq.instruments_option_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 合约代码
    symbol String, -- 合约简称
    round_lot Float64, -- 最小下单手数
    listed_date Date, -- 上市日期
    type LowCardinality(String), -- 合约类型
    contract_multiplier Float64, -- 合约乘数
    underlying_order_book_id String, -- 合约标的代码
    underlying_symbol String, -- 合约所属品种
    maturity_date Date, -- 到期日
    exchange LowCardinality(String), -- 交易所
    strike_price Float64, -- 行权价
    option_type LowCardinality(String), -- 期权类型
    exercise_type LowCardinality(String), -- 行权方式
    market_tplus Float64, -- 交易制度
    trading_hours String, -- 交易时间
    product_name String, -- ETF 期权字母简称
    de_listed_date Date, -- 退市日期
    trading_code String, -- 交易代码
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_option', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_option ON CLUSTER 'quant_cluster'
AS rq.instruments_option_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_option_local', rand());

-- 2.8 Convertible (Convertible Bond - 可转债)
CREATE TABLE IF NOT EXISTS rq.instruments_convertible_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 合约代码
    symbol String, -- 合约简称
    exchange LowCardinality(String), -- 交易所
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    type LowCardinality(String), -- 合约类型
    market_tplus Int32, -- 交易制度
    status LowCardinality(String), -- 合约状态
    round_lot Float64, -- 一手股数
    trading_code String, -- 交易代码
    trading_hours String, -- 交易时间
    stock_code String, -- 正股代码
    maturity_date Date, -- 到期日
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_convertible', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_convertible ON CLUSTER 'quant_cluster'
AS rq.instruments_convertible_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_convertible_local', rand());

-- 2.9 Repo (Repo - 回购)
CREATE TABLE IF NOT EXISTS rq.instruments_repo_local ON CLUSTER 'quant_cluster' (
    order_book_id String, -- 证券代码
    symbol String, -- 证券简称
    abbrev_symbol String, -- 证券名称缩写
    listed_date Date, -- 上市日期
    de_listed_date Date, -- 退市日期
    exchange LowCardinality(String), -- 交易所
    type LowCardinality(String), -- 合约类型
    status LowCardinality(String), -- 合约状态
    round_lot Float64, -- 一手股数
    trading_hours String, -- 交易时间
    trading_code String, -- 交易代码
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() -- 更新时间
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/rq/instruments_repo', '{replica}', updated_at
)
ORDER BY order_book_id;

CREATE TABLE IF NOT EXISTS rq.instruments_repo ON CLUSTER 'quant_cluster'
AS rq.instruments_repo_local
ENGINE = Distributed('quant_cluster', 'rq', 'instruments_repo_local', rand());

-- ============================================================
-- 3. RiceQuant 数据源索引视图
-- 从 rq 分布式表中整合数据到 ref.instruments 统一视图
-- ============================================================

CREATE VIEW IF NOT EXISTS ref.instruments ON CLUSTER 'quant_cluster' AS
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_cs_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_etf_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_lof_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_indx_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_future_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_spot_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_option_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_convertible_local
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
    'RICEQUANT' AS provider,
    updated_at
FROM rq.instruments_repo_local;

-- ============================================================
-- 4. 行情数据 (market_data) — 大表，按 symbol 哈希分片
--    仅在大量数据列上使用 CODEC 压缩
-- ============================================================

-- 4.1 分钟线
CREATE TABLE IF NOT EXISTS market_data.bars_1m_local ON CLUSTER 'quant_cluster' (
    dt Date COMMENT '业务日期' CODEC(Delta, ZSTD(1)),
    bar_time DateTime COMMENT 'K 线对齐时间' CODEC(Delta, ZSTD(1)),
    symbol LowCardinality(String) COMMENT '统一代码, e.g. 000300.XSHG',
    raw_symbol LowCardinality(String) DEFAULT '' COMMENT '原始代码',
    type LowCardinality(String) DEFAULT '' COMMENT '标的类型: stock, index, future, option, etf...',
    pre_close Float64 DEFAULT 0 COMMENT '前收盘价',
    open Float64 DEFAULT 0 COMMENT '开盘价',
    high Float64 DEFAULT 0 COMMENT '最高价',
    low Float64 DEFAULT 0 COMMENT '最低价',
    close Float64 DEFAULT 0 COMMENT '收盘价',
    volume Float64 DEFAULT 0 COMMENT '成交量',
    amount Float64 DEFAULT 0 COMMENT '成交额',
    open_interest Float64 DEFAULT 0 COMMENT '持仓量(期货)',
    settle Float64 DEFAULT 0 COMMENT '结算价',
    pre_settle Float64 DEFAULT 0 COMMENT '前结算价',
    local_time DateTime64(3) COMMENT '本地时间' CODEC(Delta, ZSTD(1)),
    provider LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3) COMMENT '数据更新时间'
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/market_data/bars_1m', '{replica}', updated_at
)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt, bar_time)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS market_data.bars_1m ON CLUSTER 'quant_cluster'
AS market_data.bars_1m_local
ENGINE = Distributed('quant_cluster', 'market_data', 'bars_1m_local', sipHash64(symbol));

-- 4.2 日线
CREATE TABLE IF NOT EXISTS market_data.bars_1d_local ON CLUSTER 'quant_cluster' (
    dt Date COMMENT '业务日期' CODEC(Delta, ZSTD(1)),
    symbol LowCardinality(String) COMMENT '统一代码, e.g. 000300.XSHG',
    raw_symbol LowCardinality(String) DEFAULT '' COMMENT '原始代码',
    type LowCardinality(String) DEFAULT '' COMMENT '标的类型: stock, index, future, option, etf...',
    pre_close Float64 DEFAULT 0 COMMENT '前收盘价',
    open Float64 DEFAULT 0 COMMENT '开盘价',
    high Float64 DEFAULT 0 COMMENT '最高价',
    low Float64 DEFAULT 0 COMMENT '最低价',
    close Float64 DEFAULT 0 COMMENT '收盘价',
    volume Float64 DEFAULT 0 COMMENT '成交量',
    amount Float64 DEFAULT 0 COMMENT '成交额',
    pct_chg Float64 DEFAULT 0 COMMENT '涨跌幅',
    pct_chg_log Float64 DEFAULT 0 COMMENT '对数收益率',
    adj_factor Float64 DEFAULT 1 COMMENT '复权因子',
    amplitude Float64 DEFAULT 0 COMMENT '振幅',
    limit_up Float64 DEFAULT 0 COMMENT '涨停价',
    limit_down Float64 DEFAULT 0 COMMENT '跌停价',
    open_interest Float64 DEFAULT 0 COMMENT '持仓量(期货)',
    settle Float64 DEFAULT 0 COMMENT '结算价',
    pre_settle Float64 DEFAULT 0 COMMENT '前结算价',
    trading_status Enum8('NORMAL'=0, 'HALTED'=1, 'UNKNOWN'=2) DEFAULT 'UNKNOWN' COMMENT '交易状态',
    provider LowCardinality(String) DEFAULT 'UNKNOWN' COMMENT '数据来源',
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3) COMMENT '数据更新时间'
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/market_data/bars_1d', '{replica}', updated_at
)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS market_data.bars_1d ON CLUSTER 'quant_cluster'
AS market_data.bars_1d_local
ENGINE = Distributed('quant_cluster', 'market_data', 'bars_1d_local', sipHash64(symbol));

-- 4.3 Tick 快照 (带 TTL)
CREATE TABLE IF NOT EXISTS market_data.ticks_local ON CLUSTER 'quant_cluster' (
    symbol      LowCardinality(String)                        COMMENT '统一代码',
    ts          DateTime64(3, 'Asia/Shanghai')                CODEC(DoubleDelta, ZSTD(1)) COMMENT '成交时间',
    price       Float64                                       CODEC(Gorilla, ZSTD(1))    COMMENT '成交价',
    volume      Float64                                       CODEC(Delta, ZSTD(1))      COMMENT '成交量',
    bid1_price  Float64                                       CODEC(Gorilla, ZSTD(1)),
    bid1_volume Float64                                       CODEC(Delta, ZSTD(1)),
    ask1_price  Float64                                       CODEC(Gorilla, ZSTD(1)),
    ask1_volume Float64                                       CODEC(Delta, ZSTD(1)),
    bs_flag     Enum8('Unknown'=0, 'Buy'=1, 'Sell'=2)        COMMENT '主动买卖方向',
    provider    LowCardinality(String) DEFAULT 'UNKNOWN'      COMMENT '数据来源',
    received_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64(3, 'Asia/Shanghai') COMMENT '入库物理时间，用于延时监控'
) ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/market_data/ticks', '{replica}'
)
PARTITION BY toYYYYMM(toDate(ts))
ORDER BY (symbol, ts)
TTL toDateTime(ts) + INTERVAL 30 DAY DELETE
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1;

CREATE TABLE IF NOT EXISTS market_data.ticks ON CLUSTER 'quant_cluster'
AS market_data.ticks_local
ENGINE = Distributed('quant_cluster', 'market_data', 'ticks_local', sipHash64(symbol));