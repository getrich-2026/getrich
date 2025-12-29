CREATE DATABASE IF NOT EXISTS rq;

-- 1. CS (Common Stock - 股票)
CREATE TABLE IF NOT EXISTS rq.instruments_cs (
    order_book_id String CODEC(ZSTD(1)), -- 证券代码
    symbol String CODEC(ZSTD(1)), -- 证券简称
    abbrev_symbol String CODEC(ZSTD(1)), -- 证券名称缩写
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    sector_code LowCardinality(String) CODEC(ZSTD(1)), -- 板块缩写代码
    sector_code_name LowCardinality(String) CODEC(ZSTD(1)), -- 板块代码名
    industry_code LowCardinality(String) CODEC(ZSTD(1)), -- 国民经济行业分类代码
    industry_name LowCardinality(String) CODEC(ZSTD(1)), -- 国民经济行业分类名称
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    issue_price Float64 CODEC(ZSTD(1)), -- 发行价
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    board_type LowCardinality(String) CODEC(ZSTD(1)), -- 板块类别
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    special_type LowCardinality(String) CODEC(ZSTD(1)), -- 特别处理状态
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    market_tplus Int32 CODEC(ZSTD(1)), -- 交易制度
    purchasedate Date CODEC(ZSTD(1)), -- 申购日期
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    office_address String CODEC(ZSTD(1)), -- 办公地址
    province LowCardinality(String) CODEC(ZSTD(1)), -- 省份
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 2. ETF (Exchange Traded Fund - 交易所交易基金)
CREATE TABLE IF NOT EXISTS rq.instruments_etf (
    order_book_id String CODEC(ZSTD(1)), -- 证券代码
    symbol String CODEC(ZSTD(1)), -- 证券简称
    abbrev_symbol String CODEC(ZSTD(1)), -- 证券名称缩写
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    market_tplus Int32 CODEC(ZSTD(1)), -- 交易制度
    least_redeem Float64 CODEC(ZSTD(1)), -- 最低申赎份额
    underlying_order_book_id String CODEC(ZSTD(1)), -- 追踪基准合约代码
    underlying_name String CODEC(ZSTD(1)), -- 追踪基准合约名称
    establishment_date Date CODEC(ZSTD(1)), -- 成立日期
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    board_type Int32 CODEC(ZSTD(1)), -- 板块类别
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 3. LOF (Listed Open-Ended Fund - 上市型开放式基金)
CREATE TABLE IF NOT EXISTS rq.instruments_lof (
    order_book_id String CODEC(ZSTD(1)), -- 证券代码
    symbol String CODEC(ZSTD(1)), -- 证券简称
    abbrev_symbol String CODEC(ZSTD(1)), -- 证券名称缩写
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    market_tplus Int32 CODEC(ZSTD(1)), -- 交易制度
    underlying_order_book_id String CODEC(ZSTD(1)), -- 追踪基准合约代码
    underlying_name String CODEC(ZSTD(1)), -- 追踪基准合约名称
    establishment_date Date CODEC(ZSTD(1)), -- 成立日期
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    board_type Int32 CODEC(ZSTD(1)), -- 板块类别
    least_redeem Float64 CODEC(ZSTD(1)), -- 最低申赎份额
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 4. INDX (Index - 指数)
CREATE TABLE IF NOT EXISTS rq.instruments_indx (
    order_book_id String CODEC(ZSTD(1)), -- 证券代码
    symbol String CODEC(ZSTD(1)), -- 证券简称
    abbrev_symbol String CODEC(ZSTD(1)), -- 证券名称缩写
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    base_date Date CODEC(ZSTD(1)), -- 基日
    base_point Float64 CODEC(ZSTD(1)), -- 基点
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    market_tplus Float64 CODEC(ZSTD(1)), -- 交易制度
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    `index` Float64 CODEC(ZSTD(1)), -- 指数值
    underlying_symbol String CODEC(ZSTD(1)), -- 标的名称
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 5. Future (Futures - 期货)
CREATE TABLE IF NOT EXISTS rq.instruments_future (
    order_book_id String CODEC(ZSTD(1)), -- 期货代码
    symbol String CODEC(ZSTD(1)), -- 期货简称
    margin_rate Float64 CODEC(ZSTD(1)), -- 最低保证金率
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    industry_name LowCardinality(String) CODEC(ZSTD(1)), -- 行业分类名称
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    market_tplus Float64 CODEC(ZSTD(1)), -- 交易制度
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    contract_multiplier Float64 CODEC(ZSTD(1)), -- 合约乘数
    underlying_order_book_id String CODEC(ZSTD(1)), -- 合约标的代码
    underlying_symbol String CODEC(ZSTD(1)), -- 合约标的名称
    maturity_date Date CODEC(ZSTD(1)), -- 到期日
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    product LowCardinality(String) CODEC(ZSTD(1)), -- 合约种类
    start_delivery_date Date CODEC(ZSTD(1)), -- 开始交割日
    end_delivery_date Date CODEC(ZSTD(1)), -- 结束交割日
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 6. Spot (Spot - 现货)
CREATE TABLE IF NOT EXISTS rq.instruments_spot (
    order_book_id String CODEC(ZSTD(1)), -- 合约代码
    symbol String CODEC(ZSTD(1)), -- 合约简称
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    market_tplus Int32 CODEC(ZSTD(1)), -- 交易制度
    contract_multiplier Float64 CODEC(ZSTD(1)), -- 合约乘数
    margin_rate Float64 CODEC(ZSTD(1)), -- 保证金率
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 7. Option (Option - 期权)
CREATE TABLE IF NOT EXISTS rq.instruments_option (
    order_book_id String CODEC(ZSTD(1)), -- 合约代码
    symbol String CODEC(ZSTD(1)), -- 合约简称
    round_lot Float64 CODEC(ZSTD(1)), -- 最小下单手数
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    contract_multiplier Float64 CODEC(ZSTD(1)), -- 合约乘数
    underlying_order_book_id String CODEC(ZSTD(1)), -- 合约标的代码
    underlying_symbol String CODEC(ZSTD(1)), -- 合约所属品种
    maturity_date Date CODEC(ZSTD(1)), -- 到期日
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    strike_price Float64 CODEC(ZSTD(1)), -- 行权价
    option_type LowCardinality(String) CODEC(ZSTD(1)), -- 期权类型
    exercise_type LowCardinality(String) CODEC(ZSTD(1)), -- 行权方式
    market_tplus Float64 CODEC(ZSTD(1)), -- 交易制度
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    product_name String CODEC(ZSTD(1)), -- ETF 期权字母简称
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 8. Convertible (Convertible Bond - 可转债)
CREATE TABLE IF NOT EXISTS rq.instruments_convertible (
    order_book_id String CODEC(ZSTD(1)), -- 合约代码
    symbol String CODEC(ZSTD(1)), -- 合约简称
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    market_tplus Int32 CODEC(ZSTD(1)), -- 交易制度
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    stock_code String CODEC(ZSTD(1)), -- 正股代码
    maturity_date Date CODEC(ZSTD(1)), -- 到期日
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;

-- 9. Repo (Repo - 回购)
CREATE TABLE IF NOT EXISTS rq.instruments_repo (
    order_book_id String CODEC(ZSTD(1)), -- 证券代码
    symbol String CODEC(ZSTD(1)), -- 证券简称
    abbrev_symbol String CODEC(ZSTD(1)), -- 证券名称缩写
    listed_date Date CODEC(ZSTD(1)), -- 上市日期
    de_listed_date Date CODEC(ZSTD(1)), -- 退市日期
    exchange LowCardinality(String) CODEC(ZSTD(1)), -- 交易所
    type LowCardinality(String) CODEC(ZSTD(1)), -- 合约类型
    status LowCardinality(String) CODEC(ZSTD(1)), -- 合约状态
    round_lot Float64 CODEC(ZSTD(1)), -- 一手股数
    trading_hours String CODEC(ZSTD(1)), -- 交易时间
    trading_code String CODEC(ZSTD(1)), -- 交易代码
    updated_at DateTime64(3, 'Asia/Shanghai') DEFAULT now64() CODEC(ZSTD(1)) -- 更新时间
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY order_book_id;