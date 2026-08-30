-- 039_classify.sql
-- classify schema：行业分类（多套 × 多级）与资产类别，关闭 getrich-design
-- `持仓诊断_表与接口设计.md` §3 的缺口 G1（行业分布/行业归因）与 G5（资产配置分解）。
-- DDL 依据该文档 §5.1。
--
-- 与 `meta.instruments.asset` 的分工：那一列是**品种级**取值
-- （index/future/option/stock/etf/fund），不是资产类别（权益/固收/商品/现金/另类）。
-- 两者不可互相顶替，故单列 `classify.instrument_category`。

CREATE SCHEMA IF NOT EXISTS classify;

-- instrument_industry 的 EXCLUDE 约束要在同一个索引里混用 `=`（标量）与 `&&`
-- （区间），只有 gist 支持，而 gist 不原生支持 bigint/varchar 的等值操作符 ——
-- btree_gist 补的就是这一块。**它不在 001_extensions.sql 里**，必须在这里装。
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- 分类体系
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classify.scheme (
    scheme_code     VARCHAR(32) PRIMARY KEY,   -- 'sw2021' / 'citics' / 'gics'
    scheme_name     VARCHAR(64) NOT NULL,
    max_level       SMALLINT NOT NULL,
    available_level SMALLINT NOT NULL,
    source          VARCHAR(32) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_available_level CHECK (available_level <= max_level)
);

COMMENT ON COLUMN classify.scheme.available_level IS
    '数据源当前实际覆盖到第几级。**体系级声明值，不得当作逐标的的数据质量判据** —— 某标的在该级仍可能缺行，逐标的降级要去 instrument_industry 查有没有对应行。';

-- ---------------------------------------------------------------------------
-- 行业节点维表
-- ---------------------------------------------------------------------------
-- 父子一致性（parent_code 必须存在于 (scheme_code, level-1)）只能由应用层保证：
-- FK 不支持在引用列上做算术，DB 层表达不了 level-1。
CREATE TABLE IF NOT EXISTS classify.industry_node (
    scheme_code   VARCHAR(32) NOT NULL REFERENCES classify.scheme(scheme_code),
    level         SMALLINT NOT NULL,
    industry_code VARCHAR(32) NOT NULL,
    industry_name VARCHAR(128) NOT NULL,
    parent_code   VARCHAR(32),
    external_code VARCHAR(32),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scheme_code, level, industry_code),
    CONSTRAINT chk_level_positive CHECK (level > 0)
);

COMMENT ON COLUMN classify.industry_node.industry_code IS
    '本体系内的行业标识。source=''datayes'' 时它是**通联的英文标识**（如 Banks / NonbankFinan），不是申万官方码。';
COMMENT ON COLUMN classify.industry_node.external_code IS
    '官方码（申万形如 801780.SI），**本轮恒 NULL**：手上没有 datayes 英文标识到申万官方码的权威映射，猜一份写进来会让下游误以为可以直接对接申万发布的成分数据。接到真源后回填。';

-- ---------------------------------------------------------------------------
-- 标的的行业归属（带有效期）
-- ---------------------------------------------------------------------------
-- in_date / out_date 不是可选项：行业分类会调整，回溯归因必须用**当时**的归属，
-- 用最新归属回算历史等于前视偏差。
CREATE TABLE IF NOT EXISTS classify.instrument_industry (
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    scheme_code   VARCHAR(32) NOT NULL,
    level         SMALLINT NOT NULL,
    industry_code VARCHAR(32) NOT NULL,
    in_date       DATE NOT NULL,
    out_date      DATE,                     -- NULL = 当前有效
    valid_range   daterange GENERATED ALWAYS AS
                      (daterange(in_date, out_date, '[)')) STORED,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        VARCHAR(32) NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, scheme_code, level, in_date),
    CONSTRAINT fk_industry FOREIGN KEY (scheme_code, level, industry_code)
        REFERENCES classify.industry_node(scheme_code, level, industry_code),
    CONSTRAINT chk_level_positive CHECK (level > 0),
    CONSTRAINT chk_date_order CHECK (out_date IS NULL OR out_date > in_date),
    -- 同一标的 × 体系 × 级别，区间不得重叠（含「当前有效」的无穷区间）。
    -- 这条是硬约束而不是应用层校验：区间重叠会让「某日属于哪个行业」有两个答案，
    -- 而归因求和照样跑得出来，只是权重被重复计了一遍，静默出错。
    CONSTRAINT excl_no_overlap EXCLUDE USING gist (
        instrument_id WITH =,
        scheme_code WITH =,
        level WITH =,
        valid_range WITH &&
    )
);

CREATE INDEX IF NOT EXISTS idx_industry_current
    ON classify.instrument_industry (scheme_code, level, industry_code)
    WHERE out_date IS NULL;

COMMENT ON COLUMN classify.instrument_industry.in_date IS
    'source=''datayes'' 时**不是真实的行业生效日**，而是该标的在导入窗口内首次出现的交易日 —— 通联的风险模型暴露表只给逐日截面，不给生效日期。区间起点因此被截短到导入窗口起点，2025 年之前的行业归因整体缺行（记 ops.data_quality_check 的 rule=classify_window_truncated）。方向是保守的：不会让历史看到未来的行业，只会看不到更早的历史。';

-- ---------------------------------------------------------------------------
-- 资产类别与市场
-- ---------------------------------------------------------------------------
-- 基金转型、上市地变更也会改分类，但频率远低于行业，因此只用 partial unique
-- index 保「当前唯一」，不叠 EXCLUDE。观察到冲突再升级成与行业表一致的方案。
CREATE TABLE IF NOT EXISTS classify.instrument_category (
    instrument_id  BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    asset_category VARCHAR(16) NOT NULL,
    market         VARCHAR(16) NOT NULL,
    in_date        DATE NOT NULL,
    out_date       DATE,
    available_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source         VARCHAR(32) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, in_date),
    CONSTRAINT chk_asset_category CHECK (asset_category IN
        ('equity', 'fixed_income', 'commodity', 'cash', 'alternative')),
    CONSTRAINT chk_market CHECK (market IN ('cn_a', 'hk', 'us', 'other')),
    CONSTRAINT chk_date_order CHECK (out_date IS NULL OR out_date > in_date)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_current
    ON classify.instrument_category (instrument_id) WHERE out_date IS NULL;

COMMENT ON COLUMN classify.instrument_category.asset_category IS
    '资产类别（权益/固收/商品/现金/另类），由 meta.instruments.asset + 交易所做**纯规则**映射。ETF 一律记 equity：区分股票型与债券型 ETF 需要基金持仓明细（缺口 G4，一期不处理），按名称猜会把债基误判成权益。';
