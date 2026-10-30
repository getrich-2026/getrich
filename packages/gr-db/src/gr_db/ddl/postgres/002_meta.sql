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

-- 期货合约参数（米筐 all_instruments(type='Future') + get_tick_size 最新快照）。
-- 只存米筐独有的字段：品种、上市／最后交易日、交割信息已由 tushare 写入
-- meta.instruments 与 meta.future_profile，这里不再重复（D-012 一表一源）。
CREATE TABLE IF NOT EXISTS meta.future_contracts (
    instrument_id BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    multiplier    NUMERIC(18,4),
    price_tick    NUMERIC(18,6),
    product       VARCHAR(16),
    margin_rate   NUMERIC(10,6),
    industry_name VARCHAR(64),
    underlying_code VARCHAR(32),
    list_date     DATE,
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_future_contracts_positive CHECK (
        (multiplier IS NULL OR multiplier > 0)
        AND (price_tick IS NULL OR price_tick > 0)
        AND (margin_rate IS NULL OR margin_rate >= 0)
    )
);

COMMENT ON TABLE meta.future_contracts IS
    '期货合约参数（米筐最新快照）：按（交易所、品种、交割年月）与 tushare 身份精确匹配后写入，对不上的不写。不是历史 PIT：最小变动价位、保证金率会调整。';
COMMENT ON COLUMN meta.future_contracts.instrument_id IS '关联 meta.instruments 的期货合约 ID（tushare 登记的身份）。';
COMMENT ON COLUMN meta.future_contracts.multiplier IS '合约乘数（米筐 contract_multiplier），覆盖商品、股指、国债期货。';
COMMENT ON COLUMN meta.future_contracts.price_tick IS '最小变动价位（米筐 get_tick_size），单位同报价单位；最新值。';
COMMENT ON COLUMN meta.future_contracts.product IS '合约种类（米筐 product，如 Commodity／Index／Government）。';
COMMENT ON COLUMN meta.future_contracts.margin_rate IS '最低保证金率（米筐 margin_rate），最新值，不是历史时点保证金。';
COMMENT ON COLUMN meta.future_contracts.industry_name IS '行业分类名称（米筐 industry_name）。';
COMMENT ON COLUMN meta.future_contracts.underlying_code IS
    '合约标的代码（米筐 underlying_order_book_id 原样，仅股指期货有值，如 000300.XSHG）；未解析为 instrument_id。';
COMMENT ON COLUMN meta.future_contracts.list_date IS
    '上市日（米筐 listed_date）。2026-10-30 用户确定期货上市日暂以本列为准；meta.instruments.list_date 保留 tushare 原值作身份与对账，两者不一致时记 future_contracts_list_date_mismatch。';
COMMENT ON COLUMN meta.future_contracts.source IS '写入方 provider；本表只由 ricequant 写入。';
COMMENT ON COLUMN meta.future_contracts.updated_at IS '记录最后更新时间。';

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
    delivery_date   DATE,
    maturity_date   DATE,
    settle_month    VARCHAR(8),
    contract_type   VARCHAR(32),
    trading_code    VARCHAR(64),
    per_unit        NUMERIC(18,4),
    price_tick      NUMERIC(18,6),
    quote_unit      VARCHAR(32),
    list_price      NUMERIC(18,6),
    CONSTRAINT chk_option_type CHECK (option_type IN ('C', 'P')),
    CONSTRAINT chk_option_contract_positive CHECK (
        (per_unit IS NULL OR per_unit > 0)
        AND (price_tick IS NULL OR price_tick > 0)
        AND (list_price IS NULL OR list_price >= 0)
    )
);

COMMENT ON COLUMN meta.option_contracts.delivery_date IS '最后交割日（opt_basic.last_ddate）。';
COMMENT ON COLUMN meta.option_contracts.maturity_date IS '到期日（opt_basic.maturity_date）。';
COMMENT ON COLUMN meta.option_contracts.settle_month IS '结算月（opt_basic.s_month，YYYYMM 文本原样）。';
COMMENT ON COLUMN meta.option_contracts.contract_type IS '合约类型（opt_basic.opt_type，如 ETF期权）。';
COMMENT ON COLUMN meta.option_contracts.trading_code IS '交易所交易代码（opt_basic.symbol），与 ts_code 不同，不可由其推导。';
COMMENT ON COLUMN meta.option_contracts.per_unit IS
    '合约单位（opt_basic.per_unit）。multiplier 取 opt_multiplier（经除权除息调整），两者语义不同，不互相替代。';
COMMENT ON COLUMN meta.option_contracts.price_tick IS '最小价格波幅（opt_basic.min_price_chg），单位同报价单位。';
COMMENT ON COLUMN meta.option_contracts.quote_unit IS '报价单位（opt_basic.quote_unit）。';
COMMENT ON COLUMN meta.option_contracts.list_price IS '挂牌基准价（opt_basic.list_price）。';

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
    -- 股息点指数（如 H30401.CSI）从 0 起算，基点 0 是源语义，不是缺失
    CONSTRAINT chk_index_profile_base_point CHECK (base_point IS NULL OR base_point >= 0)
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
COMMENT ON COLUMN meta.index_profile.base_point IS '基点（源 base_point）。股息点指数为 0。';
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

CREATE TABLE IF NOT EXISTS meta.etf_profile (
    instrument_id    BIGINT PRIMARY KEY REFERENCES meta.instruments(instrument_id),
    fullname         VARCHAR(256),
    short_name       VARCHAR(128),
    channel          VARCHAR(16),
    index_code       VARCHAR(32),
    index_name       VARCHAR(256),
    setup_date       DATE,
    manager          VARCHAR(128),
    manager_fullname VARCHAR(256),
    custodian        VARCHAR(128),
    mgt_fee          NUMERIC(10,4),
    c_fee            NUMERIC(10,4),
    fund_type        VARCHAR(16),
    fund_class       VARCHAR(32),
    invest_type      VARCHAR(64),
    benchmark        TEXT,
    found_date       DATE,
    issue_date       DATE,
    due_date         DATE,
    delist_date      DATE,
    issue_amount     NUMERIC(24,4),
    duration_year    NUMERIC(10,4),
    p_value          NUMERIC(18,4),
    min_amount       NUMERIC(24,4),
    exp_return       NUMERIC(10,4),
    trustee          VARCHAR(128),
    purc_startdate   DATE,
    redm_startdate   DATE,
    source           VARCHAR(32) NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE meta.etf_profile IS
    'ETF 档案（tushare etf_basic 与场内 fund_basic 最新快照，按 ts_code 精确连接）：classify.instrument_category 的分类依据。fund_basic 未匹配的 ETF 其 fund_* 列为 NULL。不是历史 PIT。';
COMMENT ON COLUMN meta.etf_profile.instrument_id IS '关联 meta.instruments 的 ETF ID。';
COMMENT ON COLUMN meta.etf_profile.fullname IS '基金中文全称（etf_basic.cname）。';
COMMENT ON COLUMN meta.etf_profile.short_name IS 'ETF 中文简称（etf_basic.csname）；交易所扩位简称在 meta.instruments.name。';
COMMENT ON COLUMN meta.etf_profile.channel IS '投资通道（etf_basic.etf_type，如 纯境内／QDII）。只有「纯境内」可确定为 cn_a 市场。';
COMMENT ON COLUMN meta.etf_profile.index_code IS '基准指数代码（etf_basic.index_code，源代码原样，未解析为 instrument_id）。';
COMMENT ON COLUMN meta.etf_profile.index_name IS '基准指数中文全称（etf_basic.index_name）。';
COMMENT ON COLUMN meta.etf_profile.setup_date IS '设立日期（etf_basic.setup_date）。';
COMMENT ON COLUMN meta.etf_profile.manager IS '基金管理人简称（etf_basic.mgr_name）。';
COMMENT ON COLUMN meta.etf_profile.manager_fullname IS '基金管理人全称（fund_basic.management）。';
COMMENT ON COLUMN meta.etf_profile.custodian IS '基金托管人名称（etf_basic.custod_name）。';
COMMENT ON COLUMN meta.etf_profile.mgt_fee IS '管理费（etf_basic.mgt_fee 源值原样，官方未注明单位）。';
COMMENT ON COLUMN meta.etf_profile.c_fee IS '托管费（fund_basic.c_fee 源值原样，官方未注明单位）。';
COMMENT ON COLUMN meta.etf_profile.fund_type IS '投资类型（fund_basic.fund_type，如 股票型／债券型／货币型／其他）。资产类别映射的唯一依据。';
COMMENT ON COLUMN meta.etf_profile.fund_class IS '基金类型（fund_basic.type）。';
COMMENT ON COLUMN meta.etf_profile.invest_type IS '投资风格（fund_basic.invest_type）。';
COMMENT ON COLUMN meta.etf_profile.benchmark IS '业绩比较基准（fund_basic.benchmark，文本原样）。';
COMMENT ON COLUMN meta.etf_profile.found_date IS '成立日期（fund_basic.found_date）。';
COMMENT ON COLUMN meta.etf_profile.issue_date IS '发行日期（fund_basic.issue_date）。';
COMMENT ON COLUMN meta.etf_profile.due_date IS '到期日期（fund_basic.due_date）。';
COMMENT ON COLUMN meta.etf_profile.delist_date IS '退市日期（fund_basic.delist_date）。etf_basic 无退市日，meta.instruments.delist_date 对 ETF 为 NULL。';
COMMENT ON COLUMN meta.etf_profile.issue_amount IS '发行份额，单位**份**（fund_basic.issue_amount 源单位亿份，×1e8 在 ingest 层完成）。';
COMMENT ON COLUMN meta.etf_profile.duration_year IS '存续期，单位年（fund_basic.duration_year）。';
COMMENT ON COLUMN meta.etf_profile.p_value IS '面值（fund_basic.p_value）。';
COMMENT ON COLUMN meta.etf_profile.min_amount IS '起点金额，单位**元**（fund_basic.min_amount 源单位万元，×10000 在 ingest 层完成）。';
COMMENT ON COLUMN meta.etf_profile.exp_return IS '预期收益率（fund_basic.exp_return 源值原样）。';
COMMENT ON COLUMN meta.etf_profile.trustee IS '受托人（fund_basic.trustee）。';
COMMENT ON COLUMN meta.etf_profile.purc_startdate IS '日常申购起始日（fund_basic.purc_startdate）。';
COMMENT ON COLUMN meta.etf_profile.redm_startdate IS '日常赎回起始日（fund_basic.redm_startdate）。';
COMMENT ON COLUMN meta.etf_profile.source IS '写入方 provider；本表只由 tushare 写入。';
COMMENT ON COLUMN meta.etf_profile.updated_at IS '记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_symbol_map_instrument_source
    ON meta.symbol_map (instrument_id, source);

COMMENT ON TABLE meta.symbol_map IS
    '供应商代码到证券身份的映射：(source, source_symbol) 唯一；同一 instrument_id/source 可有多个经证据核实的历史代码。不是历史代码生效区间或 PIT 可得性记录。';
