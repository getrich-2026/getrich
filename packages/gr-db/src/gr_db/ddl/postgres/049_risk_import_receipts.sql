-- 风险样本导入证据：variant → capture checkpoint → receipt → model_run binding。
-- 仅登记身份和成功导入，不创建 generation、当前指针、B2 发布或正式读取入口。
CREATE TABLE IF NOT EXISTS ops.dataset_variant (
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

CREATE TABLE IF NOT EXISTS ops.import_receipt (
    receipt_id UUID PRIMARY KEY,
    target TEXT NOT NULL,
    variant_id VARCHAR(64) NOT NULL REFERENCES ops.dataset_variant(variant_id),
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

CREATE TABLE IF NOT EXISTS factor.model_run_binding (
    run_id UUID PRIMARY KEY REFERENCES factor.model_run(run_id),
    receipt_id UUID NOT NULL,
    variant_id VARCHAR(64) NOT NULL,
    observation_id VARCHAR(32) NOT NULL,
    trading_day DATE NOT NULL,
    CONSTRAINT uq_model_run_binding_receipt UNIQUE (receipt_id),
    CONSTRAINT fk_model_run_binding_receipt FOREIGN KEY (
        receipt_id, variant_id, observation_id, trading_day
    ) REFERENCES ops.import_receipt (
        receipt_id, variant_id, observation_id, trading_day
    )
);

ALTER TABLE ops.import_checkpoint
    ADD COLUMN IF NOT EXISTS variant_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS observation_id VARCHAR(32),
    ADD COLUMN IF NOT EXISTS trading_day DATE,
    ADD COLUMN IF NOT EXISTS capture_manifest_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS import_receipt_id UUID,
    ADD COLUMN IF NOT EXISTS imported_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_import_checkpoint_tagged_identity'
            AND conrelid = 'ops.import_checkpoint'::regclass
    ) THEN
        ALTER TABLE ops.import_checkpoint ADD CONSTRAINT chk_import_checkpoint_tagged_identity
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
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_import_checkpoint_variant_source'
            AND conrelid = 'ops.import_checkpoint'::regclass
    ) THEN
        ALTER TABLE ops.import_checkpoint ADD CONSTRAINT fk_import_checkpoint_variant_source
        FOREIGN KEY (variant_id, provider, dataset_name)
        REFERENCES ops.dataset_variant (variant_id, provider, dataset_name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_import_checkpoint_receipt_identity'
            AND conrelid = 'ops.import_checkpoint'::regclass
    ) THEN
        ALTER TABLE ops.import_checkpoint ADD CONSTRAINT fk_import_checkpoint_receipt_identity
        FOREIGN KEY (import_receipt_id, variant_id, observation_id, trading_day, capture_manifest_hash)
        REFERENCES ops.import_receipt (receipt_id, variant_id, observation_id, trading_day, manifest_hash);
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION ops.reject_immutable_risk_evidence()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Immutable risk evidence rejects %', TG_OP USING ERRCODE = '23514';
END
$$;

CREATE OR REPLACE TRIGGER trg_dataset_variant_immutable
    BEFORE UPDATE OR DELETE ON ops.dataset_variant
    FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_risk_evidence();
CREATE OR REPLACE TRIGGER trg_import_receipt_immutable
    BEFORE UPDATE OR DELETE ON ops.import_receipt
    FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_risk_evidence();
CREATE OR REPLACE TRIGGER trg_model_run_binding_immutable
    BEFORE UPDATE OR DELETE ON factor.model_run_binding
    FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_risk_evidence();

CREATE OR REPLACE FUNCTION ops.validate_risk_model_run_binding()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    run_record factor.model_run%ROWTYPE;
    evidence RECORD;
BEGIN
    -- 与 model_run 元数据更新互斥；不能在核对后、绑定前并发改写用途。
    SELECT * INTO run_record FROM factor.model_run WHERE run_id = NEW.run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Risk binding requires an existing model_run' USING ERRCODE = '23514';
    END IF;
    SELECT r.target, v.provider, v.dataset_name, v.purpose, v.identity INTO evidence
    FROM ops.import_receipt r JOIN ops.dataset_variant v ON v.variant_id = r.variant_id
    WHERE r.receipt_id = NEW.receipt_id AND r.variant_id = NEW.variant_id
        AND r.observation_id = NEW.observation_id AND r.trading_day = NEW.trading_day;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Risk binding receipt identity mismatch' USING ERRCODE = '23514';
    END IF;
    IF evidence.target <> 'factor.risk_bundle'
        OR evidence.provider <> 'ricequant' OR evidence.dataset_name <> 'rq_risk_model'
        OR run_record.source IS DISTINCT FROM evidence.provider
        OR run_record.units ->> 'variant_id' IS DISTINCT FROM NEW.variant_id
        OR run_record.units ->> 'observation_id' IS DISTINCT FROM NEW.observation_id
        OR run_record.units ->> 'trading_day' IS DISTINCT FROM to_char(NEW.trading_day, 'YYYY-MM-DD')
        OR run_record.units ->> 'purpose' IS DISTINCT FROM evidence.purpose
        OR NOT (evidence.identity ?& ARRAY['model', 'industry_mapping'])
        OR jsonb_typeof(evidence.identity -> 'model') IS DISTINCT FROM 'string'
        OR jsonb_typeof(evidence.identity -> 'industry_mapping') IS DISTINCT FROM 'string'
        OR run_record.units ->> 'model' IS DISTINCT FROM evidence.identity ->> 'model'
        OR run_record.units ->> 'industry_mapping' IS DISTINCT FROM evidence.identity ->> 'industry_mapping'
    THEN
        RAISE EXCEPTION 'Risk binding model_run metadata mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER trg_model_run_binding_validate
    BEFORE INSERT ON factor.model_run_binding
    FOR EACH ROW EXECUTE FUNCTION ops.validate_risk_model_run_binding();

CREATE OR REPLACE FUNCTION ops.protect_bound_model_run()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- 既有米筐观察即使尚未绑定，也不能通过补写/改写用途和身份原地转正。
    -- 包括旧 fixed run 未记录 purpose 的情况；正式用途必须建立新的观察身份。
    IF OLD.source = 'ricequant' AND OLD.units ?| ARRAY['variant_id', 'observation_id'] THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'RiceQuant observation identity cannot be deleted'
                USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.source, NEW.units -> 'purpose', NEW.units -> 'variant_id',
               NEW.units -> 'observation_id', NEW.units -> 'trading_day')
            IS DISTINCT FROM
            ROW(OLD.source, OLD.units -> 'purpose', OLD.units -> 'variant_id',
                OLD.units -> 'observation_id', OLD.units -> 'trading_day')
        THEN
            RAISE EXCEPTION 'RiceQuant observation purpose and identity are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM factor.model_run_binding WHERE run_id = OLD.run_id) THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Bound model_run cannot be deleted' USING ERRCODE = '23514';
        END IF;
        IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'Bound model_run metadata is immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER trg_model_run_bound_immutable
    BEFORE UPDATE OR DELETE ON factor.model_run
    FOR EACH ROW EXECUTE FUNCTION ops.protect_bound_model_run();

CREATE OR REPLACE FUNCTION ops.validate_risk_import_checkpoint()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    receipt_time TIMESTAMPTZ;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.variant_id IS NOT NULL THEN
            RAISE EXCEPTION 'Tagged import checkpoint cannot be deleted' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.variant_id IS NULL THEN
            IF NEW.variant_id IS NOT NULL THEN
                RAISE EXCEPTION 'Legacy checkpoint cannot be relabelled as a risk capture'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF ROW(NEW.provider, NEW.dataset_name, NEW.partition_key, NEW.variant_id,
               NEW.observation_id, NEW.trading_day, NEW.capture_manifest_hash, NEW.captured_at,
               NEW.state, NEW.watermark_ts)
            IS DISTINCT FROM
            ROW(OLD.provider, OLD.dataset_name, OLD.partition_key, OLD.variant_id,
                OLD.observation_id, OLD.trading_day, OLD.capture_manifest_hash, OLD.captured_at,
                OLD.state, OLD.watermark_ts)
        THEN
            RAISE EXCEPTION 'Captured import identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.import_receipt_id IS NOT NULL THEN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'Imported checkpoint is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.import_receipt_id IS NULL THEN
            IF NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'Capture only permits a transition to a matching receipt'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
    ELSE
        IF NEW.variant_id IS NULL THEN RETURN NEW; END IF;
        IF NEW.import_receipt_id IS NOT NULL THEN
            RAISE EXCEPTION 'Import checkpoint must first record capture without a receipt'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.import_receipt_id IS NOT NULL THEN
        SELECT committed_at INTO receipt_time FROM ops.import_receipt
        WHERE receipt_id = NEW.import_receipt_id AND variant_id = NEW.variant_id
            AND observation_id = NEW.observation_id AND trading_day = NEW.trading_day
            AND manifest_hash = NEW.capture_manifest_hash;
        IF NOT FOUND OR NEW.imported_at IS DISTINCT FROM receipt_time THEN
            RAISE EXCEPTION 'Import checkpoint receipt or commit time mismatch' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM factor.model_run_binding WHERE receipt_id = NEW.import_receipt_id
                AND variant_id = NEW.variant_id AND observation_id = NEW.observation_id
                AND trading_day = NEW.trading_day
        ) THEN
            RAISE EXCEPTION 'Import checkpoint requires a bound model_run' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER trg_import_checkpoint_risk_transition
    BEFORE INSERT OR UPDATE OR DELETE ON ops.import_checkpoint
    FOR EACH ROW EXECUTE FUNCTION ops.validate_risk_import_checkpoint();

COMMENT ON TABLE ops.dataset_variant IS
    '不可变数据配置身份登记。purpose 必须与 identity 的用途一致；validation 不能改标 production。不是发布许可。';
COMMENT ON COLUMN ops.dataset_variant.variant_id IS '采集配置语义 SHA-256，由应用计算并校验；不包含可扩展日期范围。';
COMMENT ON COLUMN ops.dataset_variant.provider IS '数据供应商；与 checkpoint 的 provider 和绑定 run 的 source 一致。';
COMMENT ON COLUMN ops.dataset_variant.dataset_name IS '逻辑采集数据集；风险绑定当前只接受 rq_risk_model。';
COMMENT ON COLUMN ops.dataset_variant.purpose IS 'validation 或 production；不可更新，用途不同必须创建新 variant。';
COMMENT ON COLUMN ops.dataset_variant.identity IS '无凭据的配置身份 JSON 对象；purpose 字符串必填且等于登记用途。';
COMMENT ON COLUMN ops.dataset_variant.created_at IS '身份登记的实际时间，带时区，不可改写。';
COMMENT ON TABLE ops.import_receipt IS
    '成功导入的不可变回执；与业务数据、binding、成功 ETL 同事务提交，失败回滚不留成功回执。不是发布清单。';
COMMENT ON COLUMN ops.import_receipt.receipt_id IS '成功导入回执 UUID；用于绑定模型 run 及推进对应观察检查点。';
COMMENT ON COLUMN ops.import_receipt.target IS '逻辑原子目标，当前固定 factor.risk_bundle，代表同日五件套与覆盖账本。';
COMMENT ON COLUMN ops.import_receipt.variant_id IS '引用已登记的不可变采集 variant。';
COMMENT ON COLUMN ops.import_receipt.manifest_hash IS '完整采集 manifest 的语义 SHA-256，必须与 capture checkpoint 一致。';
COMMENT ON COLUMN ops.import_receipt.importer_version IS '明确的 importer 版本；与 target、manifest_hash 构成重放幂等键。';
COMMENT ON COLUMN ops.import_receipt.observation_id IS 'raw 实际观察身份，32 位小写十六进制；每次重采形成新观察。';
COMMENT ON COLUMN ops.import_receipt.trading_day IS '该观察对应的交易日（event time）；不是采集日期。';
COMMENT ON COLUMN ops.import_receipt.rows_written IS '此次成功原子导入的业务写入行数，包括覆盖账本，不包括元数据和 ETL。';
COMMENT ON COLUMN ops.import_receipt.quality IS '本次导入的质量结果 JSON 对象；数值门禁及覆盖结果可追溯，不含凭据。';
COMMENT ON COLUMN ops.import_receipt.committed_at IS '入库事务写回执时的实际时刻；只有事务提交后才可见，不伪装为历史可得时间。';
COMMENT ON TABLE factor.model_run_binding IS
    '模型 run 与成功导入回执的一次性绑定；核对用途、variant、观察和交易日，绑定后禁止改写 run 元数据。';
COMMENT ON COLUMN factor.model_run_binding.run_id IS '被绑定的 model_run；一个 run 只能绑定一次。';
COMMENT ON COLUMN factor.model_run_binding.receipt_id IS '同事务写入的成功导入回执，只能绑定一个 run；与 variant、观察和交易日组成复合外键。';
COMMENT ON COLUMN factor.model_run_binding.variant_id IS '必须同时等于 receipt.variant_id 和 model_run.units.variant_id。';
COMMENT ON COLUMN factor.model_run_binding.observation_id IS '必须同时等于 receipt.observation_id 和 model_run.units.observation_id。';
COMMENT ON COLUMN factor.model_run_binding.trading_day IS '必须同时等于 receipt.trading_day 和 model_run.units.trading_day。';
COMMENT ON COLUMN ops.import_checkpoint.variant_id IS '非 NULL 表示版本化观察检查点；NULL 的旧检查点保留原行为。';
COMMENT ON COLUMN ops.import_checkpoint.observation_id IS '实际采集观察身份；与 variant 和 trading_day 一起冻结。';
COMMENT ON COLUMN ops.import_checkpoint.trading_day IS '单个观察的交易日；partition_key 为 variant/day/observation，不代表连续水位。';
COMMENT ON COLUMN ops.import_checkpoint.capture_manifest_hash IS '实际采集完整 manifest 的语义 SHA-256；成功回执必须引用同一份证据。';
COMMENT ON COLUMN ops.import_checkpoint.captured_at IS 'raw 的实际 observed_at，带时区；采集完成时冻结，不用事件日替代。';
COMMENT ON COLUMN ops.import_checkpoint.import_receipt_id IS '采集时为 NULL；仅允许一次推进为同 variant/观察/日期/manifest 的成功回执。';
COMMENT ON COLUMN ops.import_checkpoint.imported_at IS '仅导入成功后填写，必须等于绑定回执 committed_at；重放不刷新时间。';
COMMENT ON COLUMN ops.import_checkpoint.watermark_date IS
    '旧检查点保留原语义；版本化观察只在成功导入后等于本行 trading_day，不得以 MAX 日期冒充连续导入水位。';
COMMENT ON FUNCTION ops.reject_immutable_risk_evidence() IS '拒绝 variant、receipt、binding 的 UPDATE/DELETE，禁止改写用途与成功证据。';
COMMENT ON FUNCTION ops.validate_risk_model_run_binding() IS '绑定前锁定 run，核对回执及采集用途、来源、模型和观察身份。';
COMMENT ON FUNCTION ops.protect_bound_model_run() IS '既有米筐观察用途及身份不可改写，旧 fixed 缺用途不能原地补成 production；绑定后全部 run 元数据不可改写。';
COMMENT ON FUNCTION ops.validate_risk_import_checkpoint() IS '保护版本化 capture 身份，只允许一次与回执一致的导入推进；不改变旧行行为。';
