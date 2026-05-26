-- ============================================================
-- 统一标签（策略/文章共用）
-- ============================================================
CREATE TABLE tags (
    id      SMALLSERIAL  PRIMARY KEY,
    slug    VARCHAR(50)  NOT NULL UNIQUE,  -- 'a-shares' 'momentum' 'macro'
    name    VARCHAR(50)  NOT NULL,
    group   VARCHAR(30)  NOT NULL          -- 'asset_class'|'strategy_type'|'market'|'topic'
);