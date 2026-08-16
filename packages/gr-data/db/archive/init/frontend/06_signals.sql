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
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_signal_batches_code_not_blank CHECK (btrim(batch_code) <> '')
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

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_signals_code_not_blank CHECK (btrim(signal_code) <> ''),
    CONSTRAINT chk_signals_market_not_blank CHECK (btrim(market) <> ''),
    CONSTRAINT chk_signals_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_signals_type_valid CHECK (type IN ('entry', 'exit', 'adjust', 'alert')),
    CONSTRAINT chk_signals_action_valid
        CHECK (action IN ('buy', 'sell', 'hold', 'close', 'open', 'add', 'reduce')),
    CONSTRAINT chk_signals_direction_valid
        CHECK (direction IS NULL OR direction IN ('long', 'short', 'neutral')),
    CONSTRAINT chk_signals_prices_non_negative
        CHECK (
            (entry_low IS NULL OR entry_low >= 0)
            AND (entry_high IS NULL OR entry_high >= 0)
            AND (trigger_price IS NULL OR trigger_price >= 0)
            AND (target_price IS NULL OR target_price >= 0)
            AND (stop_loss_price IS NULL OR stop_loss_price >= 0)
            AND (strike_price IS NULL OR strike_price >= 0)
            AND (exit_price IS NULL OR exit_price >= 0)
        ),
    CONSTRAINT chk_signals_entry_range
        CHECK (entry_low IS NULL OR entry_high IS NULL OR entry_low <= entry_high),
    CONSTRAINT chk_signals_suggested_quantity_positive
        CHECK (suggested_quantity IS NULL OR suggested_quantity > 0),
    CONSTRAINT chk_signals_position_pct_range CHECK (position_pct IS NULL OR position_pct BETWEEN 0 AND 1),
    CONSTRAINT chk_signals_confidence_range CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_signals_urgency_valid CHECK (urgency IN ('low', 'normal', 'high', 'critical')),
    CONSTRAINT chk_signals_option_type_valid CHECK (option_type IS NULL OR option_type IN ('call', 'put')),
    CONSTRAINT chk_signals_access_tier_non_negative CHECK (access_tier >= 0),
    CONSTRAINT chk_signals_delay_free_hours_non_negative
        CHECK (delay_free_hours IS NULL OR delay_free_hours >= 0),
    CONSTRAINT chk_signals_status_valid CHECK (status IN ('active', 'expired', 'cancelled')),
    CONSTRAINT chk_signals_result_valid
        CHECK (result IS NULL OR result IN ('win', 'loss', 'neutral', 'cancelled'))
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

    PRIMARY KEY (signal_id, symbol, snapshot_time),
    CONSTRAINT chk_signal_market_snapshot_symbol_not_blank CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_signal_market_snapshot_prices_non_negative
        CHECK (
            (open IS NULL OR open >= 0)
            AND (high IS NULL OR high >= 0)
            AND (low IS NULL OR low >= 0)
            AND (close IS NULL OR close >= 0)
        ),
    CONSTRAINT chk_signal_market_snapshot_high_low
        CHECK (high IS NULL OR low IS NULL OR high >= low),
    CONSTRAINT chk_signal_market_snapshot_volume_non_negative CHECK (volume IS NULL OR volume >= 0),
    CONSTRAINT chk_signal_market_snapshot_turnover_non_negative CHECK (turnover IS NULL OR turnover >= 0),
    CONSTRAINT chk_signal_market_snapshot_open_interest_non_negative
        CHECK (open_interest IS NULL OR open_interest >= 0),
    CONSTRAINT chk_signal_market_snapshot_implied_vol_non_negative
        CHECK (implied_vol IS NULL OR implied_vol >= 0)
);
