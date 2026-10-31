-- 持仓诊断一期接口对齐（设计 §5.5、§7.2、§7.8；PA-14、PA-15）。
-- 尚无实盘快照，2026-10-31 用户确认新列直接按新契约 NOT NULL，不为旧快照保留兼容分支。
-- 表非空时 ADD COLUMN ... NOT NULL 会失败而不是写入默认值，避免旧快照被误读成新契约。

ALTER TABLE diag.portfolio_snapshot
    ADD COLUMN IF NOT EXISTS data_fingerprint VARCHAR(64) NOT NULL
        REFERENCES diag.data_version(data_version_id),
    ADD COLUMN IF NOT EXISTS resolved_options JSONB NOT NULL,
    ADD COLUMN IF NOT EXISTS base_snapshot_id UUID
        REFERENCES diag.portfolio_snapshot(snapshot_id) ON DELETE SET NULL;

COMMENT ON COLUMN diag.portfolio_snapshot.data_fingerprint IS
    '提交时固定的数据版本，各方案共用；重算沿用原值，不重新解析最新数据。';
COMMENT ON COLUMN diag.portfolio_snapshot.resolved_options IS
    '解析后的 ResolvedCalculationOptions：缺省项写成具体值，null 只表示该项当前不可用；进入 calculation_hash。';
COMMENT ON COLUMN diag.portfolio_snapshot.base_snapshot_id IS
    '区间重算的来源快照；新提交为 NULL。重算时 requested_payload 为 {base_snapshot_id, options, reset_to_default}。';

ALTER TABLE diag.portfolio_plan
    ADD COLUMN IF NOT EXISTS input_context JSONB NOT NULL;

COMMENT ON COLUMN diag.portfolio_plan.input_context IS
    '提交时固定的 PlanInputSummary：逐行回显、合并关系、完整输入分母上的份额与已解析子集的计算权重。读取时不再重算。';

ALTER TABLE diag.data_version
    ADD COLUMN IF NOT EXISTS available_options JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN diag.data_version.available_options IS
    '本版本已验证可用的可选项（PA-15 B5），形如 {"industry_schemes": [{"code", "version"}], "benchmarks": [{"instrument_id", "symbol", "version"}]}；停用即发布新版本。';

-- 一期口径。旧版本以历史协方差为主、TopN 单值且按日再平衡，与 PA-04～PA-12 不符；
-- 按版本化规则停用而不是原地修改。风险模型选米筐 v2（2026-10-31 用户确认），但 model_id
-- 由因子顺序哈希派生、v2 数据尚未入工作库，factor_model 暂空；选择记在 params，
-- 数据入库并按 D-022 2b 发布后另发带 model_id 的新版本。
UPDATE diag.spec_version
SET is_active = false, effective_to = DATE '2026-10-31'
WHERE spec_version = 'v1-hist-20260901' AND is_active;

INSERT INTO diag.spec_version (
    spec_version, factor_model, factor_model_version,
    params, effective_from, effective_to, is_active
) VALUES (
    'v1-model-20261031',
    NULL,
    NULL,
    '{
      "enabled_features": ["core_diagnosis"],
      "cov_methods": ["forward", "historical"],
      "primary_cov_method": "forward",
      "forward_model_selector": {"source": "ricequant", "model": "v2", "industry_mapping": "sws_2021"},
      "cov_method_params": {
        "forward": {},
        "historical": {"lookback_days": 252, "min_common_samples": 120, "annualize": 252, "used_for": ["correlation_view"]}
      },
      "coverage_thresholds": {
        "_default": {"degraded": 0.95, "unavailable": 0.80},
        "distribution_with_missing_bucket": {"degraded": 0.95, "unavailable": null},
        "full_portfolio_model": {"require_complete": true}
      },
      "coverage_groups": {
        "_default": ["topn", "hhi", "l1_count", "l2_effective_count", "market_distribution",
          "asset_category_distribution", "avg_pairwise_correlation.forward",
          "high_correlation_pairs.forward"],
        "distribution_with_missing_bucket": ["industry_distribution", "max_industry",
          "mktcap_distribution", "pb_distribution"],
        "full_portfolio_model": ["volatility", "risk_contribution", "risk_contribution_ratio",
          "marginal_risk_contribution", "l3_effective_count", "l4_effective_count",
          "l4_market_source_share", "l4_largest_source", "style_exposure"]
      },
      "corr_high_threshold": 0.7,
      "mktcap_bands_yi": [100, 500, 1000, 3000],
      "pb_bands": [1, 2, 4, 8],
      "history_lookback_days": 252,
      "history_min_samples": 120,
      "var_confidence": 0.95,
      "var_method": "historical_replay",
      "var_horizon_days": 1,
      "var_quantile": "order_statistic_ceil",
      "var_full_confidence_samples": 250,
      "beta_lookback_days": 252,
      "topn": [1, 3, 5],
      "industry_scheme": "sw2021",
      "industry_level": 1,
      "benchmark_instrument_id": null,
      "rebalance": "buy_and_hold",
      "include_dividend": true,
      "include_cost": false,
      "include_fx": false
    }'::jsonb,
    DATE '2026-10-31',
    NULL,
    true
)
ON CONFLICT (spec_version) DO NOTHING;
