-- 040_diag.sql
-- diag schema：持仓诊断产品自身的存储层（请求快照 → 方案 → 计算运行 → 关联）。
--
-- 设计依据：getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md §5.5。
-- 与它配套的数据侧 schema 已分别落在 037_factor.sql / 038_fundamental.sql /
-- 039_classify.sql，本文件只建产品自身的表，不碰那三个。
--
-- 语义要点（改这些表前必须先读，写反了不会报错、只会静默算错）：
--
--   1. **计算与请求分离**。portfolio_snapshot 是「用户拥有的资源」，带
--      user_id、按 (user_id, request_hash) 幂等；diagnosis_run 是「无用户维度
--      的纯计算」，按 calculation_hash 跨用户复用。把两者压进一张表会导致
--      两个用户提交同一组合时共享或冲突于同一条缓存记录。
--   2. **diagnosis_run 的粒度是单个 plan**，不是单个 snapshot（文档 T17）。
--      一个含 N 个 plan 的请求产生 N 行。这样「A 用户的独立组合」才能命中
--      「B 用户 before/after 里的 before 方案」—— 这是选 per-plan 的全部理由。
--   3. **diagnosis_run 终态不可变**。payload 只在终态写入一次，此后不再
--      UPDATE。failed 重试只新开行（T19），因为「这次失败过」本身是要保留的
--      审计信息，而不可变是本表的定位。
--   4. **阈值只存在 spec_version.params 里**，实现时不得抄成代码常量。
--      抄成常量后阈值一调、历史报告的可复现性就静默失效了（文档 §5.5）。
--
-- schema 全限定：`diag` **不在**连接池的 search_path（app,market,meta,public）里，
-- 所有业务 SQL 必须显式写 `diag.` 前缀，与 `backtest.` / `pick.` 同一处置。
--
-- 与设计文档的一处偏差（必须的，不是可选项）：
--   * user_id / created_by 用 **UUID** 而非文档写的 BIGINT —— 本仓 app.users.id
--     是 UUID。引用列与被引用主键类型不一致的坑本仓踩过一次（DECISIONS.md
--     D-020：strategies.id 是 VARCHAR 而引用方是 UUID，整个策略/信号接口在
--     全新库上恒 500）。这里直接对齐真实主键类型。
--
-- ownership：diag.* 由 gr-api 自己写，不是 provider ingest 表，因此**不**登记到
-- ops.table_ownership（那张表管的是「同一张行情/因子表只能由一个 provider 写」）。

CREATE SCHEMA IF NOT EXISTS diag;

COMMENT ON SCHEMA diag IS
    '持仓诊断：请求快照、方案、不可变计算运行、口径版本、分享凭证。归属包 gr-api。';

-- ---------------------------------------------------------------------------
-- diag.spec_version —— 口径版本：所有阈值、窗口、模型版本的集合
-- ---------------------------------------------------------------------------
-- 整体参与 calculation_hash：口径变了（阈值、协方差方法、因子模型版本、窗口）
-- 结果就必须失效重算，否则新旧口径的数字会混在同一个缓存里。

CREATE TABLE IF NOT EXISTS diag.spec_version (
    spec_version         VARCHAR(32) PRIMARY KEY,
    factor_model         VARCHAR(32),   -- 软引用 factor.model.model_id，见下方说明
    factor_model_version VARCHAR(32),   -- 软引用 factor.model_run.model_version
    params               JSONB       NOT NULL,
    effective_from       DATE        NOT NULL,
    effective_to         DATE,                            -- NULL = 当前仍生效
    is_active            BOOLEAN     NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_spec_effective_order
        CHECK (effective_to IS NULL OR effective_to > effective_from)
);

COMMENT ON COLUMN diag.spec_version.factor_model IS
    '软引用 factor.model.model_id，**不建外键**：spec_version 属产品层、factor.* 属数据层，两者可能不同库。「forward 口径必须有 model」这条校验改由应用层在写入时做。';
COMMENT ON COLUMN diag.spec_version.params IS
    '阈值与口径的唯一运行时来源。指标文档只是口径来源（记录该是什么、为什么），运行时一律读这里。必需键的 schema 校验在应用层写入时做 —— 拼错一个 key 不能静默走代码默认值。';

-- 任意时刻至多一个 is_active=true，「当前生效版本」因此有唯一定义。
-- 插入新 active 版本的标准事务（避免并发竞态）：
--   BEGIN;
--   UPDATE diag.spec_version SET is_active=false, effective_to=CURRENT_DATE WHERE is_active;
--   INSERT INTO diag.spec_version (...) VALUES (..., true, ...);
--   COMMIT;
-- 唯一索引冲突时重试整个事务。
CREATE UNIQUE INDEX IF NOT EXISTS idx_spec_version_active
    ON diag.spec_version ((true)) WHERE is_active;

-- ---------------------------------------------------------------------------
-- diag.data_version —— 数据快照指纹的载体
-- ---------------------------------------------------------------------------
-- diagnosis_run.data_fingerprint = data_version.data_version_id。
-- 数据快照变了 → fingerprint 变 → calculation_hash 变 → 触发重算。
--
-- **本轮的已知缺口**：文档要求这张表由每日盘后批任务维护，该批任务尚不存在。
-- 下面只 bootstrap 一行，服务层取 snapshot_at 最新的一行。后果必须说清楚 ——
-- 数据重新导入后 fingerprint 不变，旧的成功计算不会失效，接口会返回陈旧结果。
-- 缓解办法：每次数据导入后手工插一行新的 data_version（snapshot_at=导入完成时刻）。

CREATE TABLE IF NOT EXISTS diag.data_version (
    data_version_id VARCHAR(64) PRIMARY KEY,   -- 如 '20260830T1800'
    snapshot_at     TIMESTAMPTZ NOT NULL,
    schemas_covered TEXT[]      NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE diag.data_version IS
    '数据快照版本。纳入的 schema 清单随数据源补全逐步扩展：一期至少 market/meta/classify，P1 加 factor/fundamental，P2 加 holding。';

CREATE INDEX IF NOT EXISTS idx_data_version_snapshot_at
    ON diag.data_version (snapshot_at DESC);

-- ---------------------------------------------------------------------------
-- diag.portfolio_snapshot —— 用户请求资源，是幂等与鉴权的边界
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS diag.portfolio_snapshot (
    snapshot_id            UUID        PRIMARY KEY,
    user_id                UUID        REFERENCES app.users(id),  -- 可空：一期不强制登录
    request_hash           VARCHAR(64) NOT NULL,
    idempotency_key        VARCHAR(128),
    requested_intent       VARCHAR(24),
    resolved_intent        VARCHAR(24) NOT NULL,
    requested_as_of_date   DATE,
    resolved_as_of_date    DATE        NOT NULL,
    requested_spec_version VARCHAR(32),
    resolved_spec_version  VARCHAR(32) NOT NULL
        REFERENCES diag.spec_version(spec_version),
    requested_payload      JSONB       NOT NULL,
    user_level             VARCHAR(16) NOT NULL DEFAULT 'retail',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at             TIMESTAMPTZ,
    CONSTRAINT chk_snapshot_intent CHECK (resolved_intent IN
        ('single_portfolio', 'single_instrument', 'rebalance_amount',
         'rebalance_holding', 'multi_portfolio')),
    CONSTRAINT chk_snapshot_user_level CHECK (user_level IN ('retail', 'pro')),
    CONSTRAINT uq_snapshot_request_hash UNIQUE (user_id, request_hash)
);

COMMENT ON COLUMN diag.portfolio_snapshot.snapshot_id IS
    '必须是 UUIDv4。不用 v1/v7 —— 那两者可枚举且泄漏生成时间，而匿名用户之间的隔离**只**依赖这个 id 的不可猜测性。';
COMMENT ON CONSTRAINT uq_snapshot_request_hash ON diag.portfolio_snapshot IS
    '同一用户提交相同请求 → 同一个 snapshot。匿名时 user_id 为 NULL，PostgreSQL 的 NULL 不参与唯一性比较，即匿名请求之间不互相幂等 —— 这是接受的降级，不是 bug。';
COMMENT ON COLUMN diag.portfolio_snapshot.user_level IS
    '渲染偏好，与付费无关（文档 D6）。只影响 /report 的裁剪，不参与计算、不进 calculation_hash。';

CREATE INDEX IF NOT EXISTS idx_snapshot_user
    ON diag.portfolio_snapshot (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- diag.portfolio_plan —— 一个 snapshot 下的方案（before/after、多组合对比在此展开）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS diag.portfolio_plan (
    snapshot_id         UUID        NOT NULL
        REFERENCES diag.portfolio_snapshot(snapshot_id) ON DELETE CASCADE,
    plan_index          SMALLINT    NOT NULL,   -- plans 数组原始顺序，0-based
    plan_id             VARCHAR(64) NOT NULL,
    label               VARCHAR(32),            -- 'before' / 'after' / 用户自定义
    weight_mode         VARCHAR(16) NOT NULL,
    requested_holdings  JSONB       NOT NULL,
    resolved_holdings   JSONB       NOT NULL,
    PRIMARY KEY (snapshot_id, plan_index),
    CONSTRAINT uq_plan_id UNIQUE (snapshot_id, plan_id),
    CONSTRAINT chk_plan_weight_mode CHECK (weight_mode IN ('user', 'equal'))
);

COMMENT ON COLUMN diag.portfolio_plan.weight_mode IS
    '**plan 级**而非 snapshot 级：一个 plan 给权重、另一个不给是合法输入，挂在 snapshot 上表达不了。';
COMMENT ON COLUMN diag.portfolio_plan.requested_holdings IS
    '[{symbol, weight}, ...] 用户原始输入，不做任何加工。用于审计与「请求本身」的复现。';
COMMENT ON COLUMN diag.portfolio_plan.resolved_holdings IS
    '[{instrument_id, symbol, weight}, ...] 归一化后的最终权重：weight_mode=user 时归一化到和为 1；weight_mode=equal 时全部为 1/n。';

-- ---------------------------------------------------------------------------
-- diag.diagnosis_run —— 一次不可变的计算，计算缓存的唯一真相源
-- ---------------------------------------------------------------------------
-- 不含用户维度（纯函数，天然跨用户可复用）。粒度 = 一个 plan（T17）。

CREATE TABLE IF NOT EXISTS diag.diagnosis_run (
    run_id                 UUID        PRIMARY KEY,
    calculation_hash       VARCHAR(64) NOT NULL,
    spec_version           VARCHAR(32) NOT NULL
        REFERENCES diag.spec_version(spec_version),
    data_fingerprint       VARCHAR(128) NOT NULL,
    status                 VARCHAR(16) NOT NULL DEFAULT 'pending',
    payload                JSONB,
    payload_schema_version VARCHAR(16) NOT NULL,
    data_quality           JSONB,
    error_reason           TEXT,
    computed_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_run_status CHECK (status IN
        ('pending', 'running', 'succeeded', 'partially_succeeded', 'failed'))
);

COMMENT ON COLUMN diag.diagnosis_run.calculation_hash IS
    '单个 plan 的 weight_mode + resolved_holdings(按 instrument_id 升序) + resolved_as_of_date + spec_version + data_fingerprint 的 sha256。**不含** user_id / plan_id / label / plan_index / intent —— 含了就会白白打散跨用户复用。';
COMMENT ON COLUMN diag.diagnosis_run.payload IS
    '单个 plan 的 PlanResult（不是整个 DiagnosisResult）。snapshot 级字段（comparison / disclosures / data_quality）在响应组装时拼接，不入此列。仅在终态写入一次，此后不再 UPDATE。';

-- 唯一键**只**约束成功终态：failed / pending / running 行不占用 calculation_hash，
-- 因此同一 hash 可以重试后重算；成功终态全库至多一行。
-- 写成全局 UNIQUE 会让「一次失败即永久不可重算」，这是本索引必须是 partial 的原因。
CREATE UNIQUE INDEX IF NOT EXISTS uq_calculation_hash_succeeded
    ON diag.diagnosis_run (calculation_hash)
    WHERE status IN ('succeeded', 'partially_succeeded');

CREATE INDEX IF NOT EXISTS idx_diagnosis_run_created
    ON diag.diagnosis_run (created_at DESC);

-- ---------------------------------------------------------------------------
-- diag.snapshot_run —— snapshot 的某个 plan 对应哪一次计算运行
-- ---------------------------------------------------------------------------
-- 只是关联表。一个 plan 在数据修订后可以指向新的 run_id，保留旧关联即为历史归档。

CREATE TABLE IF NOT EXISTS diag.snapshot_run (
    snapshot_id UUID        NOT NULL,
    plan_index  SMALLINT    NOT NULL,
    run_id      UUID        NOT NULL REFERENCES diag.diagnosis_run(run_id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, plan_index, run_id),
    FOREIGN KEY (snapshot_id, plan_index)
        REFERENCES diag.portfolio_plan(snapshot_id, plan_index) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- diag.share_token —— 分享凭证，与 snapshot_id 解耦，可撤销可过期
-- ---------------------------------------------------------------------------
-- token 只能访问 /report（渲染后报告），不暴露 /result 的全量指标。

CREATE TABLE IF NOT EXISTS diag.share_token (
    token       VARCHAR(64) PRIMARY KEY,
    snapshot_id UUID        NOT NULL
        REFERENCES diag.portfolio_snapshot(snapshot_id) ON DELETE CASCADE,
    created_by  UUID        REFERENCES app.users(id),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_share_token_snapshot
    ON diag.share_token (snapshot_id);

-- ---------------------------------------------------------------------------
-- Bootstrap：一期口径版本 + 初始数据快照版本
-- ---------------------------------------------------------------------------
-- 必须幂等：迁移记账按 file_name + checksum，文件改动后会**整体重新应用**，
-- 因此这两条 INSERT 一律 ON CONFLICT DO NOTHING，不能写成裸 INSERT。
--
-- params 取自设计文档 §8 的一期示例。其中 history_lookback_days、
-- benchmark_instrument_id、rebalance 及分红/成本/汇率三项是**架构篇 §11-Q2 的
-- 建议值，未经产品确认**，不得当作已定口径 —— 产品拍板后开一个新 spec_version，
-- 不要原地改这一行（原地改会让已生成的历史报告无法复现）。

INSERT INTO diag.spec_version (
    spec_version, factor_model, factor_model_version,
    params, effective_from, effective_to, is_active
) VALUES (
    'v1-hist-20260901',
    NULL,   -- 一期不接因子模型：G2 阻塞，协方差走历史口径
    NULL,
    '{
      "cov_methods": ["historical"],
      "primary_cov_method": "historical",
      "cov_method_params": {
        "historical": {"lookback_days": 750, "annualize": 252}
      },
      "coverage_thresholds": {
        "_default": {"degraded": 0.95, "unavailable": 0.80}
      },
      "corr_high_threshold": 0.7,
      "mktcap_bands_yi": [1000, 3000],
      "pb_bands": [2, 4],
      "var_confidence": 0.95,
      "history_lookback_days": 750,
      "rebalance": "daily",
      "include_dividend": true,
      "include_cost": false,
      "include_fx": false,
      "topn": 5,
      "industry_scheme": "sw2021",
      "industry_level": 1,
      "benchmark_instrument_id": null
    }'::jsonb,
    DATE '2026-08-30',   -- 版本号里的 20260901 取自设计文档 §8 的示例命名，不是生效日
    NULL,
    true
)
ON CONFLICT (spec_version) DO NOTHING;

INSERT INTO diag.data_version (data_version_id, snapshot_at, schemas_covered)
VALUES (
    '20260830T0000',
    TIMESTAMPTZ '2026-08-30 00:00:00+08',
    ARRAY['market', 'meta', 'classify']
)
ON CONFLICT (data_version_id) DO NOTHING;
