-- 020_signal_reads_monthly.sql
-- Per-user signal read/executed state and strategy monthly return snapshots.
--
-- Schema-qualified: the backend pool sets SET search_path=frontend;
-- services/signal.py and services/strategy.py reference these tables unprefixed.

CREATE SCHEMA IF NOT EXISTS frontend;

CREATE TABLE IF NOT EXISTS frontend.user_signal_reads (
    user_id         UUID            NOT NULL,
    signal_id       UUID            NOT NULL,
    read_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_executed     BOOLEAN         NOT NULL DEFAULT FALSE,
    executed_price  NUMERIC,
    executed_qty    INTEGER,
    executed_at     TIMESTAMPTZ,
    note            TEXT,
    PRIMARY KEY (user_id, signal_id)
);

CREATE TABLE IF NOT EXISTS frontend.strategy_monthly_returns (
    strategy_id     UUID            NOT NULL,
    year            SMALLINT        NOT NULL,
    month           SMALLINT        NOT NULL,
    monthly_return  NUMERIC         NOT NULL,
    PRIMARY KEY (strategy_id, year, month)
);

CREATE INDEX IF NOT EXISTS idx_signal_reads_user ON frontend.user_signal_reads(user_id, read_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_reads_signal ON frontend.user_signal_reads(signal_id);
CREATE INDEX IF NOT EXISTS idx_monthly_returns_strategy
    ON frontend.strategy_monthly_returns(strategy_id, year DESC, month DESC);

COMMENT ON TABLE frontend.user_signal_reads IS
    'Per-user signal read / executed state. Tracks when a user marks a signal
     as read and (optionally) records the user-side execution details.';
COMMENT ON TABLE frontend.strategy_monthly_returns IS
    'Pre-aggregated monthly return snapshots per strategy. Used for the
     monthly returns heatmap on the strategy detail page.';
