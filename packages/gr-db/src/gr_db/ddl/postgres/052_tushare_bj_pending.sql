-- 2026-10-31 用户授权：仅 .BJ 行级校验失败转待处理，不阻断其他合格记录。
-- 行情仍由原目标表承载，待处理保留供应商原始值与批次，raw 不改。
CREATE TABLE IF NOT EXISTS ops.tushare_bj_pending (
    pending_id          BIGSERIAL PRIMARY KEY,
    source              VARCHAR(32) NOT NULL DEFAULT 'tushare',
    dataset             VARCHAR(64) NOT NULL,
    source_dataset      VARCHAR(64) NOT NULL,
    source_code         VARCHAR(64) NOT NULL,
    source_date         TEXT,
    trading_day         DATE,
    raw_partition       VARCHAR(7) NOT NULL,
    batch_id            VARCHAR(128) NOT NULL,
    record_fingerprint  CHAR(64) NOT NULL,
    raw_row_index       BIGINT NOT NULL,
    failure_rules       TEXT[] NOT NULL,
    failure_detail      TEXT NOT NULL,
    raw_values          JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tushare_bj_pending_record
        UNIQUE (source, dataset, batch_id, record_fingerprint),
    CONSTRAINT chk_tushare_bj_pending_source CHECK (source = 'tushare'),
    CONSTRAINT chk_tushare_bj_pending_code CHECK (source_code LIKE '%.BJ'),
    CONSTRAINT chk_tushare_bj_pending_rules CHECK (cardinality(failure_rules) > 0),
    CONSTRAINT chk_tushare_bj_pending_partition CHECK (raw_partition ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
);

COMMENT ON TABLE ops.tushare_bj_pending IS
    'Tushare 北交所行级校验失败待处理。合格行继续写各自主表，沪深失败仍停止；与主表同事务，raw 原样保留。';
COMMENT ON COLUMN ops.tushare_bj_pending.pending_id IS '待处理记录标识。';
COMMENT ON COLUMN ops.tushare_bj_pending.source IS '供应商，固定 tushare，写入前校验单表单一来源。';
COMMENT ON COLUMN ops.tushare_bj_pending.dataset IS '失败记录拟写入的数据集，对应原 importer。';
COMMENT ON COLUMN ops.tushare_bj_pending.source_dataset IS '供应商原始数据集，例如 daily、adj_factor、daily_basic、suspend_d。';
COMMENT ON COLUMN ops.tushare_bj_pending.source_code IS '原始完整代码，仅允许 .BJ 后缀，保留前导零。';
COMMENT ON COLUMN ops.tushare_bj_pending.source_date IS '供应商原始日期文本；非法日期同样留存，不补造交易日。';
COMMENT ON COLUMN ops.tushare_bj_pending.trading_day IS '可解析的供应商交易日，非法日期为 NULL。';
COMMENT ON COLUMN ops.tushare_bj_pending.raw_partition IS '原始文件所在自然月 YYYY-MM，不随行内非法日期漂移。';
COMMENT ON COLUMN ops.tushare_bj_pending.batch_id IS '调用方批次号；历史回补固定为任务名加月份。';
COMMENT ON COLUMN ops.tushare_bj_pending.record_fingerprint IS '原始分区、行序及完整源值的 SHA-256；相同批次重导幂等，不按代码日期整组覆盖。';
COMMENT ON COLUMN ops.tushare_bj_pending.raw_row_index IS '原分区内从零开始的行序，用于区分同代码同日的多条观察。';
COMMENT ON COLUMN ops.tushare_bj_pending.failure_rules IS '该条观察触发的校验规则，不将文件、连接或程序错误降格为行级失败。';
COMMENT ON COLUMN ops.tushare_bj_pending.failure_detail IS '失败详情，不包含凭证或环境配置。';
COMMENT ON COLUMN ops.tushare_bj_pending.raw_values IS '原始行及必要辅助观察；NaN/Inf 用文字标记保留，不静默变 NULL。';
COMMENT ON COLUMN ops.tushare_bj_pending.created_at IS '记录创建时间。';
COMMENT ON COLUMN ops.tushare_bj_pending.updated_at IS '记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_tushare_bj_pending_batch
    ON ops.tushare_bj_pending (batch_id, raw_partition, source_code);
