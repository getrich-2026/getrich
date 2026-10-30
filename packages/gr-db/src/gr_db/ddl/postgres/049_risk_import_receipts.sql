-- 风险整包绑定与不可变证据触发器；variant／receipt／checkpoint 的 CREATE 均在 037。
-- 保留本文件作为风险证据机制就绪的运行时记账标识。
CREATE TABLE IF NOT EXISTS factor.model_run_binding (
    run_id UUID PRIMARY KEY REFERENCES factor.model_run(run_id),
    receipt_id UUID NOT NULL,
    variant_id VARCHAR(64) NOT NULL,
    observation_id VARCHAR(32) NOT NULL,
    trading_day DATE NOT NULL,
    CONSTRAINT uq_model_run_binding_receipt UNIQUE (receipt_id),
    CONSTRAINT fk_model_run_binding_receipt FOREIGN KEY (
        receipt_id, variant_id, observation_id, trading_day
    ) REFERENCES factor.import_receipt (
        receipt_id, variant_id, observation_id, trading_day
    )
);

CREATE OR REPLACE FUNCTION factor.reject_immutable_risk_evidence()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Immutable risk evidence rejects %', TG_OP USING ERRCODE = '23514';
END
$$;

CREATE OR REPLACE TRIGGER trg_dataset_variant_immutable
    BEFORE UPDATE OR DELETE ON factor.dataset_variant
    FOR EACH ROW EXECUTE FUNCTION factor.reject_immutable_risk_evidence();
CREATE OR REPLACE TRIGGER trg_import_receipt_immutable
    BEFORE UPDATE OR DELETE ON factor.import_receipt
    FOR EACH ROW EXECUTE FUNCTION factor.reject_immutable_risk_evidence();
CREATE OR REPLACE TRIGGER trg_model_run_binding_immutable
    BEFORE UPDATE OR DELETE ON factor.model_run_binding
    FOR EACH ROW EXECUTE FUNCTION factor.reject_immutable_risk_evidence();

CREATE OR REPLACE FUNCTION factor.validate_risk_model_run_binding()
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
    FROM factor.import_receipt r JOIN factor.dataset_variant v ON v.variant_id = r.variant_id
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
    FOR EACH ROW EXECUTE FUNCTION factor.validate_risk_model_run_binding();

CREATE OR REPLACE FUNCTION factor.protect_bound_model_run()
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
    FOR EACH ROW EXECUTE FUNCTION factor.protect_bound_model_run();

CREATE OR REPLACE FUNCTION factor.validate_risk_import_checkpoint()
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
        SELECT committed_at INTO receipt_time FROM factor.import_receipt
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
    BEFORE INSERT OR UPDATE OR DELETE ON factor.import_checkpoint
    FOR EACH ROW EXECUTE FUNCTION factor.validate_risk_import_checkpoint();

COMMENT ON TABLE factor.dataset_variant IS
    '风险模型专用的不可变数据配置身份登记。purpose 必须与 identity 的用途一致；validation 不能改标 production。不是发布许可。';
COMMENT ON COLUMN factor.dataset_variant.variant_id IS '采集配置语义 SHA-256，由应用计算并校验；不包含可扩展日期范围。';
COMMENT ON COLUMN factor.dataset_variant.provider IS '数据供应商；与 checkpoint 的 provider 和绑定 run 的 source 一致。';
COMMENT ON COLUMN factor.dataset_variant.dataset_name IS '逻辑采集数据集；风险绑定当前只接受 rq_risk_model。';
COMMENT ON COLUMN factor.dataset_variant.purpose IS 'validation 或 production；不可更新，用途不同必须创建新 variant。';
COMMENT ON COLUMN factor.dataset_variant.identity IS '无凭据的配置身份 JSON 对象；purpose 字符串必填且等于登记用途。';
COMMENT ON COLUMN factor.dataset_variant.created_at IS '身份登记的实际时间，带时区，不可改写。';
COMMENT ON TABLE factor.import_receipt IS
    '风险整包成功导入的不可变回执；与业务数据、binding、成功 ETL 同事务提交，失败回滚不留成功回执。不是发布清单。';
COMMENT ON COLUMN factor.import_receipt.receipt_id IS '成功导入回执 UUID；用于绑定模型 run 及推进对应观察检查点。';
COMMENT ON COLUMN factor.import_receipt.target IS '逻辑原子目标，当前固定 factor.risk_bundle，代表同日五件套与覆盖账本。';
COMMENT ON COLUMN factor.import_receipt.variant_id IS '引用已登记的不可变采集 variant。';
COMMENT ON COLUMN factor.import_receipt.manifest_hash IS '完整采集 manifest 的语义 SHA-256，必须与 capture checkpoint 一致。';
COMMENT ON COLUMN factor.import_receipt.importer_version IS '明确的 importer 版本；与 target、manifest_hash 构成重放幂等键。';
COMMENT ON COLUMN factor.import_receipt.observation_id IS 'raw 实际观察身份，32 位小写十六进制；每次重采形成新观察。';
COMMENT ON COLUMN factor.import_receipt.trading_day IS '该观察对应的交易日（event time）；不是采集日期。';
COMMENT ON COLUMN factor.import_receipt.rows_written IS '此次成功原子导入的业务写入行数，包括覆盖账本，不包括元数据和 ETL。';
COMMENT ON COLUMN factor.import_receipt.quality IS '本次导入的质量结果 JSON 对象；数值门禁及覆盖结果可追溯，不含凭据。';
COMMENT ON COLUMN factor.import_receipt.committed_at IS '入库事务写回执时的实际时刻；只有事务提交后才可见，不伪装为历史可得时间。';
COMMENT ON TABLE factor.model_run_binding IS
    '模型 run 与成功导入回执的一次性绑定；核对用途、variant、观察和交易日，绑定后禁止改写 run 元数据。';
COMMENT ON COLUMN factor.model_run_binding.run_id IS '被绑定的 model_run；一个 run 只能绑定一次。';
COMMENT ON COLUMN factor.model_run_binding.receipt_id IS '同事务写入的成功导入回执，只能绑定一个 run；与 variant、观察和交易日组成复合外键。';
COMMENT ON COLUMN factor.model_run_binding.variant_id IS '必须同时等于 receipt.variant_id 和 model_run.units.variant_id。';
COMMENT ON COLUMN factor.model_run_binding.observation_id IS '必须同时等于 receipt.observation_id 和 model_run.units.observation_id。';
COMMENT ON COLUMN factor.model_run_binding.trading_day IS '必须同时等于 receipt.trading_day 和 model_run.units.trading_day。';
COMMENT ON COLUMN factor.import_checkpoint.variant_id IS '非 NULL 表示风险观察检查点；当前写入方均填写。NULL 行只受基础 CHECK 约束，不经风险观察校验。';
COMMENT ON COLUMN factor.import_checkpoint.observation_id IS '实际采集观察身份；与 variant 和 trading_day 一起冻结。';
COMMENT ON COLUMN factor.import_checkpoint.trading_day IS '单个观察的交易日；partition_key 为 variant/day/observation，不代表连续水位。';
COMMENT ON COLUMN factor.import_checkpoint.capture_manifest_hash IS '实际采集完整 manifest 的语义 SHA-256；成功回执必须引用同一份证据。';
COMMENT ON COLUMN factor.import_checkpoint.captured_at IS 'raw 的实际 observed_at，带时区；采集完成时冻结，不用事件日替代。';
COMMENT ON COLUMN factor.import_checkpoint.import_receipt_id IS '采集时为 NULL；仅允许一次推进为同 variant/观察/日期/manifest 的成功回执。';
COMMENT ON COLUMN factor.import_checkpoint.imported_at IS '仅导入成功后填写，必须等于绑定回执 committed_at；重放不刷新时间。';
COMMENT ON COLUMN factor.import_checkpoint.watermark_date IS
    '风险观察只在成功导入后填写且等于本行 trading_day；不得以 MAX 日期冒充连续导入水位。';
COMMENT ON FUNCTION factor.reject_immutable_risk_evidence() IS '拒绝 variant、receipt、binding 的 UPDATE/DELETE，禁止改写用途与成功证据。';
COMMENT ON FUNCTION factor.validate_risk_model_run_binding() IS '绑定前锁定 run，核对回执及采集用途、来源、模型和观察身份。';
COMMENT ON FUNCTION factor.protect_bound_model_run() IS '既有米筐观察用途及身份不可改写，旧 fixed 缺用途不能原地补成 production；绑定后全部 run 元数据不可改写。';
COMMENT ON FUNCTION factor.validate_risk_import_checkpoint() IS '保护风险观察 capture 身份，只允许一次与回执一致的导入推进；variant_id 为 NULL 的行不校验。';
