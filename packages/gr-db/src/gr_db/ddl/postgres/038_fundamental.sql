-- 038_fundamental.sql
-- fundamental schema：估值与财务快照，关闭 getrich-design `持仓诊断_表与接口设计.md`
-- §3 的缺口 G3（市值风格分档、估值风格分档、单标的辅助字段）。
-- DDL 依据该文档 §5.3。
--
-- tushare daily_basic 只落这一张表（2026-10-30 起不再另写 market.stock_daily_basic）：
-- 源字段一个只落一处，单位、口径在 ingest 层一次归一，计算层直接取用不再换算。
-- 完整源行保留在 raw parquet，库内不再用 JSONB 复制一份。

CREATE SCHEMA IF NOT EXISTS fundamental;

-- ---------------------------------------------------------------------------
-- 每日估值快照
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fundamental.valuation_1d (
    instrument_id   BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day     DATE NOT NULL,
    total_mv        NUMERIC(24,4),          -- 单位：元
    circ_mv         NUMERIC(24,4),          -- 单位：元
    pe              NUMERIC(12,4),          -- 无量纲
    pe_ttm          NUMERIC(12,4),          -- 无量纲，TTM 口径
    pb              NUMERIC(12,4),          -- 无量纲
    ps              NUMERIC(12,4),          -- 无量纲
    ps_ttm          NUMERIC(12,4),          -- 无量纲，TTM 口径
    dv_ratio        NUMERIC(12,4),          -- 单位：%
    dv_ttm          NUMERIC(12,4),          -- 单位：%，TTM 口径
    total_share     NUMERIC(24,4),          -- 单位：股
    float_share     NUMERIC(24,4),          -- 单位：股
    free_share      NUMERIC(24,4),          -- 单位：股
    turnover_rate   NUMERIC(18,8),          -- 单位：%
    turnover_rate_f NUMERIC(18,8),          -- 单位：%，自由流通股口径
    volume_ratio    NUMERIC(12,4),          -- 无量纲
    limit_status    SMALLINT,               -- 0–6，源枚举原值
    currency        VARCHAR(8) NOT NULL DEFAULT 'CNY',
    source          VARCHAR(32) NOT NULL,
    available_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day),
    CONSTRAINT chk_valuation_1d_limit_status CHECK (limit_status BETWEEN 0 AND 6),
    CONSTRAINT chk_valuation_1d_shares CHECK (
        (total_share IS NULL OR total_share >= 0)
        AND (float_share IS NULL OR float_share >= 0)
        AND (free_share IS NULL OR free_share >= 0)
    )
);
SELECT create_hypertable('fundamental.valuation_1d', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON COLUMN fundamental.valuation_1d.total_mv IS
    '总市值，单位**元**。tushare daily_basic.total_mv 原始单位是万元，×10000 的换算在 ingest 层一次完成；计算层与文档一律不再临时乘除（指标文档里「大盘 ≥3000 亿」这类阈值以亿元表述，换算只在一处发生）。';
COMMENT ON COLUMN fundamental.valuation_1d.pe_ttm IS
    'TTM 市盈率。亏损股在 tushare 侧返回 NULL，原样保留 —— 用 0 或极大值兜底会让估值分档整体失真。';
COMMENT ON COLUMN fundamental.valuation_1d.pe IS
    '市盈率（总市值／净利润）。亏损股在 tushare 侧返回 NULL，原样保留。';
COMMENT ON COLUMN fundamental.valuation_1d.ps IS '市销率（总市值／最新年报营业收入）。';
COMMENT ON COLUMN fundamental.valuation_1d.ps_ttm IS '市销率，营业收入取 TTM。';
COMMENT ON COLUMN fundamental.valuation_1d.dv_ratio IS
    '股息率，单位 %（百分数原值，未除以 100）；分子为除息日在去年期间的派现。';
COMMENT ON COLUMN fundamental.valuation_1d.dv_ttm IS
    '股息率，单位 %（百分数原值）；分子为除息日在近 12 个月且分红报告期在 12 个月以内的派现。';
COMMENT ON COLUMN fundamental.valuation_1d.total_share IS
    '总股本，单位**股**。tushare 原始单位万股，×10000 在 ingest 层一次完成。';
COMMENT ON COLUMN fundamental.valuation_1d.float_share IS '流通股本，单位股（源单位万股 ×10000）。';
COMMENT ON COLUMN fundamental.valuation_1d.free_share IS '自由流通股本，单位股（源单位万股 ×10000）。';
COMMENT ON COLUMN fundamental.valuation_1d.turnover_rate IS
    '换手率，单位 %（百分数原值，未除以 100），分母为无限售流通股数。';
COMMENT ON COLUMN fundamental.valuation_1d.turnover_rate_f IS
    '换手率，单位 %（百分数原值），分母为自由流通股数。';
COMMENT ON COLUMN fundamental.valuation_1d.volume_ratio IS '量比（当日成交量／过去均量），无量纲。';
COMMENT ON COLUMN fundamental.valuation_1d.limit_status IS
    '收盘涨跌状态，tushare 枚举原值：0 平盘，1 上涨（不含涨停），2 涨停（不含一字），3 一字涨停，4 下跌（不含跌停），5 跌停（不含一字），6 一字跌停。部分代码的旧历史值固定为 0，见 gr-data README。';
COMMENT ON COLUMN fundamental.valuation_1d.available_at IS
    '可用时点。daily_basic 官方 15:00–17:00 更新，取交易日 17:00（**文档值不是实测值**，供应商未给逐行时间戳）。下游一律按 available_at <= 决策时点过滤。';

CREATE INDEX IF NOT EXISTS idx_valuation_1d_trading_day
    ON fundamental.valuation_1d USING BRIN (trading_day);

-- ---------------------------------------------------------------------------
-- 季度财务指标（PIT）
-- ---------------------------------------------------------------------------
-- ann_date 进主键且 NOT NULL，是**防前视的结构性保证**：
-- 取数口径固定为「ann_date <= as_of 过滤后按 end_date 取最新一期，同一 end_date
-- 取最大 ann_date（当时已知的最新修正版）」。
-- 数据源不提供公告日时，该行标记不可用；**禁止用 end_date + N 天推断** ——
-- 那会静默把三四个月后才披露的年报当成报告期当天就能看到。
CREATE TABLE IF NOT EXISTS fundamental.indicator_q (
    instrument_id   BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    end_date        DATE NOT NULL,
    ann_date        DATE NOT NULL,
    roe             NUMERIC(12,6),
    source          VARCHAR(32) NOT NULL,
    source_revision VARCHAR(32),
    available_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, end_date, ann_date)
);

COMMENT ON COLUMN fundamental.indicator_q.roe IS
    '净资产收益率。**口径待定（设计文档 T8）**：单季 vs TTM、小数 vs 百分比都尚未拍板，接 fina_indicator 时必须先定，不得凭 tushare 的默认值直接入库。';
COMMENT ON COLUMN fundamental.indicator_q.ann_date IS
    '公告日，NOT NULL 且进主键。取数按 ann_date <= 决策时点过滤；同一 end_date 有多个 ann_date 时取最大者（财报更正后当时已知的最新版）。';
