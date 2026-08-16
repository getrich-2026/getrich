-- 017_signal_settings.sql
-- User signal notification settings tables.
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- services/signal_settings.py references these tables unprefixed.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.user_signal_settings (
    user_id             UUID            PRIMARY KEY,
    push_enabled        BOOLEAN         NOT NULL DEFAULT TRUE,
    channels            JSONB           NOT NULL DEFAULT '{"sms": false, "email": false, "app_push": true, "websocket": true, "wechat_service": false}',
    confidence_threshold NUMERIC        NOT NULL DEFAULT 0.50,
    urgency_filter      TEXT[]          NOT NULL DEFAULT ARRAY['normal', 'high', 'critical'],
    quiet_hours         JSONB           NOT NULL DEFAULT '{"end": "08:30", "start": "22:00", "enabled": false}',
    trading_hours_only  BOOLEAN         NOT NULL DEFAULT FALSE,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.user_strategy_signal_settings (
    user_id                 UUID            NOT NULL,
    strategy_id             UUID            NOT NULL,
    push_enabled            BOOLEAN         NOT NULL DEFAULT TRUE,
    confidence_threshold    NUMERIC,
    notify_entry_only       BOOLEAN         NOT NULL DEFAULT FALSE,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, strategy_id)
);

COMMENT ON TABLE app.user_signal_settings IS
    'Per-user global signal notification preferences.';
COMMENT ON TABLE app.user_strategy_signal_settings IS
    'Per-user per-strategy signal notification overrides.';
