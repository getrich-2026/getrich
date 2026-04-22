-- ============================================================
-- PostgreSQL 扩展
-- ============================================================
-- pgcrypto 提供 gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- pg_trgm 用于 ILIKE 搜索优化（策略名称/描述模糊搜索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;
