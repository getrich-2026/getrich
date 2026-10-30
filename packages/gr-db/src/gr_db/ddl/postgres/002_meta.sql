-- Metadata layer.

CREATE TABLE IF NOT EXISTS meta.instruments (
    instrument_id BIGSERIAL PRIMARY KEY,
    symbol        VARCHAR(64) NOT NULL,
    asset         VARCHAR(16) NOT NULL,
    exchange      VARCHAR(16) NOT NULL,
    name          VARCHAR(128),
    list_date     DATE,
    delist_date   DATE,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset, exchange, symbol),
    CONSTRAINT chk_instruments_asset
        CHECK (asset IN ('index', 'future', 'option', 'stock', 'etf', 'fund')),
    CONSTRAINT chk_instruments_symbol_not_blank
        CHECK (btrim(symbol) <> ''),
    CONSTRAINT chk_instruments_exchange_not_blank
        CHECK (btrim(exchange) <> '')
);

CREATE INDEX IF NOT EXISTS idx_instruments_asset_exchange_status
    ON meta.instruments (asset, exchange, status);

CREATE TABLE IF NOT EXISTS meta.symbol_map (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    source        VARCHAR(32) NOT NULL,
    source_symbol VARCHAR(128) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_symbol),
    CONSTRAINT chk_symbol_map_source_not_blank
        CHECK (btrim(source) <> ''),
    CONSTRAINT chk_symbol_map_symbol_not_blank
        CHECK (btrim(source_symbol) <> '')
);

CREATE TABLE IF NOT EXISTS meta.trading_calendar (
    exchange          VARCHAR(16) NOT NULL,
    trading_day       DATE NOT NULL,
    is_open           BOOLEAN NOT NULL DEFAULT true,
    has_night         BOOLEAN NOT NULL DEFAULT false,
    prev_trading_day  DATE,
    next_trading_day  DATE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, trading_day),
    CONSTRAINT chk_calendar_exchange_not_blank
        CHECK (btrim(exchange) <> ''),
    CONSTRAINT chk_calendar_prev_before
        CHECK (prev_trading_day IS NULL OR prev_trading_day < trading_day),
    CONSTRAINT chk_calendar_next_after
        CHECK (next_trading_day IS NULL OR next_trading_day > trading_day)
);

CREATE INDEX IF NOT EXISTS idx_trading_calendar_open
    ON meta.trading_calendar (exchange, is_open, trading_day);

CREATE TABLE IF NOT EXISTS meta.future_contracts (
    instrument_id   BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    underlying      VARCHAR(64),
    multiplier      NUMERIC(18,4),
    price_tick      NUMERIC(18,6),
    list_date       DATE,
    last_trade_date DATE,
    delivery_date   DATE
);

CREATE TABLE IF NOT EXISTS meta.option_contracts (
    instrument_id   BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    underlying_id   BIGINT REFERENCES meta.instruments(instrument_id),
    option_type     CHAR(1) NOT NULL,
    exercise_style  VARCHAR(16),
    strike          NUMERIC(18,4) NOT NULL,
    multiplier      NUMERIC(18,4),
    list_date       DATE,
    last_trade_date DATE,
    exercise_date   DATE,
    CONSTRAINT chk_option_type CHECK (option_type IN ('C', 'P'))
);

CREATE INDEX IF NOT EXISTS idx_option_contracts_underlying
    ON meta.option_contracts (underlying_id);

-- ---------------------------------------------------------------------------
-- 标的档案：tushare 主数据接口里 meta.instruments 放不下的描述性字段
-- ---------------------------------------------------------------------------
-- 一张表一个 provider（D-012）；每个源字段只落一处，与 meta.instruments 同义的
-- 字段（名称、上市／退市日、状态）不在这里重复。全部是**最新快照**，不是历史 PIT：
-- 行业、沪深港通、实控人等会随时间变化，回测不能拿它当历史时点的属性。
CREATE TABLE IF NOT EXISTS meta.stock_profile (
    instrument_id BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    fullname      VARCHAR(256),
    enname        VARCHAR(256),
    cnspell       VARCHAR(32),
    area          VARCHAR(32),
    industry      VARCHAR(64),
    board         VARCHAR(16),
    is_hs         CHAR(1),
    currency      VARCHAR(8),
    act_name      VARCHAR(256),
    act_ent_type  VARCHAR(64),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_stock_profile_is_hs CHECK (is_hs IN ('N', 'H', 'S'))
);

COMMENT ON TABLE meta.stock_profile IS
    '股票档案（tushare stock_basic 最新快照）：与 meta.instruments 一对一，只存其放不下的描述性字段。不是历史 PIT。';
COMMENT ON COLUMN meta.stock_profile.instrument_id IS '关联 meta.instruments 的股票 ID。';
COMMENT ON COLUMN meta.stock_profile.fullname IS '股票全称（源 fullname）。';
COMMENT ON COLUMN meta.stock_profile.enname IS '英文全称（源 enname）。';
COMMENT ON COLUMN meta.stock_profile.cnspell IS '拼音缩写（源 cnspell）。';
COMMENT ON COLUMN meta.stock_profile.area IS '地域（源 area）。';
COMMENT ON COLUMN meta.stock_profile.industry IS
    '所属行业（源 industry，tushare 自有口径的最新值）。不是 SW2021 行业，也不是历史归属；行业归属见 classify.instrument_industry。';
COMMENT ON COLUMN meta.stock_profile.board IS '市场板块（源 market：主板／创业板／科创板／CDR／北交所）。';
COMMENT ON COLUMN meta.stock_profile.is_hs IS '沪深港通标的（源 is_hs）：N 否，H 沪股通，S 深股通。最新值。';
COMMENT ON COLUMN meta.stock_profile.currency IS '交易货币（源 curr_type）。';
COMMENT ON COLUMN meta.stock_profile.act_name IS '实际控制人名称（源 act_name），最新值。';
COMMENT ON COLUMN meta.stock_profile.act_ent_type IS '实际控制人企业性质（源 act_ent_type），最新值。';
COMMENT ON COLUMN meta.stock_profile.source IS '写入方 provider；本表只由 tushare 写入。';
COMMENT ON COLUMN meta.stock_profile.updated_at IS '记录最后更新时间。';

CREATE TABLE IF NOT EXISTS meta.index_profile (
    instrument_id  BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    fullname       VARCHAR(256),
    publish_market VARCHAR(16),
    publisher      VARCHAR(128),
    index_type     VARCHAR(64),
    category       VARCHAR(64),
    base_date      DATE,
    base_point     NUMERIC(18,4),
    weight_rule    VARCHAR(128),
    description    TEXT,
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_index_profile_base_point CHECK (base_point IS NULL OR base_point > 0)
);

COMMENT ON TABLE meta.index_profile IS
    '指数档案（tushare index_basic 最新快照）：与 meta.instruments 一对一，只存其放不下的描述性字段。';
COMMENT ON COLUMN meta.index_profile.instrument_id IS '关联 meta.instruments 的指数 ID。';
COMMENT ON COLUMN meta.index_profile.fullname IS '指数全称（源 fullname）。';
COMMENT ON COLUMN meta.index_profile.publish_market IS
    '交易所或服务商代码（源 market，如 SSE／SZSE／CSI／MSCI）。是 tushare 的指数归属口径，不是 canonical 交易所码。';
COMMENT ON COLUMN meta.index_profile.publisher IS '发布方（源 publisher）。';
COMMENT ON COLUMN meta.index_profile.index_type IS '指数风格（源 index_type）。';
COMMENT ON COLUMN meta.index_profile.category IS '指数类别（源 category，如规模指数）。';
COMMENT ON COLUMN meta.index_profile.base_date IS '基期（源 base_date）。';
COMMENT ON COLUMN meta.index_profile.base_point IS '基点（源 base_point）。';
COMMENT ON COLUMN meta.index_profile.weight_rule IS '加权方式（源 weight_rule）。';
COMMENT ON COLUMN meta.index_profile.description IS '指数描述（源 desc）。';
COMMENT ON COLUMN meta.index_profile.source IS '写入方 provider；本表只由 tushare 写入。';
COMMENT ON COLUMN meta.index_profile.updated_at IS '记录最后更新时间。';

CREATE TABLE IF NOT EXISTS meta.future_profile (
    instrument_id   BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    product_code    VARCHAR(16),
    trade_unit      VARCHAR(16),
    per_unit        NUMERIC(18,4),
    quote_unit      VARCHAR(32),
    quote_unit_desc VARCHAR(128),
    delivery_mode   VARCHAR(64),
    delivery_month  VARCHAR(8),
    delivery_date   DATE,
    trade_time_desc TEXT,
    source          VARCHAR(32) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_future_profile_per_unit CHECK (per_unit IS NULL OR per_unit > 0)
);

COMMENT ON TABLE meta.future_profile IS
    '期货档案（tushare fut_basic 最新快照）：交易单位、报价与交割信息。合约乘数与最小变动价位在 meta.future_contracts（米筐），两张表各由一个 provider 写入。';
COMMENT ON COLUMN meta.future_profile.instrument_id IS '关联 meta.instruments 的期货合约 ID。';
COMMENT ON COLUMN meta.future_profile.product_code IS '合约产品代码（源 fut_code，如 CU、IF）。';
COMMENT ON COLUMN meta.future_profile.trade_unit IS '交易计量单位（源 trade_unit，如 吨）。';
COMMENT ON COLUMN meta.future_profile.per_unit IS
    '每手交易单位数量（源 per_unit），单位见 trade_unit。不是合约乘数：股指、国债期货的乘数口径不同，乘数以 meta.future_contracts.multiplier 为准。';
COMMENT ON COLUMN meta.future_profile.quote_unit IS '报价单位（源 quote_unit，如 人民币元/吨）。';
COMMENT ON COLUMN meta.future_profile.quote_unit_desc IS '最小报价单位说明（源 quote_unit_desc，文本原样，不解析成数值）。';
COMMENT ON COLUMN meta.future_profile.delivery_mode IS '交割方式说明（源 d_mode_desc）。';
COMMENT ON COLUMN meta.future_profile.delivery_month IS '交割月份（源 d_month，YYYYMM 文本原样）。';
COMMENT ON COLUMN meta.future_profile.delivery_date IS '最后交割日（源 last_ddate）。';
COMMENT ON COLUMN meta.future_profile.trade_time_desc IS '交易时间说明（源 trade_time_desc，文本原样）。';
COMMENT ON COLUMN meta.future_profile.source IS '写入方 provider；本表只由 tushare 写入。';
COMMENT ON COLUMN meta.future_profile.updated_at IS '记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_symbol_map_instrument_source
    ON meta.symbol_map (instrument_id, source);

COMMENT ON TABLE meta.symbol_map IS
    '供应商代码到证券身份的映射：(source, source_symbol) 唯一；同一 instrument_id/source 可有多个经证据核实的历史代码。不是历史代码生效区间或 PIT 可得性记录。';
