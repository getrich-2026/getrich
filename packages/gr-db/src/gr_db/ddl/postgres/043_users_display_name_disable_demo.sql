-- app.users 补 display_name 列，并停用 011 写入的公开演示账号。
--
-- 1) gr_api/routers/auth.py 的登录与刷新令牌查询读取
--    COALESCE(u.display_name, u.name, '')，但 011 建表时没有该列，全新库上
--    两个接口都报 UndefinedColumn（与 D-006 同类：代码依赖的列未进 DDL）。
--    列可空：为空时由查询回落到 name，不需要回填。
--
-- 2) 011 的 demo@getrich.io 口令是公开的字面量 "password"，仓库公开即口令公开。
--    只停用、不删除：保留可能被其他表引用的用户 ID。按 email + 011 原始哈希匹配，
--    已改过口令的账号视为有意保留，不受影响；条件含 is_active，重放不会重复写。
--    登录与刷新令牌都要求 is_active = TRUE，停用后该账号无法登录。

ALTER TABLE app.users ADD COLUMN IF NOT EXISTS display_name VARCHAR(128);

COMMENT ON COLUMN app.users.display_name IS
    '用户展示名；为空时接口回落到 name。';

UPDATE app.users
   SET is_active = FALSE,
       updated_at = NOW()
 WHERE email = 'demo@getrich.io'
   AND password = '$2b$12$c3lZxMMPPPn40Pg104gng.47ED584SS/eWbayiO7NoBLKtjKXUamK'
   AND is_active;
