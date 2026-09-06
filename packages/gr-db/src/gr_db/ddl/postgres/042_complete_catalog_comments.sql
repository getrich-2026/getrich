-- 042_complete_catalog_comments.sql
-- 为 gr-db 管理的全部 PostgreSQL 业务表补齐 catalog 注释。
--
-- 只覆盖本仓 DDL 的 12 个 schema；TimescaleDB 的 _timescaledb_* 内部表和
-- 仓外 schema 不属于 gr-db，既不应也不能由本迁移改写。已有的人工注释不覆盖，
-- 保留 provider 设计文档中更精确的单位、时序与口径说明。

DO $$
DECLARE
    item RECORD;
    description TEXT;
BEGIN
    FOR item IN
        SELECT n.nspname AS schema_name, c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname IN (
              'app', 'backtest', 'classify', 'diag', 'factor', 'fundamental', 'market',
              'meta', 'ops', 'pick', 'realtime', 'staging'
          )
          AND obj_description(c.oid, 'pg_class') IS NULL
        ORDER BY n.nspname, c.relname
    LOOP
        description := CASE item.schema_name
            WHEN 'app' THEN format('应用业务表：%s。', item.table_name)
            WHEN 'backtest' THEN format('回测产物表：%s。', item.table_name)
            WHEN 'classify' THEN format('标的分类数据表：%s。', item.table_name)
            WHEN 'diag' THEN format('持仓诊断数据表：%s。', item.table_name)
            WHEN 'factor' THEN format('因子与风险模型数据表：%s。', item.table_name)
            WHEN 'fundamental' THEN format('基本面分析数据表：%s。', item.table_name)
            WHEN 'market' THEN format('市场行情与参考数据表：%s。', item.table_name)
            WHEN 'meta' THEN format('合约、代码映射与交易日历元数据表：%s。', item.table_name)
            WHEN 'ops' THEN format('数据接入与平台运维表：%s。', item.table_name)
            WHEN 'pick' THEN format('选股标的池数据表：%s。', item.table_name)
            WHEN 'realtime' THEN format('实时行情缓冲表：%s。', item.table_name)
            WHEN 'staging' THEN format('数据入库中转表：%s。', item.table_name)
        END;
        EXECUTE format('COMMENT ON TABLE %I.%I IS %L', item.schema_name, item.table_name, description);
    END LOOP;

    FOR item IN
        SELECT
            n.nspname AS schema_name,
            c.relname AS table_name,
            a.attname AS column_name,
            format_type(a.atttypid, a.atttypmod) AS data_type
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p')
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND n.nspname IN (
              'app', 'backtest', 'classify', 'diag', 'factor', 'fundamental', 'market',
              'meta', 'ops', 'pick', 'realtime', 'staging'
          )
          AND col_description(c.oid, a.attnum) IS NULL
        ORDER BY n.nspname, c.relname, a.attnum
    LOOP
        description := CASE item.column_name
            WHEN 'id' THEN '记录的主键。'
            WHEN 'instrument_id' THEN '关联 meta.instruments 的标的 ID。'
            WHEN 'user_id' THEN '关联 app.users 的用户 ID。'
            WHEN 'strategy_id' THEN '关联 app.strategies 的策略 ID。'
            WHEN 'signal_id' THEN '关联 app.signals 的信号 ID。'
            WHEN 'order_id' THEN '关联 app.orders 的订单 ID。'
            WHEN 'run_id' THEN '关联本次计算、导入或模型运行的唯一标识。'
            WHEN 'batch_id' THEN '关联所属批次的唯一标识。'
            WHEN 'source_order_id' THEN '关联授权来源订单的 ID。'
            WHEN 'source' THEN '产生或提供该记录的数据源标识。'
            WHEN 'provider' THEN '数据供应商标识。'
            WHEN 'dataset_name' THEN '供应商数据集名称。'
            WHEN 'schema_name' THEN '数据库 schema 名称。'
            WHEN 'table_name' THEN '数据库表名称。'
            WHEN 'symbol' THEN '带交易所后缀的规范证券代码。'
            WHEN 'source_symbol' THEN '供应商原始证券代码。'
            WHEN 'symbol_name' THEN '证券展示名称。'
            WHEN 'name' THEN '展示名称。'
            WHEN 'description' THEN '文字说明。'
            WHEN 'summary' THEN '简要说明。'
            WHEN 'note' THEN '人工备注。'
            WHEN 'status' THEN '记录的当前状态。'
            WHEN 'state' THEN '处理进度或运行状态。'
            WHEN 'role' THEN '用户权限角色。'
            WHEN 'type' THEN '业务对象类型。'
            WHEN 'asset' THEN '金融资产品种。'
            WHEN 'asset_class' THEN '资产大类。'
            WHEN 'exchange' THEN '交易所的 canonical 代码。'
            WHEN 'market' THEN '所属市场。'
            WHEN 'trading_day' THEN '所属交易日。'
            WHEN 'dt' THEN '行情事件时间；分钟行情使用带时区时间戳。'
            WHEN 'bar_dt' THEN 'K 线事件时间。'
            WHEN 'trade_date' THEN '成交或统计所属日期。'
            WHEN 'start_date' THEN '数据或任务覆盖范围的起始日期。'
            WHEN 'end_date' THEN '数据或任务覆盖范围的结束日期。'
            WHEN 'created_at' THEN '记录创建时间。'
            WHEN 'updated_at' THEN '记录最后更新时间。'
            WHEN 'available_at' THEN '数据在下游可安全使用的时间。'
            WHEN 'published_at' THEN '对外发布时间。'
            WHEN 'started_at' THEN '任务或计算开始时间。'
            WHEN 'finished_at' THEN '任务或计算结束时间。'
            WHEN 'completed_at' THEN '任务或计算完成时间。'
            WHEN 'executed_at' THEN '订单或成交实际执行时间。'
            WHEN 'expires_at' THEN '记录或授权到期时间。'
            WHEN 'expire_at' THEN '信号或订单失效时间。'
            WHEN 'open' THEN '开盘价。'
            WHEN 'high' THEN '最高价。'
            WHEN 'low' THEN '最低价。'
            WHEN 'close' THEN '收盘价或最新收盘价。'
            WHEN 'pre_close' THEN '前一交易日收盘价。'
            WHEN 'settle' THEN '结算价。'
            WHEN 'pre_settle' THEN '前一交易日结算价。'
            WHEN 'volume' THEN '成交量；股票与 ETF 单位为股，期货与期权单位为手。'
            WHEN 'amount' THEN '成交额，单位为元。'
            WHEN 'open_interest' THEN '持仓量。'
            WHEN 'limit_up' THEN '涨停参考价。'
            WHEN 'limit_down' THEN '跌停参考价。'
            WHEN 'trading_status' THEN '交易状态。'
            WHEN 'trading_state' THEN '当日交易状态。'
            WHEN 'adj_factor' THEN '复权因子。'
            WHEN 'raw_payload' THEN '保留供应商原始字段的 JSONB 载荷。'
            WHEN 'metadata' THEN '结构化扩展元数据。'
            WHEN 'request' THEN '任务请求参数的结构化快照。'
            WHEN 'checkpoint' THEN '增量任务检查点的结构化状态。'
            WHEN 'error' THEN '失败错误信息。'
            WHEN 'error_message' THEN '失败错误信息。'
            WHEN 'warning_count' THEN '本次处理产生的警告数量。'
            WHEN 'rows_written' THEN '本次写入的记录行数。'
            WHEN 'row_count' THEN '文件或数据集包含的记录行数。'
            WHEN 'file_size_bytes' THEN '文件大小，单位为字节。'
            WHEN 'content_hash' THEN '内容哈希，用于去重和变更识别。'
            WHEN 'checksum' THEN '文件内容校验和。'
            WHEN 'uri' THEN '产物或文件的存储 URI。'
            WHEN 'open_interest' THEN '持仓量。'
            WHEN 'last' THEN '最新成交价。'
            WHEN 'bid1' THEN '买一价。'
            WHEN 'ask1' THEN '卖一价。'
            WHEN 'bid_vol1' THEN '买一数量。'
            WHEN 'ask_vol1' THEN '卖一数量。'
            WHEN 'turnover' THEN '换手额或成交额。'
            WHEN 'turnover_rate' THEN '换手率。'
            WHEN 'amplitude' THEN '日内振幅。'
            WHEN 'avg_price' THEN '平均成交价。'
            WHEN 'price' THEN '价格。'
            WHEN 'quantity' THEN '数量。'
            WHEN 'qty' THEN '数量。'
            WHEN 'notional' THEN '名义金额。'
            WHEN 'fee' THEN '手续费金额。'
            WHEN 'slippage' THEN '滑点成本。'
            WHEN 'realized_pnl' THEN '已实现盈亏。'
            WHEN 'unrealized_pnl' THEN '未实现盈亏。'
            WHEN 'pnl_pct' THEN '盈亏百分比。'
            WHEN 'weight' THEN '权重。'
            WHEN 'suggest_weight' THEN '建议配置权重。'
            WHEN 'position_pct' THEN '建议仓位占比。'
            WHEN 'position_ratio' THEN '实际仓位占比。'
            WHEN 'confidence' THEN '信号置信度。'
            WHEN 'risk_level' THEN '风险等级。'
            WHEN 'target_price' THEN '目标价格。'
            WHEN 'trigger_price' THEN '触发价格。'
            WHEN 'stop_loss_price' THEN '止损价格。'
            WHEN 'entry_low' THEN '建议入场价格区间下限。'
            WHEN 'entry_high' THEN '建议入场价格区间上限。'
            WHEN 'strike' THEN '期权行权价。'
            WHEN 'strike_price' THEN '期权行权价。'
            WHEN 'option_type' THEN '期权类型：认购或认沽。'
            WHEN 'expiry_date' THEN '期权到期日。'
            WHEN 'iv' THEN '隐含波动率。'
            WHEN 'delta' THEN '期权 Delta。'
            WHEN 'gamma' THEN '期权 Gamma。'
            WHEN 'vega' THEN '期权 Vega。'
            WHEN 'theta' THEN '期权 Theta。'
            WHEN 'rho' THEN '期权 Rho。'
            WHEN 'total_return' THEN '累计收益率。'
            WHEN 'daily_return' THEN '单日收益率。'
            WHEN 'monthly_return' THEN '单月收益率。'
            WHEN 'annualized_return' THEN '年化收益率。'
            WHEN 'annualized_volatility' THEN '年化波动率。'
            WHEN 'max_drawdown' THEN '最大回撤。'
            WHEN 'sharpe_ratio' THEN '夏普比率。'
            WHEN 'sortino_ratio' THEN '索提诺比率。'
            WHEN 'calmar_ratio' THEN '卡玛比率。'
            WHEN 'beta' THEN '相对基准的 Beta 系数。'
            WHEN 'alpha' THEN '相对基准的 Alpha 收益。'
            WHEN 'nav' THEN '单位净值或策略净值。'
            WHEN 'unit_nav' THEN '单位净值。'
            WHEN 'accumulated_nav' THEN '累计净值。'
            WHEN 'total_mv' THEN '总市值，单位为元。'
            WHEN 'circ_mv' THEN '流通市值，单位为元。'
            WHEN 'pe' THEN '市盈率。'
            WHEN 'pe_ttm' THEN '滚动市盈率。'
            WHEN 'pb' THEN '市净率。'
            WHEN 'ps' THEN '市销率。'
            WHEN 'source_revision' THEN '供应商数据修订版本。'
            WHEN 'currency' THEN '金额的币种代码。'
            WHEN 'is_active' THEN '是否处于有效状态。'
            WHEN 'is_open' THEN '该日是否开市。'
            WHEN 'is_executed' THEN '是否已经执行。'
            WHEN 'verified' THEN '认证信息是否已验证。'
            WHEN 'revoked' THEN '是否已撤销。'
            WHEN 'channels' THEN '通知渠道配置。'
            WHEN 'push_enabled' THEN '是否启用推送通知。'
            WHEN 'quiet_hours' THEN '免打扰时间段配置。'
            WHEN 'indicators' THEN '行情技术指标的 JSONB 快照。'
            WHEN 'greeks' THEN '期权 Greeks 的 JSONB 快照。'
            WHEN 'greeks_snapshot' THEN '期权 Greeks 的 JSONB 快照。'
            WHEN 'reason' THEN '信号或状态变更原因。'
            WHEN 'reason_detail' THEN '信号原因的结构化明细。'
            WHEN 'detail' THEN '检查或运行明细。'
            WHEN 'detail_html' THEN '经清洗后用于展示的详情 HTML。'
            ELSE CASE
                WHEN right(item.column_name, 3) = '_id'
                    THEN format('关联的 %s 标识。', replace(item.column_name, '_id', ''))
                WHEN left(item.column_name, 3) = 'is_'
                    THEN format('是否%s的布尔标记。', replace(item.column_name, 'is_', ''))
                WHEN right(item.column_name, 3) = '_at'
                    THEN format('%s时间。', replace(item.column_name, '_at', ''))
                WHEN right(item.column_name, 5) = '_date'
                    THEN format('%s日期。', replace(item.column_name, '_date', ''))
                WHEN item.data_type IN ('json', 'jsonb')
                    THEN format('%s的结构化 JSON 数据。', item.column_name)
                WHEN item.data_type = 'boolean'
                    THEN format('%s的布尔状态标记。', item.column_name)
                WHEN item.data_type LIKE 'timestamp%'
                    THEN format('%s时间戳。', item.column_name)
                WHEN item.data_type = 'date'
                    THEN format('%s日期。', item.column_name)
                ELSE format('%s表的%s字段。', item.table_name, item.column_name)
            END
        END;
        EXECUTE format(
            'COMMENT ON COLUMN %I.%I.%I IS %L',
            item.schema_name,
            item.table_name,
            item.column_name,
            description
        );
    END LOOP;
END $$;
