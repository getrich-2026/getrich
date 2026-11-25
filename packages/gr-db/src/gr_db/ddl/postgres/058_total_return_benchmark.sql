-- DS08：按基准身份和数据版本隔离经来源核验的全收益序列。
CREATE TABLE IF NOT EXISTS market.index_total_return_1d (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    version TEXT NOT NULL CHECK (btrim(version) <> ''),
    dt DATE NOT NULL,
    simple_return DOUBLE PRECISION NOT NULL
        CHECK (simple_return >= -1 AND simple_return < 'Infinity'::DOUBLE PRECISION),
    source TEXT NOT NULL CHECK (btrim(source) <> ''),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, version, dt)
);
SELECT create_hypertable('market.index_total_return_1d', 'dt',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON TABLE market.index_total_return_1d IS 'DS08 全收益指数日简单收益；每个版本对应已核验来源快照。';
COMMENT ON COLUMN market.index_total_return_1d.instrument_id IS '全收益指数自身的标的 ID。';
COMMENT ON COLUMN market.index_total_return_1d.version IS '数据发布选项引用的不可变基准版本。';
COMMENT ON COLUMN market.index_total_return_1d.dt IS '收益所属的交易日期。';
COMMENT ON COLUMN market.index_total_return_1d.simple_return IS '全收益指数与上一开市日之比减一，小数；缺口不填。';
COMMENT ON COLUMN market.index_total_return_1d.source IS '来源，与表归属一致。';
COMMENT ON COLUMN market.index_total_return_1d.updated_at IS '本行写入数据库的时间。';
