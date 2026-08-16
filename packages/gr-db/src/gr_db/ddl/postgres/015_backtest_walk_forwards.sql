-- NOTE: backend pool sets `SET search_path=app,market,meta,public`; 本文件的表全部放 `backtest` schema，SQL 里显式写 `backtest.` 前缀。
CREATE SCHEMA IF NOT EXISTS backtest;

-- 007_backtest_walk_forwards.sql
-- PostgreSQL-backed walk-forward study persistence (P0).
-- Stores walk-forward metadata and per-window train/validation linkage/summaries.
--
-- Run: psql -d getrich -f migrations/007_backtest_walk_forwards.sql

CREATE TABLE IF NOT EXISTS backtest.backtest_walk_forwards (
    walk_forward_id         VARCHAR(128)    PRIMARY KEY,
    search_type             VARCHAR(32)     NOT NULL DEFAULT 'grid',
    search_spec             JSONB           NOT NULL DEFAULT '{}'::jsonb,
    select_metric           VARCHAR(64)     NOT NULL,
    maximize                BOOLEAN         NOT NULL,
    refit                   VARCHAR(16)     NOT NULL,
    status                  VARCHAR(16)     NOT NULL DEFAULT 'completed',
    total_windows           INT             NOT NULL DEFAULT 0,
    completed_windows       INT             NOT NULL DEFAULT 0,
    failed_windows          INT             NOT NULL DEFAULT 0,
    mean_validation_metric  DECIMAL(20,10),
    summary_json            JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ     NOT NULL,
    completed_at            TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE backtest.backtest_walk_forwards IS
    'Walk-forward study metadata and summary. One row per persisted walk-forward run.';
COMMENT ON COLUMN backtest.backtest_walk_forwards.search_spec IS
    'Search specification serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN backtest.backtest_walk_forwards.summary_json IS
    'WalkForwardResult summary snapshot. Decimal values encoded as strings.';

CREATE INDEX IF NOT EXISTS idx_backtest_walk_forwards_created
    ON backtest.backtest_walk_forwards(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_walk_forwards_status_created
    ON backtest.backtest_walk_forwards(status, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest.backtest_walk_forward_windows (
    walk_forward_id          VARCHAR(128)    NOT NULL,
    window_index             INT             NOT NULL,
    train_start              TIMESTAMPTZ     NOT NULL,
    train_end                TIMESTAMPTZ     NOT NULL,
    val_start                TIMESTAMPTZ     NOT NULL,
    val_end                  TIMESTAMPTZ     NOT NULL,
    status                   VARCHAR(16)     NOT NULL,
    error_message            TEXT,
    train_sweep_id           VARCHAR(128),
    best_trial_id            VARCHAR(160),
    best_run_id              VARCHAR(128),
    validation_run_id        VARCHAR(128),
    best_params              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    train_metric_value       DECIMAL(20,10),
    validation_metric_value  DECIMAL(20,10),
    validation_metrics_json  JSONB           NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at             TIMESTAMPTZ,
    updated_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (walk_forward_id, window_index)
);

COMMENT ON TABLE backtest.backtest_walk_forward_windows IS
    'Per-window walk-forward train sweep and validation run linkage/summaries.';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.best_params IS
    'Selected best train parameters serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.validation_metrics_json IS
    'BacktestMetrics snapshot for the validation run. Decimal values encoded as strings.';

CREATE INDEX IF NOT EXISTS idx_backtest_walk_forward_windows_walk_index
    ON backtest.backtest_walk_forward_windows(walk_forward_id, window_index);
CREATE INDEX IF NOT EXISTS idx_backtest_walk_forward_windows_walk_status
    ON backtest.backtest_walk_forward_windows(walk_forward_id, status);
CREATE INDEX IF NOT EXISTS idx_backtest_walk_forward_windows_train_sweep
    ON backtest.backtest_walk_forward_windows(train_sweep_id);
CREATE INDEX IF NOT EXISTS idx_backtest_walk_forward_windows_validation_run
    ON backtest.backtest_walk_forward_windows(validation_run_id);
