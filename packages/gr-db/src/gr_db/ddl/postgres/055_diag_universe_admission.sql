-- 多用户V1：按证券清单准入可自由组合与调权，不改变旧精确组合证据的含义。
-- 本迁移不发布数据、不改calibrated、不启用任何API配置。
CREATE TABLE IF NOT EXISTS factor.risk_universe_admission (
    admission_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES factor.model_run_binding(run_id),
    receipt_id UUID NOT NULL REFERENCES factor.import_receipt(receipt_id),
    as_of_date DATE NOT NULL CHECK (isfinite(as_of_date)),
    security_ids BIGINT[] NOT NULL CHECK (cardinality(security_ids)>0),
    security_hash VARCHAR(64) NOT NULL CHECK (security_hash ~ '^[0-9a-f]{64}$'),
    metrics TEXT[] NOT NULL CHECK (cardinality(metrics)>0),
    factor_order_hash VARCHAR(32) NOT NULL,
    units_evidence JSONB NOT NULL CHECK (jsonb_typeof(units_evidence)='object'),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='object'),
    created_xid BIGINT NOT NULL DEFAULT txid_current(),
    UNIQUE(run_id,security_hash)
);
CREATE TABLE IF NOT EXISTS factor.risk_universe_member (
    admission_id UUID NOT NULL REFERENCES factor.risk_universe_admission(admission_id),
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    PRIMARY KEY(admission_id,instrument_id)
);

-- 只新增明确协议值，旧v1与已发布hash均不重写。
ALTER TABLE diag.data_publication
 DROP CONSTRAINT IF EXISTS data_publication_contract_version_check;
ALTER TABLE diag.data_publication
 ADD CONSTRAINT data_publication_contract_version_check
 CHECK (contract_version IN ('diag-publication-v1','diag-publication-v2-universe'));

CREATE OR REPLACE FUNCTION diag.validate_universe_admission()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE ids BIGINT[]; digest TEXT; axis VARCHAR(32); n SMALLINT;
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 SELECT array_agg(DISTINCT x ORDER BY x) INTO ids FROM unnest(NEW.security_ids) x;
 digest=encode(sha256(convert_to('['||array_to_string(ids,',')||']','UTF8')),'hex');
 SELECT factor_order_hash,factor_count INTO axis,n FROM factor.model_run WHERE run_id=NEW.run_id;
 IF array_ndims(NEW.security_ids) IS DISTINCT FROM 1
  OR array_lower(NEW.security_ids,1) IS DISTINCT FROM 1
  OR array_position(NEW.security_ids,NULL) IS NOT NULL
  OR NEW.security_ids IS DISTINCT FROM ids OR NEW.security_hash IS DISTINCT FROM digest
  OR NOT diag.risk_run_is_publishable(NEW.run_id,NEW.receipt_id,NEW.as_of_date)
  OR NEW.factor_order_hash IS DISTINCT FROM axis
  OR NEW.units_evidence='{}'::jsonb OR NEW.evidence='{}'::jsonb
  OR array_position(NEW.metrics,NULL) IS NOT NULL
  OR NOT NEW.metrics <@ ARRAY['annual_variance','daily_prediction_volatility','volatility']::TEXT[]
  OR NOT EXISTS(SELECT 1 FROM factor.covariance c WHERE c.run_id=NEW.run_id
      AND c.trading_day=NEW.as_of_date AND c.factor_count=n)
  OR EXISTS (
   SELECT 1 FROM unnest(NEW.security_ids) id
   LEFT JOIN meta.instruments i ON i.instrument_id=id
   LEFT JOIN factor.model_run_coverage c ON c.run_id=NEW.run_id AND c.instrument_id=id
      AND c.trading_day=NEW.as_of_date AND c.status='included'
   LEFT JOIN factor.exposure e ON e.run_id=NEW.run_id AND e.instrument_id=id
      AND e.trading_day=NEW.as_of_date AND e.factor_count=n
   LEFT JOIN factor.specific_risk r ON r.run_id=NEW.run_id AND r.instrument_id=id
      AND r.trading_day=NEW.as_of_date
   WHERE i.instrument_id IS NULL OR i.asset<>'stock' OR i.exchange NOT IN ('XSHG','XSHE')
    OR i.list_date IS NULL OR i.list_date>NEW.as_of_date
    OR (i.delist_date IS NOT NULL AND i.delist_date<=NEW.as_of_date)
    OR c.instrument_id IS NULL OR e.instrument_id IS NULL OR r.instrument_id IS NULL
  ) THEN
  RAISE EXCEPTION 'Risk universe admission rejected' USING ERRCODE='23514';
 END IF;
 NEW.created_xid=txid_current();
 INSERT INTO diag.data_version_invalidation
  (data_version_id,event_key,reason,dataset_key,partition_key)
 SELECT c.data_version_id,'universe-admission:'||NEW.admission_id::text,
  'risk_universe_admission_changed',c.dataset_key,c.partition_key
 FROM diag.data_version_component c WHERE c.run_id=NEW.run_id ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.validate_universe_member()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE p factor.risk_universe_admission%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 SELECT * INTO STRICT p FROM factor.risk_universe_admission WHERE admission_id=NEW.admission_id;
 IF p.created_xid<>txid_current() OR NOT NEW.instrument_id=ANY(p.security_ids) THEN
  RAISE EXCEPTION 'Universe membership is immutable after admission' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.validate_universe_commit()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE actual BIGINT[];
BEGIN
 SELECT array_agg(instrument_id ORDER BY instrument_id) INTO actual
 FROM factor.risk_universe_member WHERE admission_id=NEW.admission_id;
 IF actual IS DISTINCT FROM NEW.security_ids THEN
  RAISE EXCEPTION 'Universe admission members differ from security list' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER diag_universe_validate BEFORE INSERT ON factor.risk_universe_admission
 FOR EACH ROW EXECUTE FUNCTION diag.validate_universe_admission();
CREATE OR REPLACE TRIGGER diag_universe_member_validate BEFORE INSERT ON factor.risk_universe_member
 FOR EACH ROW EXECUTE FUNCTION diag.validate_universe_member();
CREATE OR REPLACE TRIGGER diag_universe_immutable BEFORE UPDATE OR DELETE
 ON factor.risk_universe_admission FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_universe_no_truncate BEFORE TRUNCATE
 ON factor.risk_universe_admission FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_universe_member_immutable BEFORE UPDATE OR DELETE
 ON factor.risk_universe_member FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_universe_member_no_truncate BEFORE TRUNCATE
 ON factor.risk_universe_member FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='factor.risk_universe_admission'::regclass
  AND tgname='diag_universe_commit') THEN
  CREATE CONSTRAINT TRIGGER diag_universe_commit AFTER INSERT ON factor.risk_universe_admission
   DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION diag.validate_universe_commit();
 END IF;
END $$;

COMMENT ON TABLE factor.risk_universe_admission IS
 '同日同run已验收证券清单；允许清单内任意非负权重组合，不复用portfolio_hash或改变calibrated。';
COMMENT ON TABLE factor.risk_universe_member IS
 '证券清单成员真实外键；与header安全清单提交时完全一致，提交后不可追加或修改。';
COMMENT ON COLUMN factor.risk_universe_admission.admission_id IS '不可变证券清单准入ID。';
COMMENT ON COLUMN factor.risk_universe_admission.run_id IS '同一production风险整包绑定的run。';
COMMENT ON COLUMN factor.risk_universe_admission.receipt_id IS '同run同日现有原子风险收据。';
COMMENT ON COLUMN factor.risk_universe_admission.as_of_date IS '唯一准入事件日期，不回退相邻日。';
COMMENT ON COLUMN factor.risk_universe_admission.security_ids IS '严格升序无重复的证券ID清单；不含权重。';
COMMENT ON COLUMN factor.risk_universe_admission.security_hash IS '升序证券ID紧凑JSON数组的SHA256，与组合权重hash分离。';
COMMENT ON COLUMN factor.risk_universe_admission.metrics IS '已验收指标白名单，只对这份清单内完整持仓出数。';
COMMENT ON COLUMN factor.risk_universe_admission.factor_order_hash IS '与指定run严格一致的因子顺序hash。';
COMMENT ON COLUMN factor.risk_universe_admission.units_evidence IS '实际单位、反年化及读库转换的验收证据。';
COMMENT ON COLUMN factor.risk_universe_admission.evidence IS '实际证券范围、完整覆盖、验收源码与授权证据。';
COMMENT ON COLUMN factor.risk_universe_admission.created_xid IS '数据库强制创建事务，成员仅能在此事务内插入。';
COMMENT ON COLUMN factor.risk_universe_member.admission_id IS '不可变证券清单准入头，真实FK。';
COMMENT ON COLUMN factor.risk_universe_member.instrument_id IS 'meta.instruments证券ID真实FK。';

-- 独立延迟约束补充054；不替换或放松旧发布完整性检查。
CREATE OR REPLACE FUNCTION diag.validate_universe_publication()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE scope JSONB; expected JSONB; a factor.risk_universe_admission%ROWTYPE; calibrated BOOLEAN;
BEGIN
 SELECT available_options->'publication_scope' INTO scope FROM diag.data_version
 WHERE data_version_id=NEW.data_version_id;
 IF NEW.contract_version='diag-publication-v1' THEN
  IF scope->>'scope_type'='security_universe' THEN
   RAISE EXCEPTION 'Legacy publication cannot claim universe admission' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 END IF;
 IF scope->>'scope_type' IS DISTINCT FROM 'security_universe' THEN
  RAISE EXCEPTION 'Universe publication requires explicit security scope' USING ERRCODE='23514';
 END IF;
 SELECT * INTO STRICT a FROM factor.risk_universe_admission
 WHERE admission_id=(scope->>'universe_admission_id')::UUID;
 SELECT m.calibrated INTO STRICT calibrated FROM factor.model_run m WHERE m.run_id=a.run_id;
 expected=jsonb_build_object('scope_type','security_universe','as_of',to_char(a.as_of_date,'YYYY-MM-DD'),
  'model','v2','run_id',a.run_id::TEXT,'receipt_id',a.receipt_id::TEXT,
  'metrics',a.metrics,'security_ids',a.security_ids,'security_hash',a.security_hash,
  'universe_admission_id',a.admission_id::TEXT,'calibrated',calibrated);
 IF scope IS DISTINCT FROM expected OR a.as_of_date<>NEW.as_of_date
  OR NOT diag.risk_run_is_publishable(a.run_id,a.receipt_id,a.as_of_date)
  OR NOT EXISTS(SELECT 1 FROM diag.data_version_component c
   WHERE c.data_version_id=NEW.data_version_id AND c.run_id=a.run_id
    AND c.risk_receipt_id=a.receipt_id) THEN
  RAISE EXCEPTION 'Universe publication scope differs from admitted evidence' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='diag.data_publication'::regclass
  AND tgname='diag_universe_publication_commit') THEN
  CREATE CONSTRAINT TRIGGER diag_universe_publication_commit AFTER INSERT ON diag.data_publication
   DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION diag.validate_universe_publication();
 END IF;
END $$;
