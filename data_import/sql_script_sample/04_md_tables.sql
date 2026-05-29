-- ============================================================
-- GetRich 数据导入层 PostgreSQL 行情数据表 (md schema)
-- 用途: 行情数据 PostgreSQL 侧副本 — 小范围查询、数据校验
--       OLAP 主力走 ClickHouse (market_data.bars_1m / bars_1d)
-- 时区约定: TIMESTAMPTZ 以 UTC 存储，应用层 SET timezone = 'Asia/Shanghai'
--           夜盘 bar_time (23:00–02:30) 必须用 TIMESTAMPTZ，禁止用 DATE
-- ============================================================

-- ============================================================
-- 1. 分钟线 (bars_1m)
--    主键: (symbol, dt, bar_time) — 与 ClickHouse ORDER BY 对齐
-- ============================================================

CREATE TABLE IF NOT EXISTS md.bars_1m (
    dt              DATE                NOT NULL,                      -- 业务日期 (分区/索引用)
    bar_time        TIMESTAMPTZ         NOT NULL,                      -- K 线收盘对齐时间 (含夜盘)
    symbol          TEXT                NOT NULL,                      -- 统一代码, e.g. RB2501.SHFE
    raw_symbol      TEXT                NOT NULL DEFAULT '',           -- 数据源原始代码
    type            TEXT                NOT NULL DEFAULT '',           -- 标的类型: stock/index/future/option/etf
    open            DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 开盘价
    high            DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 最高价
    low             DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 最低价
    close           DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 收盘价
    volume          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 成交量
    amount          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 成交额
    open_interest   DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 持仓量 (期货/期权)
    pre_close       DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 前收盘价
    settle          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 结算价
    pre_settle      DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 前结算价
    provider        TEXT                NOT NULL DEFAULT 'UNKNOWN',    -- 数据来源
    updated_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),        -- 入库时间
    PRIMARY KEY (symbol, dt, bar_time),
    CONSTRAINT chk_bars_1m_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_bars_1m_open_non_negative
        CHECK (open >= 0),
    CONSTRAINT chk_bars_1m_high_gte_low
        CHECK (high >= low),
    CONSTRAINT chk_bars_1m_volume_non_negative
        CHECK (volume >= 0),
    CONSTRAINT chk_bars_1m_bar_time_matches_dt
        CHECK (DATE(bar_time AT TIME ZONE 'Asia/Shanghai') = dt
               OR DATE((bar_time AT TIME ZONE 'Asia/Shanghai') - INTERVAL '1 day') = dt)
);

CREATE INDEX IF NOT EXISTS idx_bars_1m_dt
    ON md.bars_1m (dt);
CREATE INDEX IF NOT EXISTS idx_bars_1m_provider_dt
    ON md.bars_1m (provider, dt);

-- ============================================================
-- 2. 日线 (bars_1d)
--    主键: (symbol, dt) — 与 ClickHouse ORDER BY 对齐
-- ============================================================

CREATE TABLE IF NOT EXISTS md.bars_1d (
    dt              DATE                NOT NULL,                      -- 业务日期
    symbol          TEXT                NOT NULL,                      -- 统一代码
    raw_symbol      TEXT                NOT NULL DEFAULT '',           -- 数据源原始代码
    type            TEXT                NOT NULL DEFAULT '',           -- 标的类型
    open            DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 开盘价
    high            DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 最高价
    low             DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 最低价
    close           DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 收盘价
    volume          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 成交量
    amount          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 成交额
    pre_close       DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 前收盘价
    pct_chg         DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 简单收益率 (close/pre_close - 1)
    pct_chg_log     DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 对数收益率 ln(close/pre_close)
    adj_factor      DOUBLE PRECISION    NOT NULL DEFAULT 1,            -- 后复权因子
    amplitude       DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 振幅 (high-low)/pre_close
    limit_up        DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 涨停价
    limit_down      DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 跌停价
    open_interest   DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 持仓量 (期货/期权)
    settle          DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 结算价
    pre_settle      DOUBLE PRECISION    NOT NULL DEFAULT 0,            -- 前结算价
    trading_status  TEXT                NOT NULL DEFAULT 'UNKNOWN',    -- 交易状态
    provider        TEXT                NOT NULL DEFAULT 'UNKNOWN',    -- 数据来源
    updated_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),        -- 入库时间
    PRIMARY KEY (symbol, dt),
    CONSTRAINT chk_bars_1d_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_bars_1d_open_non_negative
        CHECK (open >= 0),
    CONSTRAINT chk_bars_1d_high_gte_low
        CHECK (high >= low),
    CONSTRAINT chk_bars_1d_volume_non_negative
        CHECK (volume >= 0),
    CONSTRAINT chk_bars_1d_adj_factor_positive
        CHECK (adj_factor > 0),
    CONSTRAINT chk_bars_1d_trading_status_valid
        CHECK (trading_status IN ('NORMAL', 'HALTED', 'UNKNOWN'))
);

CREATE INDEX IF NOT EXISTS idx_bars_1d_dt
    ON md.bars_1d (dt);
CREATE INDEX IF NOT EXISTS idx_bars_1d_type_dt
    ON md.bars_1d (type, dt);
CREATE INDEX IF NOT EXISTS idx_bars_1d_provider_dt
    ON md.bars_1d (provider, dt);
