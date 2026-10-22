-- 同一证券在同一供应商可以有多个历史代码；正向解析仍由主键唯一约束。
-- 保留全部现有记录，仅取消阻止旧代码别名的反向唯一约束。
ALTER TABLE meta.symbol_map
    DROP CONSTRAINT IF EXISTS symbol_map_instrument_id_source_key;

CREATE INDEX IF NOT EXISTS idx_symbol_map_instrument_source
    ON meta.symbol_map (instrument_id, source);

COMMENT ON TABLE meta.symbol_map IS
    '供应商代码到证券身份的映射：(source, source_symbol) 唯一；同一 instrument_id/source 可有多个经证据核实的历史代码。不是历史代码生效区间或 PIT 可得性记录。';
