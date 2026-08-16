-- Provider 归属登记表。
-- 规则：数据库内同一张目标表只能由一个 provider 写入（ingest/stream 写库前校验）。
-- 详见 src/gr_data/common/ownership.py 与 docs/conventions/provider-ownership.md。

CREATE TABLE IF NOT EXISTS ops.table_ownership (
    target     TEXT PRIMARY KEY,            -- 形如 'market.stock_bar_1d'
    provider   VARCHAR(32) NOT NULL,        -- 'yinhe' | 'ricequant' | 'insight'
    channel    VARCHAR(16) NOT NULL DEFAULT 'ingest',  -- 'ingest' | 'stream'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_ownership_channel CHECK (channel IN ('ingest', 'stream')),
    CONSTRAINT chk_ownership_provider CHECK (provider <> '')
);

CREATE INDEX IF NOT EXISTS idx_table_ownership_provider
    ON ops.table_ownership (provider, channel);

COMMENT ON TABLE ops.table_ownership IS
    '目标表 -> 数据源归属。保证单表单一来源；转移归属需显式 force/release。';
