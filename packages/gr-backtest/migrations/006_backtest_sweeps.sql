-- NOTE: backend pool sets `SET search_path=frontend`; tables must live in the `frontend` schema.
CREATE SCHEMA IF NOT EXISTS frontend;

-- 006_backtest_sweeps.sql
-- PostgreSQL-backed parameter sweep persistence (P0).
-- Stores sweep metadata and per-trial linkage/summaries.
--
-- Run: psql -d getrich -f migrations/006_backtest_sweeps.sql

CREATE TABLE IF NOT EXISTS frontend.backtest_sweeps (
    sweep_id            VARCHAR(128)    PRIMARY KEY,
    search_type         VARCHAR(32)     NOT NULL DEFAULT 'grid',
    search_spec         JSONB           NOT NULL DEFAULT '{}'::jsonb,
    select_metric       VARCHAR(64)     NOT NULL,
    maximize            BOOLEAN         NOT NULL,
    status              VARCHAR(16)     NOT NULL DEFAULT 'completed',
    total_trials        INT             NOT NULL DEFAULT 0,
    completed_trials    INT             NOT NULL DEFAULT 0,
    failed_trials       INT             NOT NULL DEFAULT 0,
    best_trial_id       VARCHAR(160),
    best_run_id         VARCHAR(128),
    best_metric_value   DECIMAL(20,10),
    summary_json        JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ     NOT NULL,
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE frontend.backtest_sweeps IS
    'Parameter sweep metadata and summary. One row per completed or in-progress sweep.';
COMMENT ON COLUMN frontend.backtest_sweeps.search_spec IS
    'ParamSpace / search specification serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN frontend.backtest_sweeps.summary_json IS
    'Arbitrary summary metadata (e.g. param space dimension names, run_id prefix).';

CREATE INDEX IF NOT EXISTS idx_backtest_sweeps_created
    ON frontend.backtest_sweeps(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_sweeps_status_created
    ON frontend.backtest_sweeps(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_sweeps_best_run
    ON frontend.backtest_sweeps(best_run_id);

CREATE TABLE IF NOT EXISTS frontend.backtest_sweep_trials (
    trial_id            VARCHAR(160)    PRIMARY KEY,
    sweep_id            VARCHAR(128)    NOT NULL,
    run_id              VARCHAR(128)    NOT NULL,
    trial_index         INT             NOT NULL,
    params              JSONB           NOT NULL,
    param_fingerprint   VARCHAR(64)     NOT NULL,
    status              VARCHAR(16)     NOT NULL,
    error_message       TEXT,
    select_metric_value DECIMAL(20,10),
    metrics_json        JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (sweep_id, trial_index),
    UNIQUE (sweep_id, param_fingerprint)
);

COMMENT ON TABLE frontend.backtest_sweep_trials IS
    'Per-trial metadata linking a sweep to its parameter config, status, and metric summary.';
COMMENT ON COLUMN frontend.backtest_sweep_trials.params IS
    'Trial parameter configuration serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN frontend.backtest_sweep_trials.metrics_json IS
    'BacktestMetrics snapshot for completed trials. Decimal values encoded as strings.';
COMMENT ON COLUMN frontend.backtest_sweep_trials.select_metric_value IS
    'Denormalized value of the sweep''s select_metric for ranking/filtering.';

CREATE INDEX IF NOT EXISTS idx_backtest_sweep_trials_sweep_index
    ON frontend.backtest_sweep_trials(sweep_id, trial_index);
CREATE INDEX IF NOT EXISTS idx_backtest_sweep_trials_sweep_status
    ON frontend.backtest_sweep_trials(sweep_id, status);
CREATE INDEX IF NOT EXISTS idx_backtest_sweep_trials_run
    ON frontend.backtest_sweep_trials(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_sweep_trials_sweep_metric
    ON frontend.backtest_sweep_trials(sweep_id, select_metric_value);
