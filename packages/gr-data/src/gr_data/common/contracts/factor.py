"""`factor` 表契约。

DDL 真源：037_factor.sql、048_factor_model_run_coverage.sql、
049_risk_import_receipts.sql。column_types 用于 COPY 的显式类型适配。
"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract


MODEL = TableContract(
    schema="factor",
    table="model",
    columns=("model_id", "model_name", "source"),
    conflict_keys=("model_id",),
)

DEFINITION = TableContract(
    schema="factor",
    table="definition",
    columns=("model_id", "factor_code", "factor_name", "factor_type", "ordinal"),
    conflict_keys=("model_id", "factor_code"),
)

MODEL_RUN = TableContract(
    schema="factor",
    table="model_run",
    columns=(
        "run_id",
        "model_id",
        "model_version",
        "factor_order",
        "factor_count",
        "factor_order_hash",
        "factor_set_hash",
        "annualization_basis",
        "units",
        "calibrated",
        "observed_at",
        "code_version",
        "param_hash",
        "source",
    ),
    conflict_keys=("run_id",),
    column_types=(
        ("run_id", "uuid"),
        ("model_id", "text"),
        ("model_version", "text"),
        ("factor_order", "text[]"),
        ("factor_count", "int2"),
        ("factor_order_hash", "text"),
        ("factor_set_hash", "text"),
        ("annualization_basis", "text"),
        ("units", "jsonb"),
        ("calibrated", "bool"),
        ("observed_at", "timestamptz"),
        ("code_version", "text"),
        ("param_hash", "text"),
        ("source", "text"),
    ),
)

# 不可变绑定由收据 writer INSERT / 核对，不走通用更新式 UPSERT。
MODEL_RUN_BINDING = TableContract(
    schema="factor",
    table="model_run_binding",
    columns=("run_id", "receipt_id", "variant_id", "observation_id", "trading_day"),
    conflict_keys=("run_id",),
    column_types=(
        ("run_id", "uuid"),
        ("receipt_id", "uuid"),
        ("variant_id", "text"),
        ("observation_id", "text"),
        ("trading_day", "date"),
    ),
)

MODEL_RUN_COVERAGE = TableContract(
    schema="factor",
    table="model_run_coverage",
    columns=(
        "run_id",
        "instrument_id",
        "trading_day",
        "input_codes",
        "request_code",
        "status",
        "pieces",
        "evidence",
        "available_at",
    ),
    conflict_keys=("run_id", "instrument_id"),
    column_types=(
        ("run_id", "uuid"),
        ("instrument_id", "int8"),
        ("trading_day", "date"),
        ("input_codes", "text[]"),
        ("request_code", "text"),
        ("status", "text"),
        ("pieces", "jsonb"),
        ("evidence", "jsonb"),
        ("available_at", "timestamptz"),
    ),
)

EXPOSURE = TableContract(
    schema="factor",
    table="exposure",
    columns=("run_id", "instrument_id", "trading_day", "exposure", "factor_count", "available_at"),
    conflict_keys=("run_id", "instrument_id", "trading_day"),
    column_types=(
        ("run_id", "uuid"),
        ("instrument_id", "int8"),
        ("trading_day", "date"),
        ("exposure", "float4[]"),
        ("factor_count", "int2"),
        ("available_at", "timestamptz"),
    ),
)

COVARIANCE = TableContract(
    schema="factor",
    table="covariance",
    columns=("run_id", "trading_day", "cov_flat", "factor_count", "available_at"),
    conflict_keys=("run_id", "trading_day"),
    column_types=(
        ("run_id", "uuid"),
        ("trading_day", "date"),
        # DOUBLE PRECISION[]：REAL 的 7 位有效数字装不下实测的 9 位（见 037 的偏离 4）
        ("cov_flat", "float8[]"),
        ("factor_count", "int2"),
        ("available_at", "timestamptz"),
    ),
)

FACTOR_RETURN = TableContract(
    schema="factor",
    table="factor_return",
    columns=("run_id", "trading_day", "ret_vector", "factor_count", "available_at"),
    conflict_keys=("run_id", "trading_day"),
    column_types=(
        ("run_id", "uuid"),
        ("trading_day", "date"),
        ("ret_vector", "float4[]"),
        ("factor_count", "int2"),
        ("available_at", "timestamptz"),
    ),
)

SPECIFIC_RISK = TableContract(
    schema="factor",
    table="specific_risk",
    columns=("run_id", "instrument_id", "trading_day", "specific_var", "source", "available_at"),
    conflict_keys=("run_id", "instrument_id", "trading_day"),
)

SPECIFIC_RETURN = TableContract(
    schema="factor",
    table="specific_return",
    columns=("run_id", "instrument_id", "trading_day", "specific_ret", "available_at"),
    conflict_keys=("run_id", "instrument_id", "trading_day"),
)
