-- NOTE: backend pool sets `SET search_path=app,market,meta,public`; 本文件的表全部放 `backtest` schema，SQL 里显式写 `backtest.` 前缀。
CREATE SCHEMA IF NOT EXISTS backtest;

-- 008_backtest_jobs.sql
-- PostgreSQL-backed backtest job tracking (P0).
-- Stores lifecycle metadata for backtest / sweep / walk_forward tasks executed by
-- the BacktestJobRunner. ClickHouse/DuckDB are intentionally not used here.
--
-- Run: psql -d getrich -f migrations/008_backtest_jobs.sql

CREATE TABLE IF NOT EXISTS backtest.backtest_jobs (
    job_id          VARCHAR(64)     PRIMARY KEY,
    job_type        VARCHAR(16)     NOT NULL,
    ref_id          VARCHAR(128)    NOT NULL,
    status          VARCHAR(16)     NOT NULL DEFAULT 'queued',
    request_json    JSONB           NOT NULL DEFAULT '{}'::jsonb,
    progress        INT             NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    attempt INT NOT NULL DEFAULT 1,
    max_attempts INT NOT NULL DEFAULT 1,
    next_retry_at TIMESTAMPTZ,
    user_id TEXT,
    retry_base_seconds NUMERIC,
    retry_cap_seconds NUMERIC,
    retry_jitter_pct NUMERIC,
    request_hash CHAR(64)
);

COMMENT ON TABLE backtest.backtest_jobs IS
    'Lifecycle tracker for long-running backtest / sweep / walk_forward jobs.';
COMMENT ON COLUMN backtest.backtest_jobs.job_type IS
    'Job category: backtest | sweep | walk_forward.';
COMMENT ON COLUMN backtest.backtest_jobs.ref_id IS
    'Associated run_id / sweep_id / walk_forward_id produced by the job.';
COMMENT ON COLUMN backtest.backtest_jobs.status IS
    'Lifecycle status: queued | running | completed | failed | cancelled.';
COMMENT ON COLUMN backtest.backtest_jobs.request_json IS
    'Immutable request snapshot serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN backtest.backtest_jobs.progress IS
    'Coarse-grained progress 0-100 reported by the runner.';

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status_created
    ON backtest.backtest_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_type_status
    ON backtest.backtest_jobs(job_type, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_ref
    ON backtest.backtest_jobs(job_type, ref_id);

CREATE INDEX IF NOT EXISTS ix_backtest_jobs_user_id
    ON backtest.backtest_jobs (user_id) WHERE user_id IS NOT NULL;
COMMENT ON COLUMN backtest.backtest_jobs.user_id IS '回测归属用户标识；NULL 表示无归属或系统任务，不由本字段创建外键。';

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_claim
    ON backtest.backtest_jobs(job_type, status, next_retry_at NULLS FIRST, created_at)
    WHERE status = 'queued';

COMMENT ON COLUMN backtest.backtest_jobs.attempt IS
    '当前尝试次数，从 1 开始；每次重试递增。';

COMMENT ON COLUMN backtest.backtest_jobs.max_attempts IS
    '最大尝试次数；默认 1 表示不重试。';

COMMENT ON COLUMN backtest.backtest_jobs.next_retry_at IS
    '可重试失败后的最早领取时间；NULL 表示没有额外的退避等待。';

COMMENT ON COLUMN backtest.backtest_jobs.retry_base_seconds IS
    '任务级重试基础间隔，单位秒；NULL 使用 runner 默认值。';

COMMENT ON COLUMN backtest.backtest_jobs.retry_cap_seconds IS
    '任务级重试间隔上限，单位秒；NULL 使用 runner 默认值。';

COMMENT ON COLUMN backtest.backtest_jobs.retry_jitter_pct IS
    '任务级重试抖动比例，范围 [0,1)；NULL 使用 runner 默认值。';

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_idemkey_hash
    ON backtest.backtest_jobs (
        (request_json->>'_idempotency_key'),
        request_hash
    )
    WHERE request_json->>'_idempotency_key' IS NOT NULL;

COMMENT ON COLUMN backtest.backtest_jobs.request_hash IS
    '规范请求体的 SHA-256 十六进制摘要，排除服务端幂等键与旧 _user_id；NULL 表示无摘要，服务按兼容分支处理。';
