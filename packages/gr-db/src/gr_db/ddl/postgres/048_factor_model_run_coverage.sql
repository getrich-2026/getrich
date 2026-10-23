-- 动态股票池的逐日覆盖账本。它与五件套及成功 ETL 在同一个事务提交。
-- 本迁移不创建发布清单、不开放正式读取；validation run 不能用于正式诊断。
-- run_id 对应一个观测日；日期与 run 元数据的一致性由同日 writer 强制校验。
CREATE TABLE IF NOT EXISTS factor.model_run_coverage (
    run_id UUID NOT NULL REFERENCES factor.model_run(run_id),
    instrument_id BIGINT NOT NULL REFERENCES meta.instruments(instrument_id),
    trading_day DATE NOT NULL,
    input_codes TEXT[] NOT NULL,
    request_code TEXT,
    status TEXT NOT NULL,
    pieces JSONB NOT NULL,
    evidence JSONB NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, instrument_id),
    CONSTRAINT chk_model_run_coverage_input_codes CHECK (
        cardinality(input_codes) > 0
        AND array_ndims(input_codes) = 1
        AND array_lower(input_codes, 1) = 1
        AND array_position(input_codes, NULL) IS NULL
        AND array_to_string(input_codes, ',') !~ '(^|,)[[:space:]]*(,|$)'
    ),
    CONSTRAINT chk_model_run_coverage_request_code CHECK (
        request_code IS NULL OR request_code ~ '^[0-9]{6}\.(XSHG|XSHE)$'
    ),
    CONSTRAINT chk_model_run_coverage_status CHECK (status IN (
        'included', 'provider_not_returned', 'partial_bundle', 'sdk_filtered',
        'universe_boundary_unknown', 'unmapped_symbol'
    )),
    CONSTRAINT chk_model_run_coverage_pieces CHECK (
        jsonb_typeof(pieces) = 'object'
        AND pieces ?& ARRAY['exposure', 'specific_return', 'specific_risk']
        AND pieces - ARRAY['exposure', 'specific_return', 'specific_risk'] = '{}'::jsonb
        AND jsonb_typeof(pieces -> 'exposure') = 'boolean'
        AND jsonb_typeof(pieces -> 'specific_return') = 'boolean'
        AND jsonb_typeof(pieces -> 'specific_risk') = 'boolean'
    ),
    CONSTRAINT chk_model_run_coverage_evidence CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT chk_model_run_coverage_included CHECK (
        status <> 'included' OR (
            request_code IS NOT NULL
            AND pieces = '{"exposure":true,"specific_return":true,"specific_risk":true}'::jsonb
        )
    ),
    CONSTRAINT chk_model_run_coverage_missing CHECK (
        status NOT IN ('provider_not_returned', 'partial_bundle') OR (
            request_code IS NOT NULL
            AND CASE status
                WHEN 'provider_not_returned' THEN
                    pieces = '{"exposure":false,"specific_return":false,"specific_risk":false}'::jsonb
                ELSE pieces <> '{"exposure":true,"specific_return":true,"specific_risk":true}'::jsonb
                    AND pieces <> '{"exposure":false,"specific_return":false,"specific_risk":false}'::jsonb
            END
        )
    ),
    CONSTRAINT chk_model_run_coverage_unrequested CHECK (
        status NOT IN ('unmapped_symbol', 'sdk_filtered', 'universe_boundary_unknown') OR (
            request_code IS NULL
            AND pieces = '{"exposure":false,"specific_return":false,"specific_risk":false}'::jsonb
        )
    ),
    CONSTRAINT chk_model_run_coverage_available_at CHECK (isfinite(available_at))
);

CREATE INDEX IF NOT EXISTS idx_model_run_coverage_instrument_day
    ON factor.model_run_coverage (instrument_id, trading_day);

COMMENT ON TABLE factor.model_run_coverage IS
    '米筐风险模型逐日候选股票的覆盖账本。包含完整、未返回和部分返回等结果；缺失持仓按 D-017 标为不可用，不剔除、不估算。验证用途不等于正式发布。';
COMMENT ON COLUMN factor.model_run_coverage.run_id IS
    '不可变观测 run，关联 factor.model_run；同一 run 的覆盖与五件套在同一事务写入。';
COMMENT ON COLUMN factor.model_run_coverage.instrument_id IS
    '候选股票的已知 canonical 身份；已退市股票也保留。真正无法映射证券身份的外部代码只留 raw，未解析前阻断入库，不以 unmapped_symbol 写入本表。';
COMMENT ON COLUMN factor.model_run_coverage.trading_day IS
    '股票池及风险数据对应的交易日（event time），必须与该 run 的五件套日期一致。';
COMMENT ON COLUMN factor.model_run_coverage.input_codes IS
    '名单快照中的原始及已核实别名代码，非空且无 NULL；不以六位代码猜测同一证券。';
COMMENT ON COLUMN factor.model_run_coverage.request_code IS
    'SDK 解析后的实际请求代码；unmapped_symbol、sdk_filtered、universe_boundary_unknown 均未发送个股请求，必须为 NULL。被过滤的输入码保留在 input_codes 与该股 evidence。';
COMMENT ON COLUMN factor.model_run_coverage.status IS
    'included=三项完整；provider_not_returned=成功请求后三项均未返回；partial_bundle=只返回部分；unmapped_symbol=证券身份已知但生成不出米筐请求代码；sdk_filtered=身份已知但 SDK 未接受任何候选码；universe_boundary_unknown=上市退市边界未确认，未发请求。invalid_value 只留 raw 失败证据并阻断整日，unsupported_exchange 只留 raw 范围排除记录，均不落本表。';
COMMENT ON COLUMN factor.model_run_coverage.pieces IS
    'exposure、specific_return、specific_risk 三个布尔值，表示该标的各接口的完整有效数据是否返回。必须恰有这三个键；三种请求前阻断状态必须全部为 false。';
COMMENT ON COLUMN factor.model_run_coverage.evidence IS
    '仅存该股票的源日期边界、代码解析及缺失原因；不得逐行复制全市场名单、完整参考快照、SDK 版本或共用规则。整日共用证据摘要及 raw 哈希引用记录在 model_run.units 与 ETL request，完整快照留 raw。';
COMMENT ON COLUMN factor.model_run_coverage.available_at IS
    '实际采集观测时间，采用 raw 的带时区 observed_at；历史回填不能伪装为历史时点已可用。';
