-- 风险模型数组列的形状与取值约束：非空、一维、下标从 1 起、长度与 factor_count 一致、
-- 元素非 NULL 且有限。替换 037 只比较 array_length 的旧约束：空数组的 array_length
-- 为 NULL，CHECK 遇 NULL 放行；多维数组只比第一维；NaN／±Infinity 原样入库。
--
-- PostgreSQL 的浮点相等把 NaN 视为与 NaN 相等，因此用与 {NaN, Infinity, -Infinity}
-- 的数组重叠（&&）拒绝非有限元素；NULL 元素用 array_position(..., NULL) 识别。
-- 各表行的 factor_count 与所属 model_run 一致属于跨表约束，由 gr-data 入库门禁保证。
-- 约束幂等：按 pg_constraint 判断是否已存在（沿用 045 的写法）。因此修改本文件里的
-- 表达式不会生效（重放时约束名已存在而跳过）；要改约束须新开迁移并换约束名。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_model_run_factor_order' AND conrelid = 'factor.model_run'::regclass
    ) THEN
        ALTER TABLE factor.model_run DROP CONSTRAINT IF EXISTS chk_model_run_factor_count;
        ALTER TABLE factor.model_run
            ADD CONSTRAINT chk_model_run_factor_order
            CHECK (
                factor_count > 0
                AND cardinality(factor_order) = factor_count
                AND array_ndims(factor_order) = 1
                AND array_lower(factor_order, 1) = 1
                AND array_position(factor_order, NULL) IS NULL
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_exposure_array' AND conrelid = 'factor.exposure'::regclass
    ) THEN
        ALTER TABLE factor.exposure DROP CONSTRAINT IF EXISTS chk_exposure_len;
        ALTER TABLE factor.exposure
            ADD CONSTRAINT chk_exposure_array
            CHECK (
                factor_count > 0
                AND cardinality(exposure) = factor_count
                AND array_ndims(exposure) = 1
                AND array_lower(exposure, 1) = 1
                AND array_position(exposure, NULL) IS NULL
                AND NOT (exposure && ARRAY['NaN', 'Infinity', '-Infinity']::REAL[])
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_cov_array' AND conrelid = 'factor.covariance'::regclass
    ) THEN
        ALTER TABLE factor.covariance DROP CONSTRAINT IF EXISTS chk_cov_len;
        ALTER TABLE factor.covariance
            ADD CONSTRAINT chk_cov_array
            CHECK (
                factor_count > 0
                AND cardinality(cov_flat) = factor_count * (factor_count + 1) / 2
                AND array_ndims(cov_flat) = 1
                AND array_lower(cov_flat, 1) = 1
                AND array_position(cov_flat, NULL) IS NULL
                AND NOT (cov_flat && ARRAY['NaN', 'Infinity', '-Infinity']::DOUBLE PRECISION[])
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_ret_array' AND conrelid = 'factor.factor_return'::regclass
    ) THEN
        ALTER TABLE factor.factor_return DROP CONSTRAINT IF EXISTS chk_ret_len;
        ALTER TABLE factor.factor_return
            ADD CONSTRAINT chk_ret_array
            CHECK (
                factor_count > 0
                AND cardinality(ret_vector) = factor_count
                AND array_ndims(ret_vector) = 1
                AND array_lower(ret_vector, 1) = 1
                AND array_position(ret_vector, NULL) IS NULL
                AND NOT (ret_vector && ARRAY['NaN', 'Infinity', '-Infinity']::REAL[])
            );
    END IF;
END
$$;

COMMENT ON CONSTRAINT chk_model_run_factor_order ON factor.model_run IS
    'factor_order 非空、一维、下标从 1 起、无 NULL 元素，元素数等于 factor_count（>0）。';
COMMENT ON CONSTRAINT chk_exposure_array ON factor.exposure IS
    'exposure 非空、一维、下标从 1 起，元素数等于 factor_count，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';
COMMENT ON CONSTRAINT chk_cov_array ON factor.covariance IS
    'cov_flat 为上三角展平：元素数等于 K(K+1)/2，一维、下标从 1 起，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';
COMMENT ON CONSTRAINT chk_ret_array ON factor.factor_return IS
    'ret_vector 非空、一维、下标从 1 起，元素数等于 factor_count，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';
