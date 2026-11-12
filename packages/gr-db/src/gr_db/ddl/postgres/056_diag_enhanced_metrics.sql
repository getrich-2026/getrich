-- 诊断增强协议：旧v1/v2不新增财务依赖；新v3增加年度ROE与四项风险指标。
ALTER TABLE diag.data_publication DROP CONSTRAINT IF EXISTS data_publication_contract_version_check;
ALTER TABLE diag.data_publication ADD CONSTRAINT data_publication_contract_version_check
 CHECK(contract_version IN ('diag-publication-v1','diag-publication-v2-universe','diag-publication-v3'));
ALTER TABLE factor.risk_universe_admission ADD COLUMN IF NOT EXISTS contract_version TEXT NOT NULL
 DEFAULT 'diag-publication-v2-universe'
 CHECK(contract_version IN ('diag-publication-v2-universe','diag-publication-v3'));
-- 同run同证券清单允许新协议独立准入，旧收据与旧头保持不可变。
ALTER TABLE factor.risk_universe_admission DROP CONSTRAINT IF EXISTS risk_universe_admission_run_id_security_hash_key;
ALTER TABLE factor.risk_universe_admission DROP CONSTRAINT IF EXISTS risk_universe_admission_protocol_key;
ALTER TABLE factor.risk_universe_admission ADD CONSTRAINT risk_universe_admission_protocol_key
 UNIQUE(run_id,security_hash,contract_version);
COMMENT ON COLUMN factor.risk_universe_admission.contract_version IS '风险指标准入协议；旧清单默认v2，增强清单用v3独立验收。';
COMMENT ON COLUMN fundamental.indicator_q.roe IS '最近已披露完整年度的加权平均ROE，小数；Tushare roe_waa百分数仅在入库层除100。零及负值保留，缺失为NULL。';
CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
 ON fundamental.indicator_q FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('fundamental.indicator_q');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE
 ON fundamental.indicator_q FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('fundamental.indicator_q');

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
  OR NOT (NEW.metrics <@ (CASE WHEN NEW.contract_version='diag-publication-v3' THEN
   ARRAY['annual_variance','daily_prediction_volatility','volatility','risk_contribution',
   'risk_contribution_ratio','marginal_risk_contribution','l3_effective_count']::TEXT[]
   ELSE ARRAY['annual_variance','daily_prediction_volatility','volatility']::TEXT[] END))
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

CREATE OR REPLACE FUNCTION diag.publication_is_valid(p_version TEXT)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM diag.data_publication p WHERE p.data_version_id=p_version)
 AND NOT EXISTS(SELECT 1 FROM diag.data_version_invalidation i WHERE i.data_version_id=p_version)
 -- 未受保护的新内部表使发布立即不可用，避免非标准chunk创建路径形成静默缺口。
 AND NOT EXISTS(SELECT 1 FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
   WHERE n.nspname='_timescaledb_internal' AND t.relkind='r' AND NOT EXISTS(
    SELECT 1 FROM pg_trigger g WHERE g.tgrelid=t.oid AND g.tgname='diag_chunk_truncate'
      AND g.tgenabled IN ('O','A')))

 AND NOT EXISTS (SELECT 1 FROM (VALUES ('meta.instruments'),('meta.symbol_map'),('meta.trading_calendar'),('market.stock_bar_1d'),('market.stock_suspend_event'),('market.stock_suspend_coverage'),('fundamental.valuation_1d'),('classify.instrument_category'),('classify.instrument_industry'),('classify.industry_node'),('classify.scheme')) AS required(dataset_key) WHERE NOT EXISTS (SELECT 1 FROM diag.data_version_component c WHERE c.data_version_id=p_version AND c.dataset_key=required.dataset_key))
 AND (NOT EXISTS (SELECT 1 FROM diag.data_publication WHERE data_version_id=p_version
    AND contract_version='diag-publication-v3') OR EXISTS (
    SELECT 1 FROM diag.data_version_component WHERE data_version_id=p_version
     AND dataset_key='fundamental.indicator_q'))
 AND NOT EXISTS (
  SELECT 1 FROM diag.data_version_component c
  JOIN diag.data_publication p USING(data_version_id)
  LEFT JOIN ops.diag_input_head h USING(dataset_key,partition_key)
  WHERE c.data_version_id=p_version AND (h.dataset_key IS NULL OR h.dirty
   OR h.revision<>c.head_revision
   OR ROW(h.basic_receipt_id,h.risk_receipt_id,h.run_id) IS DISTINCT FROM
      ROW(c.basic_receipt_id,c.risk_receipt_id,c.run_id)
   OR (c.run_id IS NOT NULL AND NOT diag.risk_run_is_publishable(c.run_id,c.risk_receipt_id,p.as_of_date)))
 )
$$;

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
 IF NEW.contract_version='diag-publication-v3' AND NOT EXISTS (
  SELECT 1 FROM diag.data_version_component WHERE data_version_id=NEW.data_version_id
   AND dataset_key='fundamental.indicator_q') THEN
  RAISE EXCEPTION 'Enhanced publication requires annual ROE receipt' USING ERRCODE='23514';
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
 IF a.contract_version<>NEW.contract_version OR scope IS DISTINCT FROM expected OR a.as_of_date<>NEW.as_of_date
  OR NOT diag.risk_run_is_publishable(a.run_id,a.receipt_id,a.as_of_date)
  OR NOT EXISTS(SELECT 1 FROM diag.data_version_component c
   WHERE c.data_version_id=NEW.data_version_id AND c.run_id=a.run_id
    AND c.risk_receipt_id=a.receipt_id) THEN
  RAISE EXCEPTION 'Universe publication scope differs from admitted evidence' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
