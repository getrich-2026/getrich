-- 后台导入作业审计表。
-- 执行前请确认当前 PostgreSQL search_path 为 frontend，且 users/strategies 表已存在。

CREATE TABLE IF NOT EXISTS import_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_code        VARCHAR(64) NOT NULL UNIQUE,
    import_type     VARCHAR(64) NOT NULL,
    strategy_id     UUID REFERENCES strategies(id),
    file_name       VARCHAR(256) NOT NULL,
    file_sha256     CHAR(64) NOT NULL,
    mode            VARCHAR(16) NOT NULL CHECK (mode IN ('upsert', 'insert_only')),
    status          VARCHAR(16) NOT NULL CHECK (status IN ('validated', 'blocked', 'committed')),
    summary         JSONB NOT NULL DEFAULT '{}',
    preview_rows    JSONB NOT NULL DEFAULT '[]',
    validated_rows  JSONB NOT NULL DEFAULT '[]',
    created_by      UUID NOT NULL REFERENCES users(id),
    committed_by    UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_jobs_created_at
    ON import_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_import_jobs_status
    ON import_jobs(status);

CREATE TABLE IF NOT EXISTS import_job_errors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    row_number      INTEGER NOT NULL,
    column_name     VARCHAR(128),
    error_code      VARCHAR(64) NOT NULL,
    message         TEXT NOT NULL,
    raw_row         JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_import_job_errors_job
    ON import_job_errors(job_id, row_number);
