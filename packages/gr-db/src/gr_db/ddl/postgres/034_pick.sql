-- 034_pick.sql
-- 选股信号（个股推荐）P0 存储层：pick.batch（上传批次）+ pick.item（标的池条目）。
--
-- 设计依据：getrich-design/strategy-signal/个股推荐_数据库设计_P0.md §3。
-- 语义要点（改这张表前必须先读，否则会破坏未来的派生能力）：
--
--   1. **全量快照**：每个交易日一行完整池子，不存增量。出池即不写行。
--      未来的「今日新增/剔除」「持仓区间」「效果跟踪」全靠这条语义回算；
--      改成增量后那段历史补不回来。
--   2. `item_count = 0` 合法，表示基金经理确认当日空仓 —— 与「当日没上传」
--      （压根没有 batch 行）是两件事，前端文案必须区分。这是保留 batch 表
--      而不是把批次信息塞进条目表的主要理由。
--   3. 主键用上传方给的 `symbol + exchange` 而不是 `instrument_id`：
--      映射会因新股未同步、退市摘牌等原因失败，但基金经理提交的池子是
--      有效业务数据，不该因为数据层没同步就整条丢掉。
--
-- 与设计文档的三处偏差（已确认，理由见 DECISIONS.md）：
--   a. `strategy_id` 用 UUID —— 文档暂写 VARCHAR(32)，实际 app.strategies.id 是 UUID。
--   b. `import_job_id` 保留列但**不建外键**，`chk_batch_job` 也不建 ——
--      本仓根本没有 import_jobs 表的 DDL，P0 走函数/CLI 导入，没有 job 可挂。
--   c. `uploaded_by` 可空 UUID —— CLI 导入时没有登录用户。
--
-- schema 全限定：`pick` **不在**连接池的 search_path（app,market,meta,public）里，
-- 所有业务 SQL 必须显式写 `pick.` 前缀，与 `backtest.` 同一处置。

CREATE SCHEMA IF NOT EXISTS pick;

COMMENT ON SCHEMA pick IS
    '选股信号（个股推荐）：上传批次与每日标的池快照。归属包 gr-api。';

-- ---------------------------------------------------------------------------
-- pick.batch —— 一次上传 = 一个策略某一交易日的完整池子
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pick.batch (
    batch_id        BIGSERIAL   PRIMARY KEY,
    strategy_id     UUID        NOT NULL REFERENCES app.strategies(id),
    trading_day     DATE        NOT NULL,                   -- 池子归属的交易日

    source          VARCHAR(16) NOT NULL DEFAULT 'upload',  -- 'upload'=外部导入 / 'system'=未来系统内生产
    uploaded_by     UUID        REFERENCES app.users(id),   -- 操作者；CLI 导入时为 NULL
    import_job_id   UUID,                                   -- 预留：接入 /v1/admin/imports 后指向 import_jobs.id

    item_count      INT         NOT NULL DEFAULT 0,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',  -- 'active' / 'superseded'

    note            TEXT,                                   -- 基金经理备注，或系统追加的提示
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_batch_source CHECK (source IN ('upload', 'system')),
    CONSTRAINT chk_batch_status CHECK (status IN ('active', 'superseded')),
    CONSTRAINT chk_batch_count  CHECK (item_count >= 0)
);

COMMENT ON TABLE pick.batch IS
    '选股标的池的上传批次：幂等锚点与审计入口。同一策略同一交易日只允许一个 active 批次。';
COMMENT ON COLUMN pick.batch.item_count IS
    '本期标的数。0 表示确认空仓（前端显示「本期无符合条件的标的」），与「无 batch 行」（「今日数据未更新」）语义不同。';
COMMENT ON COLUMN pick.batch.import_job_id IS
    '预留列。本仓尚无 import_jobs 表的 DDL，因此不建外键；接入管理后台上传通道时再补 FK。';

-- 同一策略同一交易日只允许一个生效批次；重传时旧批次先置 superseded。
CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_active
    ON pick.batch (strategy_id, trading_day)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_batch_strategy_day
    ON pick.batch (strategy_id, trading_day DESC);

-- ---------------------------------------------------------------------------
-- pick.item —— 标的池条目
-- ---------------------------------------------------------------------------
--
-- 期货 / 期权字段（asset_class / direction / option_type / product_code /
-- product_entry_date）在 P0 就建好，解析规则等真正接入时再补 —— 建列成本为零，
-- 事后加列并回刷历史的成本很高。P0 股票场景：asset_class 恒为 'stock'、
-- direction 恒为 'long'、option_type 恒为 NULL、product_code 等于 symbol。

CREATE TABLE IF NOT EXISTS pick.item (
    strategy_id     UUID        NOT NULL REFERENCES app.strategies(id),
    trading_day     DATE        NOT NULL,
    symbol          VARCHAR(32) NOT NULL,                   -- 不含后缀的证券代码 / 合约代码
    exchange        VARCHAR(16) NOT NULL,                   -- SSE/SZSE/BSE + 六大期货交易所

    batch_id        BIGINT      NOT NULL REFERENCES pick.batch(batch_id),

    asset_class     VARCHAR(16) NOT NULL,                   -- stock / etf / future / option
    product_code    VARCHAR(32) NOT NULL,                   -- 品种代码；股票 ETF 等于 symbol
    direction       VARCHAR(8)  NOT NULL DEFAULT 'long',    -- 买卖动作，**不是**市场观点
    option_type     CHAR(1),                                -- 'C'/'P'，仅期权非空

    symbol_name     VARCHAR(64),                            -- 快照时点名称，更名后不回溯修改
    instrument_id   BIGINT,                                 -- 对齐 meta.instruments；映射失败为 NULL

    entry_date          DATE        NOT NULL,               -- 当前证券/合约的入池日
    entry_date_source   VARCHAR(16) NOT NULL,               -- 'provided' 上传方给 / 'derived' 系统推算
    product_entry_date  DATE        NOT NULL,               -- 品种级入池日，跨换月连续

    rank            INT,                                    -- 推荐排名；留空即 NULL，系统不按行序推断
    score           NUMERIC(18,8),                          -- 策略评分；量纲自定，跨策略不可比
    suggest_weight  NUMERIC(9,8),                           -- 建议权重，小数不是百分数
    reason_text     TEXT,                                   -- 入选理由

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (strategy_id, trading_day, symbol, exchange),
    CONSTRAINT chk_item_entry_date    CHECK (entry_date <= trading_day),
    CONSTRAINT chk_item_prod_entry    CHECK (product_entry_date <= entry_date),
    CONSTRAINT chk_item_entry_source  CHECK (entry_date_source IN ('provided', 'derived')),
    CONSTRAINT chk_item_asset_class   CHECK (asset_class IN ('stock', 'etf', 'future', 'option')),
    CONSTRAINT chk_item_direction     CHECK (direction IN ('long', 'short')),
    CONSTRAINT chk_item_option_type   CHECK (
        (asset_class =  'option' AND option_type IN ('C', 'P')) OR
        (asset_class <> 'option' AND option_type IS NULL)
    ),
    CONSTRAINT chk_item_exchange      CHECK (exchange IN (
        'SSE', 'SZSE', 'BSE',
        'CFFEX', 'SHFE', 'INE', 'DCE', 'CZCE', 'GFEX'
    )),
    CONSTRAINT chk_item_product_code  CHECK (btrim(product_code) <> ''),
    CONSTRAINT chk_item_rank          CHECK (rank IS NULL OR rank >= 1),
    CONSTRAINT chk_item_weight        CHECK (
        suggest_weight IS NULL OR (suggest_weight >= 0 AND suggest_weight <= 1)
    )
);

COMMENT ON TABLE pick.item IS
    '选股标的池的每日全量快照。出池即不写行，不存增量 —— 派生能力（新增/剔除、持仓区间、效果跟踪）全靠这条语义回算。';
COMMENT ON COLUMN pick.item.exchange IS
    '交易所码用 SSE/SZSE/BSE（对齐前端接口契约），与数据层 meta.* 的 canonical 码 XSHG/XSHE/XBSE 不同，转换见 gr_api/services/pick_symbols.py。';
COMMENT ON COLUMN pick.item.direction IS
    '买卖动作，不是市场观点。卖出认沽（short + P）是看涨头寸 —— 接入期权时最容易整批填反的地方。';
COMMENT ON COLUMN pick.item.product_entry_date IS
    '品种级入池日，跨换月连续。推算时兜底值取 entry_date 而非 trading_day，否则「首次入池 + 上传方给了更早的 entry_date」会违反 chk_item_prod_entry 导致整批插入失败。';
COMMENT ON COLUMN pick.item.score IS
    '策略评分，各策略量纲自定，**跨策略不可比**。P0 采集但不通过接口返回；启用展示前需先补 score_percentile 并声明取值范围。';

CREATE INDEX IF NOT EXISTS idx_item_strategy_day
    ON pick.item (strategy_id, trading_day DESC);
-- 支撑「这个标的被哪些策略选过」的反查
CREATE INDEX IF NOT EXISTS idx_item_symbol
    ON pick.item (symbol, exchange, trading_day DESC);
-- 支撑品种级入池日推算（换月后仍能找到同品种的上一条）
CREATE INDEX IF NOT EXISTS idx_item_product
    ON pick.item (strategy_id, product_code, trading_day DESC);
CREATE INDEX IF NOT EXISTS idx_item_batch
    ON pick.item (batch_id);
