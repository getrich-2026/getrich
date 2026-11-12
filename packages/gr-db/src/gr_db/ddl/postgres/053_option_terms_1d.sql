-- 2026-11-08 用户授权：仅保存有逐交易日来源证据的历史参数观察。
-- 当前合约快照保持；观察版本不推断连续有效区间或历史可得时间。
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS meta.option_terms_1d (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day DATE NOT NULL,
    strike NUMERIC(18,4) NOT NULL,
    multiplier NUMERIC(18,4) NOT NULL,
    trading_code VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL,
    observation_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ,
    PRIMARY KEY (instrument_id, trading_day, observation_id),
    CONSTRAINT chk_option_terms_strike CHECK (strike > 0 AND strike <> 'NaN'::numeric),
    CONSTRAINT chk_option_terms_multiplier CHECK (
        multiplier > 0 AND multiplier <> 'NaN'::numeric
    ),
    CONSTRAINT chk_option_terms_source CHECK (source = 'ricequant'),
    CONSTRAINT chk_option_terms_observation CHECK (length(observation_id) > 0),
    CONSTRAINT chk_option_terms_trading_code CHECK (length(trading_code) > 0)
);

CREATE INDEX IF NOT EXISTS idx_option_terms_day
    ON meta.option_terms_1d (instrument_id, trading_day);

COMMENT ON TABLE meta.option_terms_1d IS
    '米筐逐交易日期权历史参数不可变观察；稀疏日期不延展，当前合约快照不覆盖。历史回测和交易用途另行验证可得性。';
COMMENT ON COLUMN meta.option_terms_1d.instrument_id IS '正式库期权身份；每次写入重新核对，不复用隔离库ID。';
COMMENT ON COLUMN meta.option_terms_1d.trading_day IS '源接口明确返回的交易日；不通过前向填充生成。';
COMMENT ON COLUMN meta.option_terms_1d.strike IS '当日行权价；ETF期权单位元／份，来自strike_price。';
COMMENT ON COLUMN meta.option_terms_1d.multiplier IS '当日合约乘数；ETF期权单位份／张，来自contract_multiplier。';
COMMENT ON COLUMN meta.option_terms_1d.trading_code IS '当日交易代码，来自product_name；不是不可变合约身份。';
COMMENT ON COLUMN meta.option_terms_1d.source IS '唯一写入方ricequant；写入前核实ops.table_ownership。';
COMMENT ON COLUMN meta.option_terms_1d.observation_id IS '不可变raw观察标识；同一版本冲突必须停止，不更新已有观察。';
COMMENT ON COLUMN meta.option_terms_1d.observed_at IS '已证实的观察时间；旧样本缺响应完成时间时采用留证的归档时间，并记录时间类型。';
COMMENT ON COLUMN meta.option_terms_1d.available_at IS '源数据在历史当时可获得的时间；没有来源证据时为NULL，不能用observed_at或交易日推定。';
