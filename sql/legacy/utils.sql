CREATE TABLE tools (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(100) UNIQUE NOT NULL,   -- 'margin-calculator' 'stock-screener'
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    type        VARCHAR(30),   -- calculator|screener|backtest|scanner|chart
    config      JSONB,         -- 工具的默认参数/配置
    access_tier SMALLINT     NOT NULL DEFAULT 0,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 工具使用日志（限流 + 分析）
CREATE TABLE tool_usage_logs (
    id         BIGSERIAL   PRIMARY KEY,
    tool_id    UUID        NOT NULL REFERENCES tools(id),
    user_id    UUID        REFERENCES users(id),
    params     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);