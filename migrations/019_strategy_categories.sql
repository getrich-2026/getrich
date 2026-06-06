-- 019_strategy_categories.sql
-- Strategy category and tag tables.
--
-- Schema-qualified: the backend pool sets SET search_path=frontend;
-- services/strategy.py JOINs against these tables unprefixed.

CREATE SCHEMA IF NOT EXISTS frontend;

CREATE TABLE IF NOT EXISTS frontend.strategy_categories (
    id              VARCHAR(64)     PRIMARY KEY,
    name            VARCHAR(255)    NOT NULL,
    description     VARCHAR(512),
    icon_url        TEXT,
    sort_order      INTEGER         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS frontend.tags (
    id              SMALLSERIAL     PRIMARY KEY,
    slug            VARCHAR(64)     NOT NULL UNIQUE,
    name            VARCHAR(128)    NOT NULL,
    tag_group       VARCHAR(64)     NOT NULL
);

CREATE TABLE IF NOT EXISTS frontend.strategy_tags (
    strategy_id     UUID            NOT NULL,
    tag_id          SMALLINT        NOT NULL REFERENCES frontend.tags(id),
    PRIMARY KEY (strategy_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_tags_tag ON frontend.strategy_tags(tag_id);

COMMENT ON TABLE frontend.strategy_categories IS
    'Top-level strategy category buckets (CTA, Long-Only, etc.).';
COMMENT ON TABLE frontend.tags IS
    'Tag dictionary (strategy, market, asset-class tags).';
COMMENT ON TABLE frontend.strategy_tags IS
    'Many-to-many join between strategies and tags.';
