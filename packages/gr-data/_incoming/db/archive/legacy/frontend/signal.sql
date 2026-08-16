CREATE TABLE signal_batches (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id  UUID        NOT NULL REFERENCES strategies(id),
    batch_code   VARCHAR(50) UNIQUE NOT NULL,  -- STR-001-20240315-B01
    note         TEXT,                         -- 本批调仓说明
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 信号
CREATE TABLE signals (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_code     VARCHAR(40) UNIQUE NOT NULL,
    strategy_id     UUID        NOT NULL REFERENCES strategies(id),
    batch_id        UUID        REFERENCES signal_batches(id),

    -- 标的
    market          VARCHAR(20) NOT NULL,   -- A股|港股|美股|期货|外汇|加密
    symbol          VARCHAR(30) NOT NULL,   -- 000001.SZ / AAPL / rb2405
    instrument_name VARCHAR(100),

    -- 信号内容
    type            VARCHAR(20) NOT NULL,   -- entry|exit|adjust|alert
    action          VARCHAR(20) NOT NULL,   -- open|close|add|reduce
    direction       VARCHAR(10),            -- long|short|neutral

    entry_low       NUMERIC(18,4),          -- 建议买入区间
    entry_high      NUMERIC(18,4),
    entry_price     NUMERIC(18,4),          -- 中间价或精确价
    target_price    NUMERIC(18,4),
    stop_loss_price NUMERIC(18,4),
    position_pct    NUMERIC(5,2),           -- 建议仓位比例 %
    confidence      SMALLINT,               -- 1–5

    logic_summary   TEXT,

    -- 访问控制（信号可以比策略有不同的 tier 和延迟）
    access_tier         SMALLINT    NOT NULL DEFAULT 0,
    delay_free_hours    INT,                -- NULL=不延迟免费; N=N小时后对所有人免费

    -- 生命周期
    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- active|expired|cancelled
    expire_at       TIMESTAMPTZ,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 结果（信号到期后回填）
    result          VARCHAR(20),    -- win|loss|neutral|cancelled
    exit_price      NUMERIC(18,4),
    pnl_pct         NUMERIC(8,4),
    resolved_at     TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);