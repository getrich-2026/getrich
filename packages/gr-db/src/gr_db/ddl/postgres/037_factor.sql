-- 037_factor.sql
-- factor schema：Barra 式风险模型的五件套 X / f / F / u / D + 三张元数据表。
-- 关闭 getrich-design `持仓诊断_表与接口设计.md` §3 的缺口 G2（前瞻协方差、风险贡献、
-- 因子归因全部依赖它）。
--
-- DDL 依据该文档 §5.2 的草案 + `data-platform/providers/datayes.md` §7.3 的
-- factor.specific_return。**四处刻意偏离草案**，逐条写在对应表上方，理由不要删。
--
-- 两条不可从 DDL 推导的约定（应用层强制，DB 管不了）：
--   1) factor_order 必须按 definition.ordinal 排序生成，且与 definition 的集合一致；
--   2) model_run 一旦写入不可 UPDATE —— 因子集合或估计方法变化必须开新 model_version。
--      「历史 run 永不覆盖」是可复现性的全部依赖，改一行就等于让过去的诊断结果无法重算。
--
-- ownership 粒度：本轮 factor.* 按**表级**登记在 ops.table_ownership（现有
-- OwnershipManager 只支持表级）。一旦要让自研估计与供应商数据同表并存，
-- 必须先把 ownership 下沉到「表 + run_id」，否则两者会互相顶掉归属。

CREATE SCHEMA IF NOT EXISTS factor;

-- 风险模型专用的配置身份、成功收据与观察检查点。
-- 当前收据仅承载米筐风险整包；不扩大为通用供应商收据。
CREATE TABLE IF NOT EXISTS factor.dataset_variant (
    variant_id VARCHAR(64) PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    dataset_name VARCHAR(96) NOT NULL,
    purpose TEXT NOT NULL,
    identity JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_dataset_variant_id CHECK (variant_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_dataset_variant_provider CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_dataset_variant_dataset CHECK (btrim(dataset_name) <> ''),
    CONSTRAINT chk_dataset_variant_purpose CHECK (purpose IN ('validation', 'production')),
    CONSTRAINT chk_dataset_variant_identity CHECK (
        jsonb_typeof(identity) = 'object'
        AND identity ? 'purpose'
        AND jsonb_typeof(identity -> 'purpose') = 'string'
        AND identity ->> 'purpose' = purpose
    ),
    CONSTRAINT chk_dataset_variant_created_at CHECK (isfinite(created_at)),
    CONSTRAINT uq_dataset_variant_source UNIQUE (variant_id, provider, dataset_name)
);

CREATE TABLE IF NOT EXISTS factor.import_receipt (
    receipt_id UUID PRIMARY KEY,
    target TEXT NOT NULL,
    variant_id VARCHAR(64) NOT NULL REFERENCES factor.dataset_variant(variant_id),
    manifest_hash VARCHAR(64) NOT NULL,
    importer_version TEXT NOT NULL,
    observation_id VARCHAR(32) NOT NULL,
    trading_day DATE NOT NULL,
    rows_written BIGINT NOT NULL,
    quality JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_import_receipt_target CHECK (target = 'factor.risk_bundle'),
    CONSTRAINT chk_import_receipt_manifest CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_import_receipt_version CHECK (btrim(importer_version) <> ''),
    CONSTRAINT chk_import_receipt_observation CHECK (observation_id ~ '^[0-9a-f]{32}$'),
    CONSTRAINT chk_import_receipt_day CHECK (isfinite(trading_day)),
    CONSTRAINT chk_import_receipt_rows CHECK (rows_written >= 0),
    CONSTRAINT chk_import_receipt_quality CHECK (jsonb_typeof(quality) = 'object'),
    CONSTRAINT chk_import_receipt_committed_at CHECK (isfinite(committed_at)),
    CONSTRAINT uq_import_receipt_replay UNIQUE (target, manifest_hash, importer_version),
    CONSTRAINT uq_import_receipt_binding UNIQUE (
        receipt_id, variant_id, observation_id, trading_day
    ),
    CONSTRAINT uq_import_receipt_capture UNIQUE (
        receipt_id, variant_id, observation_id, trading_day, manifest_hash
    )
);

CREATE TABLE IF NOT EXISTS factor.import_checkpoint (
    provider       VARCHAR(32) NOT NULL,
    dataset_name   VARCHAR(96) NOT NULL,
    partition_key  TEXT NOT NULL,
    watermark_date DATE,
    watermark_ts   TIMESTAMPTZ,
    state          JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    variant_id VARCHAR(64),
    observation_id VARCHAR(32),
    trading_day DATE,
    capture_manifest_hash VARCHAR(64),
    captured_at TIMESTAMPTZ,
    import_receipt_id UUID,
    imported_at TIMESTAMPTZ,
    PRIMARY KEY (provider, dataset_name, partition_key),
    CONSTRAINT chk_import_checkpoint_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT chk_import_checkpoint_dataset_not_blank CHECK (btrim(dataset_name) <> ''),
    CONSTRAINT chk_import_checkpoint_partition_not_blank CHECK (btrim(partition_key) <> ''),
    CONSTRAINT chk_import_checkpoint_tagged_identity
    CHECK (
            (variant_id IS NULL AND observation_id IS NULL AND trading_day IS NULL
                AND capture_manifest_hash IS NULL AND captured_at IS NULL
                AND import_receipt_id IS NULL AND imported_at IS NULL)
            OR (
                variant_id IS NOT NULL AND observation_id IS NOT NULL
                AND trading_day IS NOT NULL AND capture_manifest_hash IS NOT NULL
                AND captured_at IS NOT NULL
                AND variant_id ~ '^[0-9a-f]{64}$'
                AND observation_id ~ '^[0-9a-f]{32}$'
                AND capture_manifest_hash ~ '^[0-9a-f]{64}$'
                AND isfinite(trading_day) AND isfinite(captured_at)
                AND partition_key = variant_id || '/' || to_char(trading_day, 'YYYY-MM-DD')
                    || '/' || observation_id
                AND jsonb_typeof(state) = 'object'
                AND watermark_ts IS NULL
                AND (
                    (import_receipt_id IS NULL AND imported_at IS NULL AND watermark_date IS NULL)
                    OR (import_receipt_id IS NOT NULL AND imported_at IS NOT NULL
                        AND watermark_date IS NOT NULL AND watermark_date = trading_day
                        AND isfinite(imported_at) AND imported_at >= captured_at)
                )
            )
        ),
    CONSTRAINT fk_import_checkpoint_variant_source
    FOREIGN KEY (variant_id, provider, dataset_name)
        REFERENCES factor.dataset_variant (variant_id, provider, dataset_name),
    CONSTRAINT fk_import_checkpoint_receipt_identity
    FOREIGN KEY (import_receipt_id, variant_id, observation_id, trading_day, capture_manifest_hash)
        REFERENCES factor.import_receipt (receipt_id, variant_id, observation_id, trading_day, manifest_hash)
);

CREATE INDEX IF NOT EXISTS idx_import_checkpoint_updated_at
    ON factor.import_checkpoint (updated_at);



-- ---------------------------------------------------------------------------
-- 元数据
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor.model (
    model_id   VARCHAR(32) PRIMARY KEY,        -- 'barra_cne6' / 'inhouse_v1'
    model_name VARCHAR(64) NOT NULL,
    source     VARCHAR(32) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 因子集合与顺序的唯一真相源。ordinal 为零基业务序号，PG 数组位置为 ordinal + 1。
CREATE TABLE IF NOT EXISTS factor.definition (
    model_id    VARCHAR(32) NOT NULL REFERENCES factor.model(model_id),
    factor_code VARCHAR(32) NOT NULL,
    factor_name VARCHAR(64),
    factor_type VARCHAR(16) NOT NULL,          -- market / industry / style
    ordinal     SMALLINT NOT NULL,             -- 零基业务序号；PG 数组位置为 ordinal + 1
    PRIMARY KEY (model_id, factor_code),
    CONSTRAINT uq_definition_ordinal UNIQUE (model_id, ordinal),
    CONSTRAINT chk_definition_factor_type CHECK (factor_type IN ('market', 'industry', 'style'))
);

-- 偏离 1：新增 units JSONB。
--   草案的 annualization_basis 是单值 CHECK ∈ ('daily','annual_252')，但 CNE6 同一个
--   模型里 F/D 是年化 %²、f/u 是日频（u 还是百分比、f 是小数），一个值装不下。
--   下游若按 annualization_basis='annual_252' 去读 ret_vector，会差 √252 倍且不报错。
--   annualization_basis 保留并填 'annual_252'，语义收窄为「风险类（F/D）的口径」。
-- 偏离 2：新增 calibrated BOOLEAN。
--   量纲定标目前只有单日样本作依据（且那一天还是 sw14 期），全区间复核通过前，
--   下游必须能看出「这批数是未标定的」并把相关指标标成 degraded。
-- 偏离 3：新增 factor_set_hash。
--   factor_order_hash 是**顺序**哈希，管的是我们自己的排序规则有没有被改；
--   集合变了（供应商换体系）是另一回事，混成一个哈希就分不清该找谁。
CREATE TABLE IF NOT EXISTS factor.model_run (
    run_id              UUID PRIMARY KEY,
    model_id            VARCHAR(32) NOT NULL REFERENCES factor.model(model_id),
    model_version       VARCHAR(32) NOT NULL,  -- 观测版本；米筐填 run_id.hex，源模型见 units
    factor_order        TEXT[] NOT NULL,       -- 按 ordinal 派生，run 内不可变
    factor_count        SMALLINT NOT NULL,
    factor_order_hash   VARCHAR(32) NOT NULL,  -- MD5(顺序)，防错位
    factor_set_hash     VARCHAR(32),           -- MD5(排序后的集合)，防供应商换因子集
    annualization_basis VARCHAR(16) NOT NULL,
    units               JSONB NOT NULL DEFAULT '{}'::jsonb,
    calibrated          BOOLEAN NOT NULL DEFAULT false,
    estimated_at        TIMESTAMPTZ NOT NULL,
    code_version        VARCHAR(64),
    param_hash          VARCHAR(32),
    source              VARCHAR(32) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_model_run_factor_order CHECK (
        factor_count > 0
        AND cardinality(factor_order) = factor_count
        AND array_ndims(factor_order) = 1
        AND array_lower(factor_order, 1) = 1
        AND array_position(factor_order, NULL) IS NULL
    ),
    CONSTRAINT chk_model_run_annualization CHECK (annualization_basis IN ('daily', 'annual_252')),
    CONSTRAINT uq_model_run_version UNIQUE (model_id, model_version)
);

COMMENT ON COLUMN factor.model_run.units IS
    '各数组列的量纲，如 {"factor_return":"dec_daily","specific_return":"pct_daily","covariance":"pct2_annual","specific_risk":"pct2_annual","exposure":"zscore"}。由 providers.<source>.scaling 配置原样落库，实现「配置→库内→下游」三处口径一致。';
COMMENT ON COLUMN factor.model_run.annualization_basis IS
    '风险类（covariance / specific_risk）的年化口径。因子收益与特质收益的口径见 units，不看这一列。';
COMMENT ON COLUMN factor.model_run.calibrated IS
    'false = 量纲定标尚未经全区间复核，下游应把依赖它的指标标为 degraded。model_run 不可 UPDATE，复核通过后开新 run。';
COMMENT ON COLUMN factor.model_run.param_hash IS
    '估计参数指纹。供应商未公开 CNE6 的估计参数，取自通联时恒为 NULL —— 不得填猜测值。';

-- ---------------------------------------------------------------------------
-- X：因子载荷（标的 × 日 × K）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor.exposure (
    run_id        UUID NOT NULL REFERENCES factor.model_run(run_id),
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day   DATE NOT NULL,
    exposure      REAL[] NOT NULL,             -- 列序 = model_run.factor_order
    factor_count  SMALLINT NOT NULL,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, instrument_id, trading_day),
    CONSTRAINT chk_exposure_array CHECK (
        factor_count > 0
        AND cardinality(exposure) = factor_count
        AND array_ndims(exposure) = 1
        AND array_lower(exposure, 1) = 1
        AND array_position(exposure, NULL) IS NULL
        AND NOT (exposure && ARRAY['NaN', 'Infinity', '-Infinity']::REAL[])
    )
);
SELECT create_hypertable('factor.exposure', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON COLUMN factor.exposure.exposure IS
    '下标严格对应 model_run.factor_order。风格因子是无量纲 z-score，行业因子是 0/1 哑变量（同一标的同一天恰有一个行业为 1），COUNTRY 恒为 1。';

-- ---------------------------------------------------------------------------
-- F：因子协方差（日 × K×K 上三角）
-- ---------------------------------------------------------------------------
-- 偏离 4：cov_flat 由草案的 REAL[] 改为 DOUBLE PRECISION[]。
--   实测样本最大元素 723.695971 = 9 位有效数字，REAL 只有约 7 位，末两位小数会被
--   静默截掉。而这张表的下游是矩阵求逆与半正定判定，对精度敏感，截断后仍能算出
--   一个「看起来正常」的结果。其余数组列保持 REAL（草案的 O5「存储精度即口径」
--   仍然成立，只是协方差这一张的精度必须更高）。
CREATE TABLE IF NOT EXISTS factor.covariance (
    run_id       UUID NOT NULL REFERENCES factor.model_run(run_id),
    trading_day  DATE NOT NULL,
    cov_flat     DOUBLE PRECISION[] NOT NULL,
    factor_count SMALLINT NOT NULL,
    half_life    SMALLINT,
    window_days  SMALLINT,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, trading_day),
    CONSTRAINT chk_cov_array CHECK (
        factor_count > 0
        AND cardinality(cov_flat) = factor_count * (factor_count + 1) / 2
        AND array_ndims(cov_flat) = 1
        AND array_lower(cov_flat, 1) = 1
        AND array_position(cov_flat, NULL) IS NULL
        AND NOT (cov_flat && ARRAY['NaN', 'Infinity', '-Infinity']::DOUBLE PRECISION[])
    )
);

COMMENT ON COLUMN factor.covariance.cov_flat IS
    '对称矩阵的上三角展平，**行优先、i<=j、i 在外层**：[C00,C01,...,C0K-1,C11,...,CK-1K-1]，长度 K(K+1)/2（K=52 时 1378）。用错展开顺序还原出的矩阵依然对称、依然正定，不会报错，只是每个元素都对应错了因子对。单位：年化 %²（与 specific_risk.specific_var 同量纲，联用无需换算）。';

-- ---------------------------------------------------------------------------
-- D：特质方差对角元（标的 × 日）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor.specific_risk (
    run_id        UUID NOT NULL REFERENCES factor.model_run(run_id),
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day   DATE NOT NULL,
    specific_var  REAL NOT NULL,
    half_life     SMALLINT,
    window_days   SMALLINT,
    source        VARCHAR(32) NOT NULL,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, instrument_id, trading_day),
    -- NaN 在 PG 里 NaN >= 0 得 NULL，而 CHECK 遇 NULL 通过，所以必须显式拒 NaN 与 +Inf
    CONSTRAINT chk_specific_var_valid CHECK (
        specific_var >= 0
        AND specific_var = specific_var
        AND specific_var < 'Infinity'::REAL
    )
);
SELECT create_hypertable('factor.specific_risk', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON COLUMN factor.specific_risk.specific_var IS
    '特质**方差**（不是标准差），单位年化 %²。通联的 SRISK 字段给的是年化百分比波动率 σ，入库前平方。把 σ 当 σ² 用会让特质风险被系统性低估约一个数量级。';

-- ---------------------------------------------------------------------------
-- f：因子收益（日 × K）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor.factor_return (
    run_id       UUID NOT NULL REFERENCES factor.model_run(run_id),
    trading_day  DATE NOT NULL,
    ret_vector   REAL[] NOT NULL,              -- 长度 K，列序同 factor_order
    factor_count SMALLINT NOT NULL,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, trading_day),
    CONSTRAINT chk_ret_array CHECK (
        factor_count > 0
        AND cardinality(ret_vector) = factor_count
        AND array_ndims(ret_vector) = 1
        AND array_lower(ret_vector, 1) = 1
        AND array_position(ret_vector, NULL) IS NULL
        AND NOT (ret_vector && ARRAY['NaN', 'Infinity', '-Infinity']::REAL[])
    )
);

COMMENT ON COLUMN factor.factor_return.ret_vector IS
    '因子日收益，单位**小数**（不是百分比）。与 specific_return.specific_ret 的百分比不同量纲：还原个股收益是 r = 100 * X·f + u。';

-- ---------------------------------------------------------------------------
-- u：特质收益（标的 × 日）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS factor.specific_return (
    run_id        UUID NOT NULL REFERENCES factor.model_run(run_id),
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day   DATE NOT NULL,
    specific_ret  REAL NOT NULL,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, instrument_id, trading_day),
    CONSTRAINT chk_specific_ret_valid CHECK (
        specific_ret = specific_ret
        AND specific_ret < 'Infinity'::REAL
        AND specific_ret > '-Infinity'::REAL
    )
);
SELECT create_hypertable('factor.specific_return', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON COLUMN factor.specific_return.specific_ret IS
    '特质日收益，单位**百分比**（与 factor_return 的小数不同量纲）。用于 r = 100 * X·f + u 的五表自洽校验。';

-- 反查索引：按标的取一段时间序列是最常见的读法，而 PK 以 run_id 打头。
CREATE INDEX IF NOT EXISTS idx_exposure_instrument_day
    ON factor.exposure (instrument_id, trading_day);
CREATE INDEX IF NOT EXISTS idx_specific_risk_instrument_day
    ON factor.specific_risk (instrument_id, trading_day);
CREATE INDEX IF NOT EXISTS idx_specific_return_instrument_day
    ON factor.specific_return (instrument_id, trading_day);

COMMENT ON CONSTRAINT chk_model_run_factor_order ON factor.model_run IS
    'factor_order 非空、一维、下标从 1 起、无 NULL 元素，元素数等于 factor_count（>0）。';

COMMENT ON CONSTRAINT chk_exposure_array ON factor.exposure IS
    'exposure 非空、一维、下标从 1 起，元素数等于 factor_count，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';

COMMENT ON CONSTRAINT chk_cov_array ON factor.covariance IS
    'cov_flat 为上三角展平：元素数等于 K(K+1)/2，一维、下标从 1 起，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';

COMMENT ON CONSTRAINT chk_ret_array ON factor.factor_return IS
    'ret_vector 非空、一维、下标从 1 起，元素数等于 factor_count，元素非 NULL 且有限。factor_count 与 model_run 一致由入库门禁保证。';
