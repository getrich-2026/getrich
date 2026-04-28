-- ============================================================
-- 信号模块
-- ============================================================

-- 批次（同一次调仓发出的多条信号共享一个 batch_code）
CREATE TABLE frontend.signal_batches (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID            NOT NULL REFERENCES frontend.strategies(id),
    batch_code      VARCHAR(50)     UNIQUE NOT NULL,        -- STR-001-20260415-B01
    note            TEXT,                                   -- 本批调仓说明
    published_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 信号主表
CREATE TABLE frontend.signals (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_code     VARCHAR(40)     UNIQUE NOT NULL,        -- SIG_20260415_001（对外展示）
    strategy_id     UUID            NOT NULL REFERENCES frontend.strategies(id),
    batch_id        UUID            REFERENCES frontend.signal_batches(id),
    parent_signal_id UUID           REFERENCES frontend.signals(id), -- entry/exit 配对关联

    -- 标的信息
    market          VARCHAR(20)     NOT NULL,               -- A股|港股|美股|期货|外汇|加密
    exchange        VARCHAR(16),                            -- SSE/SZSE/CFFEX/SHFE/DCE/CZCE
    symbol          VARCHAR(30)     NOT NULL,               -- 000001.SZ / IF2506 / AAPL
    symbol_name     VARCHAR(100),

    -- 信号内容
    type            VARCHAR(20)     NOT NULL,               -- entry|exit|adjust|alert
    action          VARCHAR(20)     NOT NULL,               -- buy|sell|hold|close|open|add|reduce
    direction       VARCHAR(10),                            -- long|short|neutral

    -- 价格与数量
    entry_low           NUMERIC(18,4),                      -- 建议买入区间下沿
    entry_high          NUMERIC(18,4),                      -- 建议买入区间上沿
    trigger_price       NUMERIC(18,4),                      -- 触发价格（中间价）
    target_price        NUMERIC(18,4),                      -- 目标价格
    stop_loss_price     NUMERIC(18,4),                      -- 止损价格
    suggested_quantity  INT,                                -- 建议数量/手数
    position_pct        NUMERIC(5,4),                       -- 建议仓位比例（0.0000~1.0000）

    -- 信号质量
    confidence      NUMERIC(3,2)    NOT NULL DEFAULT 0.50,  -- 置信度 0.00~1.00
    urgency         VARCHAR(8)      NOT NULL DEFAULT 'normal', -- low|normal|high|critical

    -- 触发上下文
    reason          TEXT,                                   -- 简述
    reason_detail   JSONB           NOT NULL DEFAULT '{}',  -- 详细触发数据 {spread_current, z_score, trigger_rule ...}
    logic_summary   TEXT,                                   -- 给用户看的 summary（和 reason 的区别：可以更长）

    -- 期权专用
    option_type     VARCHAR(4),                             -- call|put
    strike_price    NUMERIC(18,4),
    expiry_date     DATE,
    greeks          JSONB,                                  -- {delta, gamma, theta, vega, rho}

    -- 访问控制
    access_tier         SMALLINT    NOT NULL DEFAULT 0,
    delay_free_hours    INT,                                -- NULL=不延迟免费；N=N小时后对所有人免费

    -- 生命周期
    status          VARCHAR(20)     NOT NULL DEFAULT 'active',  -- active|expired|cancelled
    expire_at       TIMESTAMPTZ,
    published_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 结果回填（信号结束后）
    result          VARCHAR(20),                            -- win|loss|neutral|cancelled
    exit_price      NUMERIC(18,4),
    pnl_pct         NUMERIC(8,4),
    resolved_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 信号触发时刻的行情快照（对应前端 5.2 信号详情页的市场数据区）
CREATE TABLE frontend.signal_market_snapshot (
    signal_id       UUID            NOT NULL REFERENCES frontend.signals(id) ON DELETE CASCADE,
    symbol          VARCHAR(30)     NOT NULL,
    snapshot_time   TIMESTAMPTZ     NOT NULL,

    -- OHLCV
    open            NUMERIC(18,4),
    high            NUMERIC(18,4),
    low             NUMERIC(18,4),
    close           NUMERIC(18,4),
    volume          BIGINT,
    turnover        NUMERIC(20,4),

    -- 市场微结构（期货专用）
    open_interest   BIGINT,
    basis           NUMERIC(18,4),

    -- 技术指标快照（合并为 JSONB，后续指标扩展不改表结构）
    indicators      JSONB,                                  -- {ma5, ma10, ma20, ma60, rsi_14, macd, macd_signal, macd_hist, atr_14, bollinger_upper, bollinger_lower}

    -- 期权专用
    implied_vol     NUMERIC(10,6),
    greeks_snapshot JSONB,                                  -- 行情快照时的 greeks

    PRIMARY KEY (signal_id, symbol, snapshot_time)
);
