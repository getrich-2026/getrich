-- ClickHouse Table Schema for getrich project

-- 1. 分钟 K 线数据表 (min_bar)
-- 用于存储所有品种的分钟 K 线数据。
-- 按月分区，主键为（品种代码，时间戳），确保查询性能。
CREATE TABLE IF NOT EXISTS getrich.min_bar
(
    `date` UInt32,
    `time` Int32,
    `pre_close` Int64,
    `open` Int64,
    `high` Int64,
    `low` Int64,
    `close` Int64,
    `volume` Int64,
    `turnover` Int64,
    `open_interest` Int64,
    `pre_settle_price` Int64,
    `settle_price` Int64,
    `symbol` String,
    `trading_day` Int32,
    `local_time` Int64,
    `insert_time` DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(toDate(toDateTime(local_time / 1000)))
ORDER BY (symbol, local_time);

-- 2. 代码基本信息表 (code_info)
-- 用于存储每个品种的静态基本信息。
-- 该表不分区，使用 ReplacingMergeTree 引擎，可以根据 symbol 进行更新，保留最新版本的数据。
CREATE TABLE IF NOT EXISTS getrich.code_info
(
    `sec_type` Int32,
    `sec_name` String,
    `date` Int32,
    `high_limited` UInt32,
    `low_limited` UInt32,
    `multiplier` Int32,
    `margin_ratio` Int32,
    `price_tick` Int32,
    `capital` Int64,
    `cap_change_date` UInt32,
    `trade_date_in` UInt32,
    `trade_date_out` UInt32,
    `is_halt` Int8,
    `margin_unit` UInt32,
    `margin_ratio_param1` Int32,
    `margin_ratio_param2` Int32,
    `sec_name_ext` String,
    `symbol` String,
    `insert_time` DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(insert_time)
ORDER BY (symbol);
