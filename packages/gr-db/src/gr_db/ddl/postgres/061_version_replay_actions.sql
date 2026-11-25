-- 将每个来源快照的规范事件与覆盖绑定到原始摘要；历史发布可在新观察入库后重算。
-- 仅原位替换本项目 059/060 已知主键，不移动数据或删除行。
DO $$
DECLARE
    item RECORD;
    existing TEXT[];
BEGIN
    FOR item IN
        SELECT * FROM (VALUES
            ('finance', 'dividend', ARRAY['instrument_id','period_end','implementation_date']),
            ('finance', 'dividend_coverage', ARRAY['instrument_id']),
            ('market', 'stock_delisting', ARRAY['instrument_id','delist_date'])
        ) AS keys(namespace, relation, old_keys)
    LOOP
        SELECT array_agg(a.attname::text ORDER BY k.ordinality) INTO existing
        FROM pg_catalog.pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ordinality)
        JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
        WHERE c.conrelid=format('%I.%I', item.namespace, item.relation)::regclass AND c.contype='p';
        IF existing = item.old_keys THEN
            EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I, ADD PRIMARY KEY (%s,raw_sha256)',
                item.namespace, item.relation, item.relation || '_pkey', array_to_string(existing, ','));
        ELSIF existing IS DISTINCT FROM array_append(item.old_keys, 'raw_sha256') THEN
            RAISE EXCEPTION 'Unexpected replay primary key: %.%', item.namespace, item.relation;
        END IF;
    END LOOP;
END $$;
