-- D-022 2b：不可变诊断发布与同版本读取。迁移不发布数据、不改校准状态。
-- advisory key 7342061105：reader在事务前取session共享锁；writer取事务排他锁。
CREATE TABLE IF NOT EXISTS ops.diag_input_receipt (
    receipt_id UUID PRIMARY KEY,
    dataset_key TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (btrim(provider) <> ''),
    manifest_hash VARCHAR(64) NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    importer_version TEXT NOT NULL CHECK (btrim(importer_version) <> ''),
    coverage_start DATE NOT NULL,
    coverage_end DATE NOT NULL CHECK (coverage_end >= coverage_start),
    quality JSONB NOT NULL CHECK (jsonb_typeof(quality) = 'object'),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(dataset_key,partition_key,manifest_hash,importer_version),
    UNIQUE(receipt_id,dataset_key,partition_key)
);
CREATE TABLE IF NOT EXISTS ops.diag_input_head (
    dataset_key TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    basic_receipt_id UUID,
    risk_receipt_id UUID REFERENCES factor.import_receipt(receipt_id),
    run_id UUID REFERENCES factor.model_run_binding(run_id),
    revision BIGINT NOT NULL CHECK (revision > 0),
    dirty BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY(dataset_key,partition_key),
    FOREIGN KEY (basic_receipt_id,dataset_key,partition_key)
        REFERENCES ops.diag_input_receipt(receipt_id,dataset_key,partition_key),
    CHECK ((basic_receipt_id IS NOT NULL AND risk_receipt_id IS NULL AND run_id IS NULL)
        OR (basic_receipt_id IS NULL AND risk_receipt_id IS NOT NULL AND run_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS diag.data_publication (
    data_version_id VARCHAR(64) PRIMARY KEY REFERENCES diag.data_version(data_version_id),
    as_of_date DATE NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    publication_seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    manifest_hash VARCHAR(64) NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    contract_version TEXT NOT NULL CHECK (contract_version = 'diag-publication-v1'),
    created_xid BIGINT NOT NULL DEFAULT txid_current()
);
CREATE TABLE IF NOT EXISTS diag.data_version_component (
    data_version_id VARCHAR(64) NOT NULL REFERENCES diag.data_publication(data_version_id),
    dataset_key TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    basic_receipt_id UUID,
    risk_receipt_id UUID REFERENCES factor.import_receipt(receipt_id),
    run_id UUID REFERENCES factor.model_run_binding(run_id),
    coverage_start DATE NOT NULL,
    coverage_end DATE NOT NULL CHECK (coverage_end >= coverage_start),
    head_revision BIGINT NOT NULL CHECK (head_revision > 0),
    PRIMARY KEY(data_version_id,dataset_key,partition_key),
    FOREIGN KEY (basic_receipt_id,dataset_key,partition_key)
        REFERENCES ops.diag_input_receipt(receipt_id,dataset_key,partition_key),
    FOREIGN KEY (dataset_key,partition_key) REFERENCES ops.diag_input_head(dataset_key,partition_key),
    CHECK ((basic_receipt_id IS NOT NULL AND risk_receipt_id IS NULL AND run_id IS NULL)
        OR (basic_receipt_id IS NULL AND risk_receipt_id IS NOT NULL AND run_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS diag.data_version_invalidation (
    data_version_id VARCHAR(64) NOT NULL REFERENCES diag.data_publication(data_version_id),
    event_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    dataset_key TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    new_receipt_id UUID,
    invalidated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(data_version_id,event_key)
);
CREATE TABLE IF NOT EXISTS factor.risk_run_admission (
    admission_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES factor.model_run_binding(run_id),
    receipt_id UUID NOT NULL REFERENCES factor.import_receipt(receipt_id),
    as_of_date DATE NOT NULL,
    portfolio_hash VARCHAR(64) NOT NULL CHECK (portfolio_hash ~ '^[0-9a-f]{64}$'),
    metrics TEXT[] NOT NULL CHECK (cardinality(metrics)>0),
    factor_order_hash VARCHAR(32) NOT NULL,
    units_evidence JSONB NOT NULL CHECK (jsonb_typeof(units_evidence)='object'),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='object'),
    UNIQUE(run_id,portfolio_hash)
);

CREATE OR REPLACE FUNCTION diag.risk_run_is_publishable(p_run UUID, p_receipt UUID, p_day DATE)
RETURNS BOOLEAN LANGUAGE SQL STABLE AS $$
 SELECT EXISTS (
  SELECT 1 FROM factor.model_run m
  JOIN factor.model_run_binding b USING(run_id)
  JOIN factor.import_receipt r ON r.receipt_id=b.receipt_id
  JOIN factor.dataset_variant v ON v.variant_id=b.variant_id
  WHERE m.run_id=p_run AND b.receipt_id=p_receipt AND b.trading_day=p_day
    AND r.trading_day=p_day AND r.variant_id=b.variant_id AND r.observation_id=b.observation_id
    AND v.purpose='production' AND m.source='ricequant'
    AND m.units->>'purpose'='production' AND m.units->>'model'='v2'
    AND v.identity->>'horizon'='daily' AND m.annualization_basis='annual_252'
    AND m.units->>'covariance'='pct2_annual' AND m.units->>'specific_risk'='pct2_annual'
    AND r.quality->>'publication_eligible'='true'
    AND NOT EXISTS (SELECT 1 FROM ops.data_quality_check q
      WHERE q.rule='risk_bundle_publishable'
        AND q.detail->>'factor_model_run_id'=m.run_id::text AND q.detail->>'publishable'='false')
    AND (SELECT count(*)>0 AND count(*) FILTER(WHERE c.status='included')*1000>=count(*)*999
      AND count(*) FILTER(WHERE c.status IN ('universe_boundary_unknown','unmapped_symbol'))=0
      FROM factor.model_run_coverage c WHERE c.run_id=m.run_id)
 )
$$;
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

CREATE OR REPLACE FUNCTION diag.reject_publication_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Diagnostic publication evidence is immutable' USING ERRCODE='23514';
END $$;
CREATE OR REPLACE FUNCTION diag.validate_component()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE h ops.diag_input_head%ROWTYPE; p diag.data_publication%ROWTYPE; r ops.diag_input_receipt%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 SELECT * INTO STRICT p FROM diag.data_publication WHERE data_version_id=NEW.data_version_id;
 IF p.created_xid<>txid_current() THEN
  RAISE EXCEPTION 'Cannot append to committed publication' USING ERRCODE='23514';
 END IF;
 SELECT * INTO STRICT h FROM ops.diag_input_head
  WHERE dataset_key=NEW.dataset_key AND partition_key=NEW.partition_key FOR UPDATE;
 IF h.dirty OR h.revision<>NEW.head_revision OR
   ROW(h.basic_receipt_id,h.risk_receipt_id,h.run_id) IS DISTINCT FROM
   ROW(NEW.basic_receipt_id,NEW.risk_receipt_id,NEW.run_id) THEN
  RAISE EXCEPTION 'Publication head changed or dirty' USING ERRCODE='23514';
 END IF;
 IF NEW.run_id IS NOT NULL THEN
  IF NEW.coverage_start<>p.as_of_date OR NEW.coverage_end<>p.as_of_date OR
    (SELECT committed_at FROM factor.import_receipt WHERE receipt_id=NEW.risk_receipt_id)>p.published_at OR
    NOT diag.risk_run_is_publishable(NEW.run_id,NEW.risk_receipt_id,p.as_of_date) THEN
   RAISE EXCEPTION 'Risk run is not publishable' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO STRICT r FROM ops.diag_input_receipt WHERE receipt_id=NEW.basic_receipt_id;
  IF r.committed_at>p.published_at OR r.quality->>'accepted' IS DISTINCT FROM 'true'
     OR r.coverage_start>NEW.coverage_start
     OR r.coverage_end<NEW.coverage_end THEN
   RAISE EXCEPTION 'Basic receipt coverage not accepted' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.validate_admission()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 IF NOT diag.risk_run_is_publishable(NEW.run_id,NEW.receipt_id,NEW.as_of_date)
 OR NEW.factor_order_hash IS DISTINCT FROM
    (SELECT factor_order_hash FROM factor.model_run WHERE run_id=NEW.run_id)
 OR NEW.units_evidence='{}'::jsonb OR NEW.evidence='{}'::jsonb
 OR NOT NEW.metrics <@ ARRAY['annual_variance','daily_prediction_volatility','volatility']::TEXT[] THEN
  RAISE EXCEPTION 'Scoped risk admission rejected' USING ERRCODE='23514';
 END IF;
 -- 新组合或指标准入改变版本可用能力，必须发布新版本，不能原地扩展。
 INSERT INTO diag.data_version_invalidation(data_version_id,event_key,reason,dataset_key,partition_key)
 SELECT c.data_version_id,'admission:'||NEW.admission_id::text,'risk_admission_changed',
   c.dataset_key,c.partition_key
 FROM diag.data_version_component c WHERE c.run_id=NEW.run_id
 ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.validate_head()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 IF TG_OP='UPDATE' AND (NEW.dataset_key<>OLD.dataset_key OR NEW.partition_key<>OLD.partition_key
   OR NEW.revision<=OLD.revision) THEN
  RAISE EXCEPTION 'Head revision must advance without changing partition' USING ERRCODE='23514';
 END IF;
 IF NEW.run_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM factor.model_run_binding b
  WHERE b.run_id=NEW.run_id AND b.receipt_id=NEW.risk_receipt_id) THEN
  RAISE EXCEPTION 'Head run receipt mismatch' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' THEN
  INSERT INTO diag.data_version_invalidation(data_version_id,event_key,reason,dataset_key,partition_key,new_receipt_id)
  SELECT c.data_version_id,txid_current()::text||':'||NEW.dataset_key||':'||NEW.partition_key,
    'input_head_changed',NEW.dataset_key,NEW.partition_key,coalesce(NEW.basic_receipt_id,NEW.risk_receipt_id)
  FROM diag.data_version_component c WHERE c.dataset_key=OLD.dataset_key AND c.partition_key=OLD.partition_key
  ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.guard_input_write()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 -- Timescale默认关闭chunk DDL事件；仅当前受保护写入事务打开，以覆盖未来chunk。
 -- 官方源码src/chunk.c在DefineRelation前后消费此GUC，不修改数据库全局配置。
 PERFORM set_config('timescaledb.enable_event_triggers','on',true);
 -- 保守按整个数据集失效；row触发器也保护直接写Timescale chunk的路径。
 UPDATE ops.diag_input_head SET dirty=true,revision=revision+1
  WHERE (dataset_key=TG_ARGV[0] OR TG_ARGV[0]='*') AND NOT dirty;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION diag.guard_disabled_run()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' OR TG_OP='UPDATE' THEN
  IF OLD.rule='risk_bundle_publishable' AND OLD.detail->>'publishable'='false' THEN
   RAISE EXCEPTION 'Disabled risk run evidence is immutable' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP<>'DELETE' AND NEW.rule='risk_bundle_publishable' AND NEW.detail->>'publishable'='false' THEN
  PERFORM pg_advisory_xact_lock(7342061105);
  INSERT INTO diag.data_version_invalidation(data_version_id,event_key,reason,dataset_key,partition_key)
  SELECT c.data_version_id,'disabled:'||(NEW.detail->>'factor_model_run_id'),'risk_run_disabled',c.dataset_key,c.partition_key
  FROM diag.data_version_component c WHERE c.run_id::text=NEW.detail->>'factor_model_run_id'
  ON CONFLICT DO NOTHING;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.guard_quality_truncate()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM ops.data_quality_check WHERE rule='risk_bundle_publishable' AND detail->>'publishable'='false') THEN
  RAISE EXCEPTION 'Disabled risk evidence forbids truncate' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION diag.guard_version_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM diag.data_publication WHERE data_version_id=OLD.data_version_id) THEN
  RAISE EXCEPTION 'Published data version is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER diag_immutable_row BEFORE UPDATE OR DELETE ON ops.diag_input_receipt FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_immutable_truncate BEFORE TRUNCATE ON ops.diag_input_receipt FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_immutable_row BEFORE UPDATE OR DELETE ON diag.data_publication FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_immutable_truncate BEFORE TRUNCATE ON diag.data_publication FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_immutable_row BEFORE UPDATE OR DELETE ON diag.data_version_component FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_immutable_truncate BEFORE TRUNCATE ON diag.data_version_component FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_immutable_row BEFORE UPDATE OR DELETE ON diag.data_version_invalidation FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_immutable_truncate BEFORE TRUNCATE ON diag.data_version_invalidation FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_immutable_row BEFORE UPDATE OR DELETE ON factor.risk_run_admission FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_immutable_truncate BEFORE TRUNCATE ON factor.risk_run_admission FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_component_validate BEFORE INSERT ON diag.data_version_component
 FOR EACH ROW EXECUTE FUNCTION diag.validate_component();
CREATE OR REPLACE TRIGGER diag_admission_validate BEFORE INSERT ON factor.risk_run_admission
 FOR EACH ROW EXECUTE FUNCTION diag.validate_admission();
CREATE OR REPLACE TRIGGER diag_head_validate BEFORE INSERT OR UPDATE ON ops.diag_input_head
 FOR EACH ROW EXECUTE FUNCTION diag.validate_head();
CREATE OR REPLACE TRIGGER diag_head_no_delete BEFORE DELETE ON ops.diag_input_head
 FOR EACH ROW EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_head_no_truncate BEFORE TRUNCATE ON ops.diag_input_head
 FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();
CREATE OR REPLACE TRIGGER diag_disabled_run BEFORE INSERT OR UPDATE OR DELETE ON ops.data_quality_check
 FOR EACH ROW EXECUTE FUNCTION diag.guard_disabled_run();
CREATE OR REPLACE TRIGGER diag_disabled_no_truncate BEFORE TRUNCATE ON ops.data_quality_check
 FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_quality_truncate();
CREATE OR REPLACE TRIGGER diag_version_immutable BEFORE UPDATE OR DELETE ON diag.data_version
 FOR EACH ROW EXECUTE FUNCTION diag.guard_version_change();
CREATE OR REPLACE TRIGGER diag_version_no_truncate BEFORE TRUNCATE ON diag.data_version
 FOR EACH STATEMENT EXECUTE FUNCTION diag.reject_publication_change();

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON meta.instruments FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('meta.instruments');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON meta.instruments FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('meta.instruments');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON meta.symbol_map FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('meta.symbol_map');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON meta.symbol_map FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('meta.symbol_map');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON meta.trading_calendar FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('meta.trading_calendar');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON meta.trading_calendar FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('meta.trading_calendar');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON market.stock_bar_1d FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('market.stock_bar_1d');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON market.stock_bar_1d FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('market.stock_bar_1d');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON market.stock_suspend_event FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('market.stock_suspend_event');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON market.stock_suspend_event FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('market.stock_suspend_event');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON market.stock_suspend_coverage FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('market.stock_suspend_coverage');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON market.stock_suspend_coverage FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('market.stock_suspend_coverage');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON fundamental.valuation_1d FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('fundamental.valuation_1d');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON fundamental.valuation_1d FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('fundamental.valuation_1d');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON classify.instrument_category FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('classify.instrument_category');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON classify.instrument_category FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('classify.instrument_category');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON classify.instrument_industry FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('classify.instrument_industry');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON classify.instrument_industry FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('classify.instrument_industry');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON classify.industry_node FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('classify.industry_node');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON classify.industry_node FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('classify.industry_node');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.model_run FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.model_run FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.exposure FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.exposure FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.specific_risk FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.specific_risk FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.covariance FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.covariance FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.factor_return FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.factor_return FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.specific_return FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.specific_return FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.model_run_coverage FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.model_run_coverage FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

COMMENT ON TABLE ops.diag_input_receipt IS '诊断基础数据不可变验收收据，非通用采集协议。';

COMMENT ON TABLE ops.diag_input_head IS '诊断组成当前收据；写入与旧版本失效同事务。';

COMMENT ON TABLE diag.data_publication IS '不可变发布清单头；种子版本无此行，不具生产可用性。';

COMMENT ON TABLE diag.data_version_component IS '固定日期范围、来源收据、run与head修订。';

COMMENT ON TABLE diag.data_version_invalidation IS '追加式失效事件，旧报告产物仍可读取。';

COMMENT ON TABLE factor.risk_run_admission IS '目标日期和精确持仓范围的单日指标准入，不改calibrated。';

CREATE OR REPLACE FUNCTION diag.validate_publication_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE stamp TIMESTAMPTZ;
BEGIN
 PERFORM pg_advisory_xact_lock(7342061105);
 SELECT snapshot_at INTO STRICT stamp FROM diag.data_version WHERE data_version_id=NEW.data_version_id;
 IF NEW.published_at IS DISTINCT FROM stamp OR stamp>clock_timestamp() THEN
  RAISE EXCEPTION 'Publication cutoff differs from data version' USING ERRCODE='23514';
 END IF;
 NEW.created_xid=txid_current();
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION diag.validate_publication_commit()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF NOT diag.publication_is_valid(NEW.data_version_id)
 OR EXISTS(SELECT 1 FROM diag.data_version_component c WHERE c.data_version_id=NEW.data_version_id
  AND (c.coverage_start>NEW.as_of_date OR c.coverage_end<NEW.as_of_date)) THEN
  RAISE EXCEPTION 'Publication components incomplete or invalid at commit' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE TRIGGER diag_publication_insert BEFORE INSERT ON diag.data_publication
 FOR EACH ROW EXECUTE FUNCTION diag.validate_publication_insert();
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='diag.data_publication'::regclass
  AND tgname='diag_publication_commit') THEN
  CREATE CONSTRAINT TRIGGER diag_publication_commit AFTER INSERT ON diag.data_publication
   DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION diag.validate_publication_commit();
 END IF;
END $$;

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON classify.scheme FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('classify.scheme');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON classify.scheme FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('classify.scheme');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.model FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.model FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.definition FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');
CREATE OR REPLACE TRIGGER diag_input_row AFTER INSERT OR UPDATE OR DELETE ON factor.definition FOR EACH ROW EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON factor.model_run_binding FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('factor.risk_bundle');

COMMENT ON COLUMN ops.diag_input_receipt.committed_at IS '收据实际写入时刻，不冒充供应商发布时间。';
COMMENT ON COLUMN ops.diag_input_receipt.coverage_end IS '本组成验收覆盖的末事件日期，含端点。';
COMMENT ON COLUMN ops.diag_input_receipt.coverage_start IS '本组成验收覆盖的起始事件日期。';
COMMENT ON COLUMN ops.diag_input_receipt.dataset_key IS '全限定数据集标识；风险整包统一为factor.risk_bundle。';
COMMENT ON COLUMN ops.diag_input_receipt.evidence IS '不可变来源、验收源码与授权证据。';
COMMENT ON COLUMN ops.diag_input_receipt.importer_version IS '验收或导入源码版本。';
COMMENT ON COLUMN ops.diag_input_receipt.manifest_hash IS '组成收据、范围、日期与选项的规范化SHA256。';
COMMENT ON COLUMN ops.diag_input_receipt.partition_key IS '显式来源分区键，不由到达顺序推断权威版本。';
COMMENT ON COLUMN ops.diag_input_receipt.provider IS '经归属校验的唯一来源。';
COMMENT ON COLUMN ops.diag_input_receipt.quality IS '结构化验收结果，accepted仅为该收据声明范围。';
COMMENT ON COLUMN ops.diag_input_receipt.receipt_id IS '不可变来源收据ID，重放不得改写。';
COMMENT ON COLUMN ops.diag_input_head.basic_receipt_id IS '基础数据收据；与风险收据互斥。';
COMMENT ON COLUMN ops.diag_input_head.dataset_key IS '全限定数据集标识；风险整包统一为factor.risk_bundle。';
COMMENT ON COLUMN ops.diag_input_head.dirty IS '当前数据已变化且未重新验收，禁止发布。';
COMMENT ON COLUMN ops.diag_input_head.partition_key IS '显式来源分区键，不由到达顺序推断权威版本。';
COMMENT ON COLUMN ops.diag_input_head.revision IS 'head本地修订号，仅用于相等性与CAS，不表示供应商先后。';
COMMENT ON COLUMN ops.diag_input_head.risk_receipt_id IS '现有factor.import_receipt风险整包收据。';
COMMENT ON COLUMN ops.diag_input_head.run_id IS '同一风险整包绑定的model_run，不跨run拼接。';
COMMENT ON COLUMN diag.data_publication.as_of_date IS '诊断事件日期，区别于实际发布取数时刻。';
COMMENT ON COLUMN diag.data_publication.contract_version IS '诊断发布契约版本。';
COMMENT ON COLUMN diag.data_publication.created_xid IS '数据库强制写入的创建事务，仅允许本事务追加组成。';
COMMENT ON COLUMN diag.data_publication.data_version_id IS '固定诊断数据版本；旧种子没有publication记录。';
COMMENT ON COLUMN diag.data_publication.manifest_hash IS '组成收据、范围、日期与选项的规范化SHA256。';
COMMENT ON COLUMN diag.data_publication.publication_seq IS '串行屏障内发布的唯一序号，不是供应商观察顺序。';
COMMENT ON COLUMN diag.data_publication.published_at IS '取得写入屏障后固定的实际发布取数截止时刻。';
COMMENT ON COLUMN diag.data_version_component.basic_receipt_id IS '基础数据收据；与风险收据互斥。';
COMMENT ON COLUMN diag.data_version_component.coverage_end IS '本组成验收覆盖的末事件日期，含端点。';
COMMENT ON COLUMN diag.data_version_component.coverage_start IS '本组成验收覆盖的起始事件日期。';
COMMENT ON COLUMN diag.data_version_component.data_version_id IS '固定诊断数据版本；旧种子没有publication记录。';
COMMENT ON COLUMN diag.data_version_component.dataset_key IS '全限定数据集标识；风险整包统一为factor.risk_bundle。';
COMMENT ON COLUMN diag.data_version_component.head_revision IS '发布时固定的head修订号。';
COMMENT ON COLUMN diag.data_version_component.partition_key IS '显式来源分区键，不由到达顺序推断权威版本。';
COMMENT ON COLUMN diag.data_version_component.risk_receipt_id IS '现有factor.import_receipt风险整包收据。';
COMMENT ON COLUMN diag.data_version_component.run_id IS '同一风险整包绑定的model_run，不跨run拼接。';
COMMENT ON COLUMN diag.data_version_invalidation.data_version_id IS '固定诊断数据版本；旧种子没有publication记录。';
COMMENT ON COLUMN diag.data_version_invalidation.dataset_key IS '全限定数据集标识；风险整包统一为factor.risk_bundle。';
COMMENT ON COLUMN diag.data_version_invalidation.event_key IS '幂等失效事件键。';
COMMENT ON COLUMN diag.data_version_invalidation.invalidated_at IS '失效事件实际写入时间，与更新同事务。';
COMMENT ON COLUMN diag.data_version_invalidation.new_receipt_id IS '触发失效的新收据，仅供审计，可能尚无新收据。';
COMMENT ON COLUMN diag.data_version_invalidation.partition_key IS '显式来源分区键，不由到达顺序推断权威版本。';
COMMENT ON COLUMN diag.data_version_invalidation.reason IS '失效的可定位原因。';
COMMENT ON COLUMN factor.risk_run_admission.admission_id IS '目标组合单日指标准入证据ID。';
COMMENT ON COLUMN factor.risk_run_admission.as_of_date IS '诊断事件日期，区别于实际发布取数时刻。';
COMMENT ON COLUMN factor.risk_run_admission.evidence IS '不可变来源、验收源码与授权证据。';
COMMENT ON COLUMN factor.risk_run_admission.factor_order_hash IS '与同run严格一致的因子顺序hash。';
COMMENT ON COLUMN factor.risk_run_admission.metrics IS '本证据已验收指标白名单，不扩为L4等其他指标。';
COMMENT ON COLUMN factor.risk_run_admission.portfolio_hash IS '全部非零证券ID及精确权重规范化SHA256。';
COMMENT ON COLUMN factor.risk_run_admission.receipt_id IS '不可变来源收据ID，重放不得改写。';
COMMENT ON COLUMN factor.risk_run_admission.run_id IS '同一风险整包绑定的model_run，不跨run拼接。';
COMMENT ON COLUMN factor.risk_run_admission.units_evidence IS '供应商单位确认及读库换算证据，不修改calibrated。';

-- 归属变更也是来源身份变化，保守失效所有诊断组成。
CREATE OR REPLACE TRIGGER diag_input_statement BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
 ON ops.table_ownership FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write('*');

CREATE UNIQUE INDEX IF NOT EXISTS diag_publication_one_risk_run
 ON diag.data_version_component(data_version_id) WHERE run_id IS NOT NULL;

-- Timescale的行触发器不会覆盖直接TRUNCATE chunk。对内部普通表保守安装
-- 全组成失效屏障；DDL事件按新建relation OID处理，不依赖尚未登记的chunk目录。
CREATE OR REPLACE FUNCTION diag.protect_new_internal_table()
RETURNS event_trigger LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
 FOR r IN
  SELECT n.nspname,c.relname FROM pg_event_trigger_ddl_commands() d
  JOIN pg_class c ON d.classid='pg_class'::regclass AND c.oid=d.objid
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='_timescaledb_internal' AND c.relkind='r'
 LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER diag_chunk_truncate BEFORE TRUNCATE ON %I.%I '
   'FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write(''*'')',r.nspname,r.relname);
 END LOOP;
END $$;
DO $$
DECLARE r RECORD;
BEGIN
 FOR r IN SELECT n.nspname,c.relname FROM pg_class c
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='_timescaledb_internal' AND c.relkind='r'
 LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER diag_chunk_truncate BEFORE TRUNCATE ON %I.%I '
   'FOR EACH STATEMENT EXECUTE FUNCTION diag.guard_input_write(''*'')',r.nspname,r.relname);
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_event_trigger WHERE evtname='diag_new_internal_table') THEN
  CREATE EVENT TRIGGER diag_new_internal_table ON ddl_command_end WHEN TAG IN ('CREATE TABLE')
   EXECUTE FUNCTION diag.protect_new_internal_table();
 END IF;
END $$;
