CREATE TABLE articles (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id       UUID         NOT NULL REFERENCES users(id),

    title           VARCHAR(300) NOT NULL,
    summary         TEXT,
    content         TEXT         NOT NULL,
    cover_url       TEXT,

    type            VARCHAR(30)  NOT NULL,   -- knowledge|market_comment|research|weekly_review

    -- 统一访问模型（和 strategies/signals 一致）
    access_tier     SMALLINT     NOT NULL DEFAULT 0,
    delay_free_hours INT,         -- NULL=永不延迟免费; N=N小时后公开

    view_count      INT          NOT NULL DEFAULT 0,
    like_count      INT          NOT NULL DEFAULT 0,

    status          VARCHAR(20)  NOT NULL DEFAULT 'draft',
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE article_tags (
    article_id UUID     REFERENCES articles(id)  ON DELETE CASCADE,
    tag_id     SMALLINT REFERENCES tags(id)       ON DELETE CASCADE,
    PRIMARY KEY (article_id, tag_id)
);

-- ============================================================
-- 点赞
-- ============================================================
CREATE TABLE article_likes (
    user_id    UUID REFERENCES users(id)    ON DELETE CASCADE,
    article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id)
);

-- ============================================================
-- 评论（支持二级回复，不做三级）
-- ============================================================
CREATE TABLE article_comments (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID        NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    user_id    UUID        NOT NULL REFERENCES users(id),
    parent_id  UUID        REFERENCES article_comments(id), -- NULL=顶级; 有值=回复某条
    content    TEXT        NOT NULL,
    like_count INT         NOT NULL DEFAULT 0,
    status     SMALLINT    NOT NULL DEFAULT 1, -- 1正常 0用户删除 -1管理员隐藏
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 评论点赞（单独一张，区分文章点赞）
CREATE TABLE comment_likes (
    user_id    UUID REFERENCES users(id)           ON DELETE CASCADE,
    comment_id UUID REFERENCES article_comments(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, comment_id)
);