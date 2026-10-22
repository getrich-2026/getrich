-- D-024：涨跌停价的状态，区分「当日不设涨跌幅」与「涨跌停价未知」（DS05、PA-12）。
-- 供应商用哨兵值表示不设涨跌幅（如新股上市初期），不能当真实价格写入 limit_up/limit_down。
-- 列可空、无默认值：045 之前写入的行与其他供应商写入的行为 NULL（未评估），不改写既有行。
ALTER TABLE market.stock_bar_1d
    ADD COLUMN IF NOT EXISTS price_limit_status VARCHAR(16);

-- 约束幂等：按 pg_constraint 判断是否已存在（沿用 033 的写法）。
-- 已有行的状态均为 NULL，添加时的校验必然通过。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_stock_1d_price_limit_status'
          AND conrelid = 'market.stock_bar_1d'::regclass
    ) THEN
        ALTER TABLE market.stock_bar_1d
            ADD CONSTRAINT chk_stock_1d_price_limit_status
            CHECK (
                price_limit_status IS NULL
                OR price_limit_status IN ('LIMITED', 'NO_LIMIT', 'UNKNOWN')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_stock_1d_price_limit_consistency'
          AND conrelid = 'market.stock_bar_1d'::regclass
    ) THEN
        ALTER TABLE market.stock_bar_1d
            ADD CONSTRAINT chk_stock_1d_price_limit_consistency
            CHECK (
                (price_limit_status IS DISTINCT FROM 'LIMITED'
                    OR (limit_up IS NOT NULL AND limit_down IS NOT NULL))
                AND (price_limit_status IS DISTINCT FROM 'NO_LIMIT'
                    OR (limit_up IS NULL AND limit_down IS NULL))
            );
    END IF;
END
$$;

COMMENT ON COLUMN market.stock_bar_1d.price_limit_status IS
    '涨跌停价状态。LIMITED：当日有涨跌幅限制，limit_up/limit_down 均有效；NO_LIMIT：当日不设涨跌幅（供应商哨兵值已写为 NULL）；UNKNOWN：涨跌停价缺失、非法或不可信，可保留单边有效值；NULL：未评估（045 之前写入或其他供应商）。回放判断开盘是否达到涨停价时须区分 NO_LIMIT 与 UNKNOWN。';
COMMENT ON CONSTRAINT chk_stock_1d_price_limit_status ON market.stock_bar_1d IS
    'price_limit_status 只允许 LIMITED/NO_LIMIT/UNKNOWN 或 NULL（未评估）。';
COMMENT ON CONSTRAINT chk_stock_1d_price_limit_consistency ON market.stock_bar_1d IS
    'LIMITED 要求两侧涨跌停价都有值；NO_LIMIT 要求两侧都为 NULL，防止哨兵值被当作价格写入。';
