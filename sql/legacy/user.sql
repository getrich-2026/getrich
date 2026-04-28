-- 用户主表
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50) UNIQUE,
    display_name    VARCHAR(100),
    avatar_url      TEXT,
    bio             TEXT,
    status          SMALLINT NOT NULL DEFAULT 1,  -- 1正常 2封禁 3注销
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 认证方式表（一个用户可绑定多种）
CREATE TABLE user_auth (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_type       VARCHAR(20) NOT NULL,  -- 'phone' | 'email' | 'wechat' | 'apple'
    identifier      VARCHAR(255) NOT NULL, -- 手机号 / 邮箱 / openid
    credential      TEXT,                  -- 密码hash，OAuth不填
    verified        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (auth_type, identifier)
);

-- 验证码表（手机/邮箱）
CREATE TABLE verification_codes (
    id              BIGSERIAL PRIMARY KEY,
    target          VARCHAR(255) NOT NULL,  -- 手机号或邮箱
    code            VARCHAR(10) NOT NULL,
    purpose         VARCHAR(30) NOT NULL,   -- 'login' | 'register' | 'bind' | 'reset_pwd'
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 微信专用扩展（存储 unionid / session_key 等）
CREATE TABLE user_wechat (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    openid          VARCHAR(100) UNIQUE NOT NULL,
    unionid         VARCHAR(100) UNIQUE,
    nickname        VARCHAR(100),
    avatar_url      TEXT,
    session_key     TEXT,
    refreshed_at    TIMESTAMPTZ
);

-- 登录会话 / Token
CREATE TABLE user_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_info     JSONB,      -- UA、设备型号等
    ip_address      INET,
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);