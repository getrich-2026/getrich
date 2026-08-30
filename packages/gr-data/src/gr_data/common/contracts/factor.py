"""`factor` schema 的表契约。DDL 真源：gr-db `ddl/postgres/037_factor.sql`。

数组列与 JSONB 列必须声明 `column_types`：文本 COPY 下 psycopg 靠首行推断适配器，
推断出的 `float8[]` 喂给 `real[]` 走隐式转换（能跑但脆），首行全 NULL 时还会退化。
声明的是**发送端的线上类型**，所以 NUMERIC/REAL 目标列这里写 `float8`。
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
        "estimated_at",
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
        ("estimated_at", "timestamptz"),
        ("code_version", "text"),
        ("param_hash", "text"),
        ("source", "text"),
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
