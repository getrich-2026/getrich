-- ============================================================
-- 用户侧的信号状态 & 推送配置
-- ============================================================

-- 信号已读 + 执行记录（对应前端 5.3 POST /signals/{id}/read、5.4 execute）
CREATE TABLE frontend.user_signal_reads (
    user_id         UUID            NOT NULL REFERENCES frontend.users(id) ON DELETE CASCADE,
    signal_id       UUID            NOT NULL REFERENCES frontend.signals(id) ON DELETE CASCADE,
    read_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 执行反馈
    is_executed     BOOLEAN         NOT NULL DEFAULT FALSE,
    executed_price  NUMERIC(18,4),
    executed_qty    INT,
    executed_at     TIMESTAMPTZ,
    note            TEXT,

    PRIMARY KEY (user_id, signal_id),
    CONSTRAINT chk_signal_reads_executed_price_non_negative
        CHECK (executed_price IS NULL OR executed_price >= 0),
    CONSTRAINT chk_signal_reads_executed_qty_positive CHECK (executed_qty IS NULL OR executed_qty > 0),
    CONSTRAINT chk_signal_reads_executed_state
        CHECK (
            is_executed = FALSE
            OR executed_price IS NOT NULL
            OR executed_qty IS NOT NULL
            OR executed_at IS NOT NULL
        )
);

-- 用户全局推送设置（对应前端 5.6/5.7 GET/PUT /user/signal-settings）
CREATE TABLE frontend.user_signal_settings (
    user_id              UUID           PRIMARY KEY REFERENCES frontend.users(id) ON DELETE CASCADE,
    push_enabled         BOOLEAN        NOT NULL DEFAULT TRUE,

    -- 推送渠道开关：{"app_push":true,"sms":false,"email":true,"wechat_service":true,"websocket":true}
    channels             JSONB          NOT NULL DEFAULT '{"app_push":true,"sms":false,"email":false,"wechat_service":false,"websocket":true}',

    -- 全局过滤规则
    confidence_threshold NUMERIC(3,2)   NOT NULL DEFAULT 0.50,
    urgency_filter       TEXT[]         NOT NULL DEFAULT ARRAY['normal','high','critical'],
    quiet_hours          JSONB          NOT NULL DEFAULT '{"enabled":false,"start":"22:00","end":"08:30"}',
    trading_hours_only   BOOLEAN        NOT NULL DEFAULT FALSE,

    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_user_signal_settings_confidence_range
        CHECK (confidence_threshold BETWEEN 0 AND 1)
);

-- 单策略级别的推送覆盖设置
CREATE TABLE frontend.user_strategy_signal_settings (
    user_id              UUID           NOT NULL REFERENCES frontend.users(id) ON DELETE CASCADE,
    strategy_id          UUID           NOT NULL REFERENCES frontend.strategies(id) ON DELETE CASCADE,
    push_enabled         BOOLEAN        NOT NULL DEFAULT TRUE,
    confidence_threshold NUMERIC(3,2),                      -- NULL 表示继承全局配置
    notify_entry_only    BOOLEAN        NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, strategy_id),
    CONSTRAINT chk_user_strategy_signal_settings_confidence_range
        CHECK (confidence_threshold IS NULL OR confidence_threshold BETWEEN 0 AND 1)
);
