-- ============================================================
-- GetRich 数据导入层 PostgreSQL 初始化 Schema
-- 用途: 参考数据与供应商标的信息，小表、高频读、支持复杂查询
-- 时区约定: TIMESTAMPTZ 以 UTC 存储，应用层 SET timezone = 'Asia/Shanghai'
-- ============================================================

CREATE SCHEMA IF NOT EXISTS re;  -- re -> ref
CREATE SCHEMA IF NOT EXISTS md;  -- md -> market_date
