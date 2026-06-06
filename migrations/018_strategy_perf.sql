-- 018_strategy_perf.sql
-- Strategy performance snapshots and equity curve tables.
--
-- Schema-qualified: the backend pool sets SET search_path=frontend;
-- services/strategy.py references these tables unprefixed.

CREATE SCHEMA IF NOT EXISTS frontend;

CREATE TABLE IF NOT EXISTS frontend.strategy_performance_snapshot (
    strategy_id             UUID            NOT NULL,
    snapshot_date           DATE            NOT NULL,
    total_return            NUMERIC,
    annualized_return       NUMERIC,
    ytd_return              NUMERIC,
    recent_1m_return        NUMERIC,
    recent_3m_return        NUMERIC,
    recent_6m_return        NUMERIC,
    recent_1y_return        NUMERIC,
    max_drawdown            NUMERIC,
    max_drawdown_start      DATE,
    max_drawdown_end        DATE,
    max_drawdown_recovery   DATE,
    annualized_volatility   NUMERIC,
    downside_deviation      NUMERIC,
    sharpe_ratio            NUMERIC,
    sortino_ratio           NUMERIC,
    calmar_ratio            NUMERIC,
    information_ratio       NUMERIC,
    total_trades            INTEGER,
    win_rate                NUMERIC,
    profit_factor           NUMERIC,
    avg_win                 NUMERIC,
    avg_loss                NUMERIC,
    max_consecutive_wins    INTEGER,
    max_consecutive_losses  INTEGER,
    avg_holding_days        NUMERIC,
    var_95                  NUMERIC,
    cvar_95                 NUMERIC,
    beta                    NUMERIC,
    alpha                   NUMERIC,
    PRIMARY KEY (strategy_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS frontend.strategy_equity_curve (
    strategy_id         UUID            NOT NULL,
    trade_date          DATE            NOT NULL,
    nav                 NUMERIC         NOT NULL,
    cumulative_return   NUMERIC,
    daily_return        NUMERIC,
    drawdown            NUMERIC,
    benchmark_nav       NUMERIC,
    position_ratio      NUMERIC,
    PRIMARY KEY (strategy_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_equity_curve_strategy_date
    ON frontend.strategy_equity_curve(strategy_id, trade_date DESC);

COMMENT ON TABLE frontend.strategy_performance_snapshot IS
    'Periodic performance snapshots for strategies — one row per strategy per date.';
COMMENT ON TABLE frontend.strategy_equity_curve IS
    'Daily equity curve data for strategies — one row per strategy per trading day.';
