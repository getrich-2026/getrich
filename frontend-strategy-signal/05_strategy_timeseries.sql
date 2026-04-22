-- ============================================================
-- 策略时序数据（PostgreSQL 存储，替代原来的 strategies.backtest_report JSONB）
-- 对应前端接口：
--   4.3 GET /strategies/{id}               ← strategy_performance_snapshot（最新快照）
--   4.4 GET /strategies/{id}/equity-curve   ← strategy_equity_curve
--   4.5 GET /strategies/{id}/monthly-returns ← strategy_monthly_returns
--   4.6 GET /strategies/{id}/backtest-report ← strategy_performance_snapshot + 聚合
-- ============================================================

-- 净值曲线（日度）
CREATE TABLE strategy_equity_curve (
    strategy_id         UUID            NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    trade_date          DATE            NOT NULL,
    nav                 NUMERIC(12,6)   NOT NULL,           -- 单位净值（基准 1.000000）
    cumulative_return   NUMERIC(10,6),                      -- 累计收益率
    daily_return        NUMERIC(10,6),                      -- 当日收益率
    drawdown            NUMERIC(10,6),                      -- 当前回撤（负值）
    benchmark_nav       NUMERIC(12,6),                      -- 基准净值（沪深300 等）
    position_ratio      NUMERIC(5,4),                       -- 当日仓位比例
    PRIMARY KEY (strategy_id, trade_date)
);

-- 绩效快照（每日跑一次，取最新一行即为"当前绩效"）
CREATE TABLE strategy_performance_snapshot (
    strategy_id             UUID            NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    snapshot_date           DATE            NOT NULL,

    -- 收益指标
    total_return            NUMERIC(10,6),
    annualized_return       NUMERIC(10,6),
    ytd_return              NUMERIC(10,6),                  -- 今年以来
    recent_1m_return        NUMERIC(10,6),
    recent_3m_return        NUMERIC(10,6),
    recent_6m_return        NUMERIC(10,6),
    recent_1y_return        NUMERIC(10,6),

    -- 风险指标
    max_drawdown            NUMERIC(10,6),
    max_drawdown_start      DATE,
    max_drawdown_end        DATE,
    max_drawdown_recovery   DATE,
    annualized_volatility   NUMERIC(10,6),
    downside_deviation      NUMERIC(10,6),

    -- 风险调整指标
    sharpe_ratio            NUMERIC(8,4),
    sortino_ratio           NUMERIC(8,4),
    calmar_ratio            NUMERIC(8,4),
    information_ratio       NUMERIC(8,4),

    -- 交易统计
    total_trades            INT,
    win_rate                NUMERIC(5,4),
    profit_factor           NUMERIC(8,4),
    avg_win                 NUMERIC(10,6),
    avg_loss                NUMERIC(10,6),
    max_consecutive_wins    INT,
    max_consecutive_losses  INT,
    avg_holding_days        NUMERIC(6,2),

    -- 风控指标
    var_95                  NUMERIC(10,6),
    cvar_95                 NUMERIC(10,6),
    beta                    NUMERIC(8,4),
    alpha                   NUMERIC(10,6),

    PRIMARY KEY (strategy_id, snapshot_date)
);

-- 月度收益矩阵（年 x 月热力图数据源）
CREATE TABLE strategy_monthly_returns (
    strategy_id     UUID            NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    year            SMALLINT        NOT NULL,
    month           SMALLINT        NOT NULL CHECK (month BETWEEN 1 AND 12),
    monthly_return  NUMERIC(10,6)   NOT NULL,
    PRIMARY KEY (strategy_id, year, month)
);
