-- ============================================================
-- 用户模块
-- ============================================================

-- 用户主表
CREATE TABLE frontend.users (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50)     UNIQUE,
    display_name    VARCHAR(100),
    avatar_url      TEXT,
    bio             TEXT,
    status          SMALLINT        NOT NULL DEFAULT 1,     -- 1正常 2封禁 3注销
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 认证方式（一个用户可以绑定多种登录方式）
CREATE TABLE frontend.user_auth (
    id              BIGSERIAL       PRIMARY KEY,
    user_id         UUID            NOT NULL REFERENCES frontend.users(id) ON DELETE CASCADE,
    auth_type       VARCHAR(20)     NOT NULL,               -- phone|email|wechat|apple
    identifier      VARCHAR(255)    NOT NULL,               -- 手机号 / 邮箱 / openid
    credential      TEXT,                                   -- 密码 hash，OAuth 不填
    verified        BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (auth_type, identifier)
);

-- 验证码（手机/邮箱）
CREATE TABLE frontend.verification_codes (
    id              BIGSERIAL       PRIMARY KEY,
    target          VARCHAR(255)    NOT NULL,               -- 手机号或邮箱
    code            VARCHAR(10)     NOT NULL,
    purpose         VARCHAR(30)     NOT NULL,               -- login|register|bind|reset_pwd
    expires_at      TIMESTAMPTZ     NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 微信信息扩展
CREATE TABLE frontend.user_wechat (
    user_id         UUID            PRIMARY KEY REFERENCES frontend.users(id) ON DELETE CASCADE,
    openid          VARCHAR(100)    UNIQUE NOT NULL,
    unionid         VARCHAR(100)    UNIQUE,
    nickname        VARCHAR(100),
    avatar_url      TEXT,
    session_key     TEXT,
    refreshed_at    TIMESTAMPTZ
);

-- 登录会话
CREATE TABLE frontend.user_sessions (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL REFERENCES frontend.users(id) ON DELETE CASCADE,
    device_info     JSONB,
    ip_address      INET,
    expires_at      TIMESTAMPTZ     NOT NULL,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
