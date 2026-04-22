-- ============================================================
-- 用户侧的信号状态 & 推送配置
-- ============================================================

-- 信号已读 + 执行记录（对应前端 5.3 POST /signals/{id}/read、5.4 execute）
CREATE TABLE user_signal_reads (
    user_id         UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signal_id       UUID            NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    read_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- 执行反馈
    is_executed     BOOLEAN         NOT NULL DEFAULT FALSE,
    executed_price  NUMERIC(18,4),
    executed_qty    INT,
    executed_at     TIMESTAMPTZ,
    note            TEXT,

    PRIMARY KEY (user_id, signal_id)
);

-- 用户全局推送设置（对应前端 5.6/5.7 GET/PUT /user/signal-settings）
CREATE TABLE user_signal_settings (
    user_id              UUID           PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    push_enabled         BOOLEAN        NOT NULL DEFAULT TRUE,

    -- 推送渠道开关：{"app_push":true,"sms":false,"email":true,"wechat_service":true,"websocket":true}
    channels             JSONB          NOT NULL DEFAULT '{"app_push":true,"sms":false,"email":false,"wechat_service":false,"websocket":true}',

    -- 全局过滤规则
    confidence_threshold NUMERIC(3,2)   NOT NULL DEFAULT 0.50,
    urgency_filter       TEXT[]         NOT NULL DEFAULT ARRAY['normal','high','critical'],
    quiet_hours          JSONB          NOT NULL DEFAULT '{"enabled":false,"start":"22:00","end":"08:30"}',
    trading_hours_only   BOOLEAN        NOT NULL DEFAULT FALSE,

    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- 单策略级别的推送覆盖设置
CREATE TABLE user_strategy_signal_settings (
    user_id              UUID           NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_id          UUID           NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    push_enabled         BOOLEAN        NOT NULL DEFAULT TRUE,
    confidence_threshold NUMERIC(3,2),                      -- NULL 表示继承全局配置
    notify_entry_only    BOOLEAN        NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, strategy_id)
);
