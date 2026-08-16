-- ============================================================
-- GetRich Quant Platform — ClickHouse 行情数据 Schema
-- 用途: 时序行情数据 (分钟线、日线、Tick) — 大表、只追加、OLAP
-- 部署: 单节点，无集群/副本
-- 时区: DateTime64 统一使用 'Asia/Shanghai'
--       夜盘数据 (23:00–02:30) 必须用 DateTime64，禁止用 Date
-- ============================================================

CREATE DATABASE IF NOT EXISTS market_data;

-- ============================================================
-- 1. 分钟线 (bars_1m)
--    排序键: (symbol, dt, bar_time) — 按标的+时间顺序扫描
--    分区键: toYYYYMM(dt) — 按月分区，TTL 5 年
-- ============================================================

CREATE TABLE IF NOT EXISTS market_data.bars_1m (
    dt            Date                            CODEC(Delta, ZSTD(1)),      -- 业务日期 (分区用)
    bar_time      DateTime64(3, 'Asia/Shanghai')  CODEC(DoubleDelta, ZSTD(1)), -- K 线收盘对齐时间 (含夜盘)
    symbol        LowCardinality(String),                                      -- 统一代码, e.g. RB2501.SHFE
    raw_symbol    LowCardinality(String)          DEFAULT '',                  -- 数据源原始代码
    type          LowCardinality(String)          DEFAULT '',                  -- 标的类型: stock/index/future/option/etf
    open          Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 开盘价
    high          Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 最高价
    low           Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 最低价
    close         Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 收盘价
    volume        Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 成交量
    amount        Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 成交额
    open_interest Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 持仓量 (期货/期权)
    pre_close     Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 前收盘价
    settle        Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 结算价
    pre_settle    Float64                         CODEC(ZSTD(1)) DEFAULT 0,   -- 前结算价
    provider      LowCardinality(String)          DEFAULT 'UNKNOWN',          -- 数据来源
    updated_at    DateTime64(3, 'Asia/Shanghai')  DEFAULT now64(3)            -- 入库时间
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt, bar_time)
TTL dt + INTERVAL 5 YEAR
SETTINGS index_granularity = 8192;

-- ============================================================
-- 2. 日线 (bars_1d)
--    排序键: (symbol, dt)
--    分区键: toYYYYMM(dt)，TTL 20 年
-- ============================================================

CREATE TABLE IF NOT EXISTS market_data.bars_1d (
    dt              Date                            CODEC(Delta, ZSTD(1)),       -- 业务日期
    symbol          LowCardinality(String),                                       -- 统一代码
    raw_symbol      LowCardinality(String)          DEFAULT '',                   -- 数据源原始代码
    type            LowCardinality(String)          DEFAULT '',                   -- 标的类型
    open            Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 开盘价
    high            Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 最高价
    low             Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 最低价
    close           Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 收盘价
    volume          Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 成交量
    amount          Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 成交额
    pre_close       Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 前收盘价
    pct_chg         Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 简单收益率 (close/pre_close - 1)
    pct_chg_log     Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 对数收益率 ln(close/pre_close)
    adj_factor      Float64                         CODEC(ZSTD(1)) DEFAULT 1,    -- 后复权因子
    amplitude       Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 振幅 (high-low)/pre_close
    limit_up        Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 涨停价
    limit_down      Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 跌停价
    open_interest   Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 持仓量 (期货/期权)
    settle          Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 结算价
    pre_settle      Float64                         CODEC(ZSTD(1)) DEFAULT 0,    -- 前结算价
    trading_status  Enum8('NORMAL'=0, 'HALTED'=1, 'UNKNOWN'=2) DEFAULT 'UNKNOWN', -- 交易状态
    provider        LowCardinality(String)          DEFAULT 'UNKNOWN',           -- 数据来源
    updated_at      DateTime64(3, 'Asia/Shanghai')  DEFAULT now64(3)             -- 入库时间
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 20 YEAR
SETTINGS index_granularity = 8192;

-- ============================================================
-- 3. Tick 快照 (ticks)
--    TTL: 30 天 (实盘监控用，历史分析走分钟线)
--    DoubleDelta — 适合毫秒级高频时间戳
-- ============================================================

CREATE TABLE IF NOT EXISTS market_data.ticks (
    symbol        LowCardinality(String),                                          -- 统一代码
    ts            DateTime64(3, 'Asia/Shanghai')  CODEC(DoubleDelta, ZSTD(1)),    -- 行情时间戳 (含夜盘)
    price         Float64                         CODEC(Gorilla, ZSTD(1)),         -- 最新价
    volume        Float64                         CODEC(Delta, ZSTD(1)),           -- 成交量
    amount        Float64                         CODEC(ZSTD(1)),                  -- 成交额
    open_interest Float64                         CODEC(ZSTD(1)),                  -- 持仓量
    bid1_price    Float64                         CODEC(Gorilla, ZSTD(1)),         -- 买一价
    bid1_volume   Float64                         CODEC(Delta, ZSTD(1)),           -- 买一量
    ask1_price    Float64                         CODEC(Gorilla, ZSTD(1)),         -- 卖一价
    ask1_volume   Float64                         CODEC(Delta, ZSTD(1)),           -- 卖一量
    bs_flag       Enum8('Unknown'=0, 'Buy'=1, 'Sell'=2),                           -- 主动买卖方向
    provider      LowCardinality(String)          DEFAULT 'UNKNOWN',              -- 数据来源
    received_at   DateTime64(3, 'Asia/Shanghai')  DEFAULT now64(3)                -- 入库物理时间 (延时监控)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(toDate(ts))
ORDER BY (symbol, ts)
TTL toDateTime(ts) + INTERVAL 30 DAY DELETE
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1;
