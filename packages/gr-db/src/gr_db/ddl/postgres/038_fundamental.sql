-- 038_fundamental.sql
-- fundamental schema：估值与财务快照，关闭 getrich-design `持仓诊断_表与接口设计.md`
-- §3 的缺口 G3（市值风格分档、估值风格分档、单标的辅助字段）。
-- DDL 依据该文档 §5.3。
--
-- 与 market.stock_daily_basic 的分工：那张表是 insight 时代的形状（OHLC + 换手
-- + 市值），装不下 tushare daily_basic 的估值口径，多余字段只能进 raw_payload；
-- **这里是面向分析的规整形态**，单位、口径都已经归一，计算层直接取用不再换算。
-- 两张表由同一份 raw parquet 喂，两个 importer，不合并。

CREATE SCHEMA IF NOT EXISTS fundamental;

-- ---------------------------------------------------------------------------
-- 每日估值快照
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fundamental.valuation_1d (
    instrument_id   BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day     DATE NOT NULL,
    total_mv        NUMERIC(24,4),          -- 单位：元
    circ_mv         NUMERIC(24,4),          -- 单位：元
    pb              NUMERIC(12,4),          -- 无量纲
    pe_ttm          NUMERIC(12,4),          -- 无量纲，TTM 口径
    currency        VARCHAR(8) NOT NULL DEFAULT 'CNY',
    fx_as_of        DATE,                   -- currency <> 'CNY' 时非空，港美股接入后启用
    source          VARCHAR(32) NOT NULL,
    source_revision VARCHAR(32),            -- 仅供追溯，不参与查询
    available_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trading_day)
);
SELECT create_hypertable('fundamental.valuation_1d', 'trading_day',
    chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);

COMMENT ON COLUMN fundamental.valuation_1d.total_mv IS
    '总市值，单位**元**。tushare daily_basic.total_mv 原始单位是万元，×10000 的换算在 ingest 层一次完成；计算层与文档一律不再临时乘除（指标文档里「大盘 ≥3000 亿」这类阈值以亿元表述，换算只在一处发生）。';
COMMENT ON COLUMN fundamental.valuation_1d.pe_ttm IS
    'TTM 市盈率。亏损股在 tushare 侧返回 NULL，原样保留 —— 用 0 或极大值兜底会让估值分档整体失真。';
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
