"""`factor.model` / `definition` / `model_run` 的读写。

`model_run` 是**不可变**的：它钉住了「这批数据用的是哪 K 个因子、按什么顺序、
什么量纲」。其余五张表都以 `run_id` 外键指向它，下游按下标取值。
所以一旦因子集合变了，唯一正确的做法是**开一个新 model_version**，
而不是原地改 —— 改一行就等于让过去所有算过的诊断结果无法重算。

`get_or_create_run` 的语义因此是：同 `(model_id, model_version)` 已存在时，
校验因子顺序哈希一致后复用；不一致就抛错要求人工介入。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from gr_data.ingest.datayes import factors as fx
from gr_data.ingest.datayes.scaling import Scaling


MODEL_ID = "barra_cne6"
MODEL_NAME = "通联 CNE6 风险模型（申万行业）"
MODEL_VERSION = "cne6-sw21"
SOURCE = "datayes"

#: 风险类（covariance / specific_risk）的年化口径。因子收益与特质收益是日频，
#: 它们的口径在 model_run.units 里，不看这一列（见 037_factor.sql 的偏离 1）。
ANNUALIZATION_BASIS = "annual_252"


class ModelRunConflictError(RuntimeError):
    """已存在的 model_run 与本次要写入的因子顺序不一致。"""


def upsert_model_and_definitions(conn: psycopg.Connection, factor_order: list[str]) -> None:
    """写 factor.model 一行 + factor.definition 每因子一行。

    `definition.ordinal` 就是各数组列里的下标，必须与 `factor_order` 一一对应。
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO factor.model (model_id, model_name, source) VALUES (%s, %s, %s) "
            "ON CONFLICT (model_id) DO UPDATE SET model_name = EXCLUDED.model_name",
            (MODEL_ID, MODEL_NAME, SOURCE),
        )
        cur.executemany(
            "INSERT INTO factor.definition "
            "  (model_id, factor_code, factor_name, factor_type, ordinal) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (model_id, factor_code) DO UPDATE SET "
            "  factor_name = EXCLUDED.factor_name, "
            "  factor_type = EXCLUDED.factor_type, "
            "  ordinal = EXCLUDED.ordinal",
            [
                (
                    MODEL_ID,
                    code,
                    fx.INDUSTRY_NAMES.get(code, code),
                    fx.FACTOR_TYPE[code],
                    ordinal,
                )
                for ordinal, code in enumerate(factor_order)
            ],
        )


def get_or_create_run(
    conn: psycopg.Connection,
    factor_order: list[str],
    scaling: Scaling,
    *,
    estimated_at: datetime,
    model_version: str = MODEL_VERSION,
) -> uuid.UUID:
    """取回或创建 model_run，返回 run_id。

    已存在且因子顺序一致 → 直接复用（**不 UPDATE**，`model_run` 不可变）。
    顺序不一致 → 抛 `ModelRunConflictError`，要人工确认后开新 model_version。
    """
    order_hash = fx.factor_order_hash(factor_order)
    set_hash = fx.factor_set_hash(factor_order)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, factor_order_hash, factor_count FROM factor.model_run "
            "WHERE model_id = %s AND model_version = %s",
            (MODEL_ID, model_version),
        )
        row = cur.fetchone()
        if row is not None:
            run_id, existing_hash, existing_count = row
            if existing_hash != order_hash or existing_count != len(factor_order):
                raise ModelRunConflictError(
                    f"model_run({MODEL_ID}, {model_version}) 已存在，但因子顺序与本次不一致"
                    f"（库内 hash={existing_hash} count={existing_count}，"
                    f"本次 hash={order_hash} count={len(factor_order)}）。"
                    "model_run 不可变——请确认供应商是否更换了因子体系，"
                    "确认后用新的 model_version 重新入库，不要改这一行。"
                )
            return run_id

        run_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO factor.model_run "
            "  (run_id, model_id, model_version, factor_order, factor_count, "
            "   factor_order_hash, factor_set_hash, annualization_basis, units, calibrated, "
            "   estimated_at, code_version, param_hash, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                MODEL_ID,
                model_version,
                list(factor_order),
                len(factor_order),
                order_hash,
                set_hash,
                ANNUALIZATION_BASIS,
                Jsonb(scaling.as_units()),
                scaling.calibrated,
                estimated_at,
                None,
                # 供应商未公开 CNE6 的估计参数（半衰期、窗口），恒为 NULL。
                # 填一个猜的值比留空更糟：口径追溯会指向一个从未成立的参数。
                None,
                SOURCE,
            ),
        )
        return run_id


def load_run(conn: psycopg.Connection, model_version: str = MODEL_VERSION) -> tuple:
    """读回 (run_id, factor_order, factor_set_hash)，供各 importer 复核当日因子集。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, factor_order, factor_set_hash FROM factor.model_run "
            "WHERE model_id = %s AND model_version = %s",
            (MODEL_ID, model_version),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"factor.model_run 里没有 ({MODEL_ID}, {model_version})，"
            "请先运行 `gr-data ingest datayes --only model_run`。"
        )
    return row
