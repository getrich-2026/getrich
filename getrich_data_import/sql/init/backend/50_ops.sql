-- Operations, audit, and quality metadata.

CREATE TABLE IF NOT EXISTS ops.users (
    user_id    BIGSERIAL PRIMARY KEY,
    username   VARCHAR(64) UNIQUE NOT NULL,
    role       VARCHAR(16) NOT NULL DEFAULT 'reader',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_users_role CHECK (role IN ('reader', 'writer', 'admin'))
);

CREATE TABLE IF NOT EXISTS ops.api_keys (
    key_id       BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES ops.users(user_id) ON DELETE CASCADE,
    api_key_hash VARCHAR(128) UNIQUE NOT NULL,
    scopes       TEXT[],
    rate_limit   INT NOT NULL DEFAULT 600,
    expires_at   TIMESTAMPTZ,
    revoked      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.etl_job_run (
    run_id       BIGSERIAL PRIMARY KEY,
    job_name     VARCHAR(64) NOT NULL,
    provider     VARCHAR(32),
    dataset_name VARCHAR(96),
    trading_day  DATE,
    start_date   DATE,
    end_date     DATE,
    asset        VARCHAR(16),
    freq         VARCHAR(8),
    status       VARCHAR(16) NOT NULL,
    rows_written BIGINT NOT NULL DEFAULT 0,
    warning_count INT NOT NULL DEFAULT 0,
    request      JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint   JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    error        TEXT,
    CONSTRAINT chk_etl_job_status CHECK (status IN ('running', 'success', 'failed', 'partial')),
    CONSTRAINT chk_etl_job_date_range CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date),
    CONSTRAINT chk_etl_job_warning_count CHECK (warning_count >= 0),
    CONSTRAINT chk_etl_job_run_timestamps
        CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

ALTER TABLE ops.etl_job_run
    ADD COLUMN IF NOT EXISTS provider VARCHAR(32),
    ADD COLUMN IF NOT EXISTS dataset_name VARCHAR(96),
    ADD COLUMN IF NOT EXISTS start_date DATE,
    ADD COLUMN IF NOT EXISTS end_date DATE,
    ADD COLUMN IF NOT EXISTS warning_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS request JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_etl_job_date_range'
          AND conrelid = 'ops.etl_job_run'::regclass
    ) THEN
        ALTER TABLE ops.etl_job_run
            ADD CONSTRAINT chk_etl_job_date_range
            CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_etl_job_warning_count'
          AND conrelid = 'ops.etl_job_run'::regclass
    ) THEN
        ALTER TABLE ops.etl_job_run
            ADD CONSTRAINT chk_etl_job_warning_count
            CHECK (warning_count >= 0);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id
    ON ops.api_keys (user_id);

CREATE INDEX IF NOT EXISTS idx_etl_job_run_lookup
    ON ops.etl_job_run (job_name, trading_day, status);

CREATE INDEX IF NOT EXISTS idx_etl_job_run_dataset
    ON ops.etl_job_run (provider, dataset_name, start_date, end_date, status);

CREATE TABLE IF NOT EXISTS ops.data_quality_check (
    check_id   BIGSERIAL PRIMARY KEY,
    run_id     BIGINT REFERENCES ops.etl_job_run(run_id),
    rule       VARCHAR(64) NOT NULL,
    severity   VARCHAR(8) NOT NULL,
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_quality_severity CHECK (severity IN ('info', 'warn', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_quality_run_severity
    ON ops.data_quality_check (run_id, severity);

CREATE INDEX IF NOT EXISTS idx_quality_check_detail
    ON ops.data_quality_check USING gin (detail);

CREATE TABLE IF NOT EXISTS ops.schema_migrations (
    file_name  TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
