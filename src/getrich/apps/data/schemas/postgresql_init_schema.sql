-- ============================================================
-- GetRich Quant Platform — PostgreSQL 初始化 Schema
-- 用途: 参考数据 (交易日历、标的信息) — 小表、高频读、支持复杂查询
-- 时区约定: TIMESTAMPTZ 以 UTC 存储，应用层 SET timezone = 'Asia/Shanghai'
-- ============================================================

CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS rq;

-- ============================================================
-- 1. 参考数据 (ref)
-- ============================================================

-- 1.1 交易日历
CREATE TABLE IF NOT EXISTS ref.calendar (
    exchange         VARCHAR(20)  NOT NULL,  -- 交易所, 如 XSHG / DCE
    dt               DATE         NOT NULL,  -- 日期
    is_trading       BOOLEAN      NOT NULL DEFAULT FALSE,  -- 是否交易日
    prev_trading_day DATE,                   -- 上一个交易日
    next_trading_day DATE,                   -- 下一个交易日
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, dt)
);

CREATE INDEX IF NOT EXISTS idx_calendar_trading
    ON ref.calendar (exchange, is_trading, dt);

-- 1.2 标的代码映射 (多数据源)
CREATE TABLE IF NOT EXISTS ref.symbol_mapping (
    symbol        TEXT        NOT NULL,  -- 标准代码, 如 RB2405
    provider      VARCHAR(20) NOT NULL,  -- 数据源标识, 如 rq / wind / hdb
    mapped_symbol TEXT        NOT NULL,  -- 数据源侧代码
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, symbol),
    UNIQUE (provider, mapped_symbol)
);

CREATE INDEX IF NOT EXISTS idx_symbol_mapping_symbol
    ON ref.symbol_mapping (symbol);

-- ============================================================
-- 2. RiceQuant 标的信息 (rq)
-- ============================================================

-- 2.1 CS — 股票
CREATE TABLE IF NOT EXISTS rq.instruments_cs (
    order_book_id    TEXT             PRIMARY KEY,  -- 证券代码
    symbol           TEXT             NOT NULL,      -- 证券简称
    abbrev_symbol    TEXT,                           -- 证券名称缩写
    round_lot        DOUBLE PRECISION,               -- 一手股数
    sector_code      VARCHAR(20),                    -- 板块缩写代码
    sector_code_name TEXT,                           -- 板块代码名
    industry_code    VARCHAR(30),                    -- 国民经济行业分类代码
    industry_name    TEXT,                           -- 国民经济行业分类名称
    listed_date      DATE,                           -- 上市日期
    de_listed_date   DATE,                           -- 退市日期
    issue_price      DOUBLE PRECISION,               -- 发行价
    type             VARCHAR(20),                    -- 合约类型
    exchange         VARCHAR(20),                    -- 交易所
    board_type       VARCHAR(20),                    -- 板块类别
    status           VARCHAR(20),                    -- 合约状态
    special_type     VARCHAR(20),                    -- 特别处理状态
    trading_hours    TEXT,                           -- 交易时间
    market_tplus     INTEGER,                        -- 交易制度
    purchasedate     DATE,                           -- 申购日期
    trading_code     TEXT,                           -- 交易代码
    office_address   TEXT,                           -- 办公地址
    province         VARCHAR(50),                    -- 省份
    updated_at       TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_exchange_status
    ON rq.instruments_cs (exchange, status, listed_date, de_listed_date);

-- 2.2 ETF — 交易所交易基金
CREATE TABLE IF NOT EXISTS rq.instruments_etf (
    order_book_id            TEXT             PRIMARY KEY,  -- 证券代码
    symbol                   TEXT             NOT NULL,      -- 证券简称
    abbrev_symbol            TEXT,                           -- 证券名称缩写
    round_lot                DOUBLE PRECISION,               -- 一手股数
    listed_date              DATE,                           -- 上市日期
    de_listed_date           DATE,                           -- 退市日期
    establishment_date       DATE,                           -- 成立日期
    type                     VARCHAR(20),                    -- 合约类型
    exchange                 VARCHAR(20),                    -- 交易所
    board_type               INTEGER,                        -- 板块类别
    status                   VARCHAR(20),                    -- 合约状态
    trading_hours            TEXT,                           -- 交易时间
    market_tplus             INTEGER,                        -- 交易制度
    least_redeem             DOUBLE PRECISION,               -- 最低申赎份额
    underlying_order_book_id TEXT,                           -- 追踪基准合约代码
    underlying_name          TEXT,                           -- 追踪基准合约名称
    trading_code             TEXT,                           -- 交易代码
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etf_exchange_status
    ON rq.instruments_etf (exchange, status);

-- 2.3 LOF — 上市型开放式基金
CREATE TABLE IF NOT EXISTS rq.instruments_lof (
    order_book_id            TEXT             PRIMARY KEY,  -- 证券代码
    symbol                   TEXT             NOT NULL,      -- 证券简称
    abbrev_symbol            TEXT,                           -- 证券名称缩写
    round_lot                DOUBLE PRECISION,               -- 一手股数
    listed_date              DATE,                           -- 上市日期
    de_listed_date           DATE,                           -- 退市日期
    establishment_date       DATE,                           -- 成立日期
    type                     VARCHAR(20),                    -- 合约类型
    exchange                 VARCHAR(20),                    -- 交易所
    board_type               INTEGER,                        -- 板块类别
    status                   VARCHAR(20),                    -- 合约状态
    trading_hours            TEXT,                           -- 交易时间
    market_tplus             INTEGER,                        -- 交易制度
    least_redeem             DOUBLE PRECISION,               -- 最低申赎份额
    underlying_order_book_id TEXT,                           -- 追踪基准合约代码
    underlying_name          TEXT,                           -- 追踪基准合约名称
    trading_code             TEXT,                           -- 交易代码
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lof_exchange_status
    ON rq.instruments_lof (exchange, status);

-- 2.4 INDX — 指数
CREATE TABLE IF NOT EXISTS rq.instruments_indx (
    order_book_id     TEXT             PRIMARY KEY,  -- 证券代码
    symbol            TEXT             NOT NULL,      -- 证券简称
    abbrev_symbol     TEXT,                           -- 证券名称缩写
    listed_date       DATE,                           -- 上市日期
    de_listed_date    DATE,                           -- 退市日期
    type              VARCHAR(20),                    -- 合约类型
    exchange          VARCHAR(20),                    -- 交易所
    status            VARCHAR(20),                    -- 合约状态
    base_date         DATE,                           -- 基日
    base_point        DOUBLE PRECISION,               -- 基点
    index_value       DOUBLE PRECISION,               -- 指数值
    underlying_symbol TEXT,                           -- 标的名称
    trading_hours     TEXT,                           -- 交易时间
    market_tplus      DOUBLE PRECISION,               -- 交易制度
    round_lot         DOUBLE PRECISION,               -- 一手股数
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_indx_exchange
    ON rq.instruments_indx (exchange);

-- 2.5 Future — 期货
CREATE TABLE IF NOT EXISTS rq.instruments_future (
    order_book_id            TEXT             PRIMARY KEY,  -- 期货代码
    symbol                   TEXT             NOT NULL,      -- 期货简称
    type                     VARCHAR(20),                    -- 合约类型
    exchange                 VARCHAR(20),                    -- 交易所
    product                  VARCHAR(30),                    -- 合约品种 (如 RB / IF)
    listed_date              DATE,                           -- 上市日期
    de_listed_date           DATE,                           -- 退市日期
    maturity_date            DATE,                           -- 到期日
    start_delivery_date      DATE,                           -- 开始交割日
    end_delivery_date        DATE,                           -- 结束交割日
    contract_multiplier      DOUBLE PRECISION,               -- 合约乘数
    margin_rate              DOUBLE PRECISION,               -- 最低保证金率
    round_lot                DOUBLE PRECISION,               -- 一手数量
    market_tplus             DOUBLE PRECISION,               -- 交易制度
    underlying_order_book_id TEXT,                           -- 合约标的代码
    underlying_symbol        TEXT,                           -- 合约标的名称
    industry_name            TEXT,                           -- 行业分类名称
    trading_hours            TEXT,                           -- 交易时间
    trading_code             TEXT,                           -- 交易代码
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_future_product_maturity
    ON rq.instruments_future (product, maturity_date);
CREATE INDEX IF NOT EXISTS idx_future_exchange_delisted
    ON rq.instruments_future (exchange, de_listed_date);

-- 2.6 Spot — 现货
CREATE TABLE IF NOT EXISTS rq.instruments_spot (
    order_book_id       TEXT             PRIMARY KEY,  -- 合约代码
    symbol              TEXT             NOT NULL,      -- 合约简称
    type                VARCHAR(20),                    -- 合约类型
    exchange            VARCHAR(20),                    -- 交易所
    listed_date         DATE,                           -- 上市日期
    de_listed_date      DATE,                           -- 退市日期
    contract_multiplier DOUBLE PRECISION,               -- 合约乘数
    margin_rate         DOUBLE PRECISION,               -- 保证金率
    round_lot           DOUBLE PRECISION,               -- 一手股数
    market_tplus        INTEGER,                        -- 交易制度
    trading_hours       TEXT,                           -- 交易时间
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- 2.7 Option — 期权
CREATE TABLE IF NOT EXISTS rq.instruments_option (
    order_book_id            TEXT             PRIMARY KEY,  -- 合约代码
    symbol                   TEXT             NOT NULL,      -- 合约简称
    type                     VARCHAR(20),                    -- 合约类型
    exchange                 VARCHAR(20),                    -- 交易所
    listed_date              DATE,                           -- 上市日期
    de_listed_date           DATE,                           -- 退市日期
    maturity_date            DATE,                           -- 到期日
    underlying_order_book_id TEXT,                           -- 合约标的代码
    underlying_symbol        TEXT,                           -- 合约所属品种
    strike_price             DOUBLE PRECISION,               -- 行权价
    option_type              VARCHAR(10),                    -- 期权类型 (C/P)
    exercise_type            VARCHAR(10),                    -- 行权方式 (European/American)
    contract_multiplier      DOUBLE PRECISION,               -- 合约乘数
    round_lot                DOUBLE PRECISION,               -- 最小下单手数
    market_tplus             DOUBLE PRECISION,               -- 交易制度
    product_name             TEXT,                           -- ETF 期权字母简称
    trading_hours            TEXT,                           -- 交易时间
    trading_code             TEXT,                           -- 交易代码
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_option_underlying_maturity
    ON rq.instruments_option (underlying_order_book_id, maturity_date);
CREATE INDEX IF NOT EXISTS idx_option_exchange_type
    ON rq.instruments_option (exchange, option_type);

-- 2.8 Convertible — 可转债
CREATE TABLE IF NOT EXISTS rq.instruments_convertible (
    order_book_id  TEXT             PRIMARY KEY,  -- 合约代码
    symbol         TEXT             NOT NULL,      -- 合约简称
    type           VARCHAR(20),                    -- 合约类型
    exchange       VARCHAR(20),                    -- 交易所
    status         VARCHAR(20),                    -- 合约状态
    listed_date    DATE,                           -- 上市日期
    de_listed_date DATE,                           -- 退市日期
    maturity_date  DATE,                           -- 到期日
    stock_code     TEXT,                           -- 正股代码
    round_lot      DOUBLE PRECISION,               -- 一手股数
    market_tplus   INTEGER,                        -- 交易制度
    trading_hours  TEXT,                           -- 交易时间
    trading_code   TEXT,                           -- 交易代码
    updated_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_convertible_stock
    ON rq.instruments_convertible (stock_code);

-- 2.9 Repo — 回购
CREATE TABLE IF NOT EXISTS rq.instruments_repo (
    order_book_id  TEXT         PRIMARY KEY,  -- 证券代码
    symbol         TEXT         NOT NULL,      -- 证券简称
    abbrev_symbol  TEXT,                       -- 证券名称缩写
    type           VARCHAR(20),                -- 合约类型
    exchange       VARCHAR(20),                -- 交易所
    status         VARCHAR(20),                -- 合约状态
    listed_date    DATE,                       -- 上市日期
    de_listed_date DATE,                       -- 退市日期
    round_lot      DOUBLE PRECISION,           -- 一手股数
    trading_hours  TEXT,                       -- 交易时间
    trading_code   TEXT,                       -- 交易代码
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 3. 统一标的视图 ref.instruments
--    整合所有 rq 分表，供上层统一查询
-- ============================================================

CREATE OR REPLACE VIEW ref.instruments AS
-- CS (股票)
SELECT
    order_book_id                               AS symbol,
    trading_code                                AS symbol_raw,
    exchange,
    symbol                                      AS name,
    type,
    ''                                          AS und_code,
    ''                                          AS und_name,
    1.0                                         AS multiplier,
    0.0                                         AS margin_ratio,
    0.0                                         AS strike_price,
    ''                                          AS option_type,
    ''                                          AS exercise_type,
    'CNY'                                       AS currency,
    listed_date,
    COALESCE(de_listed_date, DATE '2099-12-31') AS delisted_date,
    'RICEQUANT'                                 AS provider,
    updated_at
FROM rq.instruments_cs
UNION ALL
-- ETF
SELECT order_book_id, trading_code, exchange, symbol, type,
    COALESCE(underlying_order_book_id, ''), COALESCE(underlying_name, ''),
    1.0, 0.0, 0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_etf
UNION ALL
-- LOF
SELECT order_book_id, trading_code, exchange, symbol, type,
    COALESCE(underlying_order_book_id, ''), COALESCE(underlying_name, ''),
    1.0, 0.0, 0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_lof
UNION ALL
-- INDX (指数)
SELECT order_book_id, order_book_id, exchange, symbol, type,
    COALESCE(underlying_symbol, ''), COALESCE(underlying_symbol, ''),
    1.0, 0.0, 0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_indx
UNION ALL
-- Future (期货)
SELECT order_book_id, trading_code, exchange, symbol, type,
    COALESCE(underlying_order_book_id, ''), COALESCE(underlying_symbol, ''),
    COALESCE(contract_multiplier, 1.0), COALESCE(margin_rate, 0.0),
    0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_future
UNION ALL
-- Spot (现货)
SELECT order_book_id, order_book_id, exchange, symbol, type,
    '', '',
    COALESCE(contract_multiplier, 1.0), COALESCE(margin_rate, 0.0),
    0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_spot
UNION ALL
-- Option (期权)
SELECT order_book_id, trading_code, exchange, symbol, type,
    COALESCE(underlying_order_book_id, ''), COALESCE(underlying_symbol, ''),
    COALESCE(contract_multiplier, 1.0), 0.0,
    COALESCE(strike_price, 0.0), COALESCE(option_type, ''), COALESCE(exercise_type, ''),
    'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_option
UNION ALL
-- Convertible (可转债)
SELECT order_book_id, trading_code, exchange, symbol, type,
    COALESCE(stock_code, ''), '',
    1.0, 0.0, 0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_convertible
UNION ALL
-- Repo (回购)
SELECT order_book_id, trading_code, exchange, symbol, type,
    '', '',
    1.0, 0.0, 0.0, '', '', 'CNY',
    listed_date, COALESCE(de_listed_date, DATE '2099-12-31'), 'RICEQUANT', updated_at
FROM rq.instruments_repo;
