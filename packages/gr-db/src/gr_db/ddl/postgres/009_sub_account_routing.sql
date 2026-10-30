-- 策略与子账户路由；当前没有 app.live_positions，不为尚不存在的表预埋补列。
CREATE SCHEMA IF NOT EXISTS app;

-- Mapping table: strategy UUID → sub-account ID in live_account_state
CREATE TABLE IF NOT EXISTS app.strategy_sub_account_mapping (
    strategy_id     UUID         NOT NULL PRIMARY KEY,
    sub_account_id  INT          NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE app.strategy_sub_account_mapping IS
    'Maps strategy UUIDs to sub-account IDs in live_account_state.';
