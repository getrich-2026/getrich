-- D-023：稀疏事件独立保存；没有事件与没有采集不能混为一谈。
CREATE TABLE IF NOT EXISTS market.stock_suspend_event (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day DATE NOT NULL,
    suspend_type VARCHAR(1) NOT NULL CHECK (suspend_type IN ('S', 'R')),
    suspend_timing TEXT,
    source_symbol TEXT NOT NULL,
    source VARCHAR(32) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day, suspend_type, source)
);
CREATE INDEX IF NOT EXISTS idx_stock_suspend_event_day
    ON market.stock_suspend_event (trading_day, source);

CREATE TABLE IF NOT EXISTS market.stock_suspend_coverage (
    trading_day DATE NOT NULL,
    source VARCHAR(32) NOT NULL,
    raw_sha256 VARCHAR(64) NOT NULL CHECK (length(raw_sha256) = 64),
    observed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trading_day, source)
);

COMMENT ON TABLE market.stock_suspend_event IS
    '停复牌原始事件，Tushare suspend_d 单一来源；同日 S/R 均保留，不用无价格 bar 承载全天停牌。仅保存当前观察，不宣称历史 PIT。';
COMMENT ON COLUMN market.stock_suspend_event.instrument_id IS '关联 meta.instruments 的股票标的 ID。';
COMMENT ON COLUMN market.stock_suspend_event.trading_day IS 'Asia/Shanghai 下的源 trade_date，事件发生日期；不跨日填充。';
COMMENT ON COLUMN market.stock_suspend_event.suspend_type IS '源事件类型：S 停牌，R 复牌；同日两种事件顺序未知。';
COMMENT ON COLUMN market.stock_suspend_event.suspend_timing IS '源日内停牌时段字符串，保留多个时段；NULL 表示源未提供日内时段，不猜开盘可交易性。';
COMMENT ON COLUMN market.stock_suspend_event.source_symbol IS '供应商原始股票代码，保留交易所后缀。';
COMMENT ON COLUMN market.stock_suspend_event.source IS '单表单源的供应商标识，写入前校验 ops.table_ownership。';
COMMENT ON COLUMN market.stock_suspend_event.observed_at IS '此 raw 分区成功完成的实际观测时间，非供应商发布时间。';
COMMENT ON COLUMN market.stock_suspend_event.updated_at IS '记录最后写库时间；不是事件时间或观测时间。';
COMMENT ON TABLE market.stock_suspend_coverage IS
    '停复牌成功请求的逐日覆盖；合法空响应仍记覆盖。与事件及派生 bar 状态同事务写入，缺覆盖时状态为 UNKNOWN。';
COMMENT ON COLUMN market.stock_suspend_coverage.trading_day IS '成功请求的交易日期；不是按事件存在与否推断的覆盖。';
COMMENT ON COLUMN market.stock_suspend_coverage.source IS '供应商标识，与事件来源一致。';
COMMENT ON COLUMN market.stock_suspend_coverage.raw_sha256 IS '已校验的月分区 Parquet SHA-256，支持追溯，不等同诊断发布版本。';
COMMENT ON COLUMN market.stock_suspend_coverage.observed_at IS '分区成功观测时间，timezone-aware；重抓不回填成历史发布时间。';
COMMENT ON COLUMN market.stock_suspend_coverage.updated_at IS '记录最后写库时间；不是交易日或观测时间。';
COMMENT ON COLUMN market.stock_bar_1d.trading_status IS
    '派生日级交易状态。Tushare 使用 NORMAL/HALTED/INTRADAY_HALTED/UNKNOWN；全天停牌通常无 bar，须结合事件表和日历读取。不能据日级状态推断开盘可买。旧行需重导刷新。';
