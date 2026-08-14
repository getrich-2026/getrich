-- NOTE: backend pool sets `SET search_path=frontend`; tables must live in the `frontend` schema.
CREATE SCHEMA IF NOT EXISTS frontend;

-- 005_backtest_results.sql
-- PostgreSQL-backed backtest run/result persistence (P0).
-- Stores run metadata, metrics, chartable equity points, final positions, and artifact references.
--
-- Run: psql -d getrich -f migrations/005_backtest_results.sql

CREATE TABLE IF NOT EXISTS frontend.backtest_runs (
    run_id                  VARCHAR(128)    PRIMARY KEY,
    strategy_id             VARCHAR(64),
    strategy_name           VARCHAR(255)    NOT NULL,
    strategy_names          JSONB           NOT NULL DEFAULT '[]'::jsonb,
    config_fingerprint      VARCHAR(64)     NOT NULL,
    config                  JSONB           NOT NULL,
    symbols                 JSONB           NOT NULL,
    freq                    VARCHAR(16)     NOT NULL,
    start_at                TIMESTAMPTZ     NOT NULL,
    end_at                  TIMESTAMPTZ     NOT NULL,
    initial_cash            DECIMAL(20,4)   NOT NULL,
    final_cash              DECIMAL(20,4),
    final_equity            DECIMAL(20,4),
    benchmark_final_equity  DECIMAL(20,4),
    status                  VARCHAR(16)     NOT NULL DEFAULT 'completed',
    error_message           TEXT,
    created_at              TIMESTAMPTZ     NOT NULL,
    completed_at            TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE frontend.backtest_runs IS
    'Backtest run metadata and summary. One row per submitted/completed run.';
COMMENT ON COLUMN frontend.backtest_runs.config IS
    'Immutable RunConfig snapshot serialized as JSONB. Decimal values are encoded as strings.';
COMMENT ON COLUMN frontend.backtest_runs.config_fingerprint IS
    'Deterministic RunConfig fingerprint excluding run_id and created_at.';

CREATE INDEX IF NOT EXISTS idx_backtest_runs_created
    ON frontend.backtest_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_created
    ON frontend.backtest_runs(strategy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_fingerprint
    ON frontend.backtest_runs(config_fingerprint);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status_created
    ON frontend.backtest_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS frontend.backtest_metrics (
    run_id                  VARCHAR(128)    PRIMARY KEY,
    total_return            DECIMAL(20,10),
    log_return              DECIMAL(20,10),
    annualized_return       DECIMAL(20,10),
    annualized_volatility   DECIMAL(20,10),
    sharpe_ratio            DECIMAL(20,10),
    sortino_ratio           DECIMAL(20,10),
    calmar_ratio            DECIMAL(20,10),
    max_drawdown            DECIMAL(20,10),
    max_drawdown_duration   INT,
    total_fees              DECIMAL(20,4),
    total_turnover          DECIMAL(20,4),
    turnover_rate           DECIMAL(20,10),
    total_trades            INT,
    n_bars                  INT,
    risk_free_rate          DECIMAL(20,10),
    trading_days_per_year   INT,
    metrics_json            JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE frontend.backtest_metrics IS
    'Typed and JSONB performance metrics for completed backtest runs.';

CREATE TABLE IF NOT EXISTS frontend.backtest_equity_points (
    run_id          VARCHAR(128)    NOT NULL,
    strategy_name   VARCHAR(255)    NOT NULL DEFAULT '_combined',
    dt              TIMESTAMPTZ     NOT NULL,
    cash            DECIMAL(20,4),
    equity          DECIMAL(20,4)   NOT NULL,
    trading_pnl     DECIMAL(20,4),
    mtm_pnl         DECIMAL(20,4),
    total_fees      DECIMAL(20,4),
    gross_exposure  DECIMAL(20,4),
    row_json        JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, strategy_name, dt)
);

COMMENT ON TABLE frontend.backtest_equity_points IS
    'Chartable equity time series points persisted from BacktestResult.equity_curve.';
COMMENT ON COLUMN frontend.backtest_equity_points.row_json IS
    'Additional equity columns not promoted to typed columns.';

CREATE INDEX IF NOT EXISTS idx_backtest_equity_points_run_dt
    ON frontend.backtest_equity_points(run_id, dt);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_points_run_strategy_dt
    ON frontend.backtest_equity_points(run_id, strategy_name, dt);

CREATE TABLE IF NOT EXISTS frontend.backtest_final_positions (
    run_id          VARCHAR(128)    NOT NULL,
    symbol          VARCHAR(32)     NOT NULL,
    qty             DECIMAL(20,8)   NOT NULL,
    position_json   JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, symbol)
);

COMMENT ON TABLE frontend.backtest_final_positions IS
    'Final account position snapshot for a completed backtest run.';

CREATE TABLE IF NOT EXISTS frontend.backtest_artifacts (
    id              VARCHAR(64)     PRIMARY KEY,
    run_id          VARCHAR(128)    NOT NULL,
    artifact_type   VARCHAR(32)     NOT NULL,
    uri             TEXT            NOT NULL,
    checksum        VARCHAR(128),
    meta            JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE frontend.backtest_artifacts IS
    'References to filesystem/object-store artifacts generated for backtest runs.';

CREATE INDEX IF NOT EXISTS idx_backtest_artifacts_run
    ON frontend.backtest_artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_artifacts_run_type
    ON frontend.backtest_artifacts(run_id, artifact_type);
