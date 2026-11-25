CREATE TABLE IF NOT EXISTS finance.dividend_coverage (
    instrument_id BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    through_date DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL CHECK (source = 'tushare'),
    raw_sha256 TEXT NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (through_date < (observed_at AT TIME ZONE 'Asia/Shanghai')::date)
);
COMMENT ON TABLE finance.dividend_coverage IS 'DS06 按股票请求全历史分红，成功取得末页且核验文件哈希后登记；仅匹配同摘要的事件。从供应商可查询历史到 through_date 的当前视角覆盖，不是当时已观测。';
COMMENT ON COLUMN finance.dividend_coverage.instrument_id IS 'Tushare 全历史请求的单只股票。';
COMMENT ON COLUMN finance.dividend_coverage.through_date IS '保守覆盖截至日，最迟上海观察日期前一个自然日。';
COMMENT ON COLUMN finance.dividend_coverage.observed_at IS '整股请求成功完成时间，必须带时区。';
COMMENT ON COLUMN finance.dividend_coverage.source IS '与 finance.dividend 同源的供应商。';
COMMENT ON COLUMN finance.dividend_coverage.raw_sha256 IS '原始完整股票快照哈希；回放必须匹配事件来源摘要。';
