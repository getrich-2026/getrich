-- 002_strategy_trades.sql
-- Strategy-level trade journal — one row per executed fill.
-- Populated from live signal execution and (future) backtest fill import.
--
-- Run: psql -d getrich -f migrations/002_strategy_trades.sql
--
-- Schema-qualified for the same reason as 003/004: the backend pool sets
-- `SET search_path=app,...`；services/strategy.py 用不带前缀的 `strategy_trades`，故本表放 `app`。

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.strategy_trades (
    id              VARCHAR(64)     PRIMARY KEY,        -- UUID v4
    strategy_id     VARCHAR(64)     NOT NULL,           -- FK to strategies.id
    signal_id       VARCHAR(64),                        -- nullable FK to signals.id (null for backtest fills)
    symbol          VARCHAR(32)     NOT NULL,
    action          VARCHAR(8)      NOT NULL,           -- 'buy' | 'sell'
    quantity        DECIMAL(20,8)   NOT NULL,           -- executed qty
    price           DECIMAL(16,4)   NOT NULL,           -- fill price
    notional        DECIMAL(20,4)   NOT NULL,           -- price * quantity
    fee             DECIMAL(20,4)   NOT NULL DEFAULT 0, -- commission + tax
    slippage        DECIMAL(16,6)   NOT NULL DEFAULT 0, -- fill_price - trigger_price
    avg_cost        DECIMAL(16,4),                      -- avg cost before this fill (null on open)
    realized_pnl    DECIMAL(20,4)   NOT NULL DEFAULT 0, -- PnL on this fill (0 for buys)
    cumulative_pnl  DECIMAL(20,4),                      -- cumulative PnL up to this trade
    executed_at     TIMESTAMPTZ     NOT NULL,           -- fill timestamp
    bar_dt          TIMESTAMPTZ,                        -- bar period (backtest fills)
    tag             VARCHAR(128),                       -- free-form tag / note
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE app.strategy_trades IS
    'Strategy-level trade journal. One row per fill. Populated from live signal execution.';

-- Core indexes for list_trades() query patterns
CREATE INDEX IF NOT EXISTS idx_strategy_trades_strategy
    ON app.strategy_trades(strategy_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_trades_signal
    ON app.strategy_trades(signal_id);
