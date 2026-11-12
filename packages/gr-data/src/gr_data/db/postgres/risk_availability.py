from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from gr_data.common.risk_availability import RiskCoverage, RiskDay, assess_day


def assess_postgres_day(
    conn: psycopg.Connection,
    snapshot: RiskDay,
    *,
    model: str,
    day: date,
    holdings: Mapping[str, Decimal],
    known_at: datetime | None = None,
) -> dict[str, object]:
    """用工作库的同日实体数据验证离线持仓覆盖，返回预检事实而非风险数值。

    snapshot 必须来自已登记哈希的库存清单。此同步专用入口要求只读连接，
    不选择最近日期或其他模型，不输出风险矩阵，不提供正式发布权限。

    Raises:
        ValueError: 连接非只读、清单身份与实时数据库不一致，或输入非法。
    """
    if not conn.read_only:
        raise ValueError("Risk availability queries require a read-only connection")
    empty = RiskCoverage(model, day, snapshot.run_id, ())
    # 验证输入和明确的缺口；不查询邻日来替代它。
    preflight = assess_day(
        snapshot, model=model, day=day, holdings=holdings, coverage=empty, known_at=known_at
    )
    if snapshot.storage_status != "accepted":
        return preflight
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """SELECT m.model_id,m.observed_at,m.units,m.factor_order_hash,m.calibrated,
                      v.identity->>'horizon' AS horizon
               FROM factor.model_run m
               JOIN factor.model_run_binding b USING(run_id)
               JOIN factor.import_receipt r ON r.receipt_id=b.receipt_id
                 AND r.variant_id=b.variant_id AND r.trading_day=b.trading_day
                 AND r.observation_id=b.observation_id
               JOIN factor.dataset_variant v ON v.variant_id=r.variant_id
               WHERE m.run_id=%s AND m.source='ricequant'
                 AND b.trading_day=%s AND b.variant_id=%s""",
            (snapshot.run_id, day, snapshot.variant_id),
        )
        rows = cur.fetchall()
        if len(rows) != 1:
            raise ValueError("Inventory snapshot no longer has a unique atomic receipt binding")
        row = rows[0]
        units = row["units"]
        if (
            row["model_id"] != snapshot.model_id
            or row["observed_at"] != snapshot.observed_at
            or units.get("model") != model
            or units.get("trading_day") != day.isoformat()
            or units.get("variant_id") != snapshot.variant_id
            or row["factor_order_hash"] != snapshot.factor_axis_hash
            or row["horizon"] != snapshot.horizon
            or units.get("covariance") != snapshot.variance_unit
            or units.get("specific_risk") != snapshot.variance_unit
            or row["calibrated"] is not snapshot.calibrated
        ):
            raise ValueError(
                "Inventory model/date/units/horizon/axis identity differs from database"
            )
        cur.execute(
            """SELECT i.symbol FROM factor.exposure e
               JOIN factor.specific_risk s USING(run_id,instrument_id)
               JOIN factor.model_run_coverage c USING(run_id,instrument_id)
               JOIN meta.instruments i USING(instrument_id)
               WHERE e.run_id=%s AND e.trading_day=%s AND s.trading_day=%s
                 AND c.trading_day=%s AND c.status='included'
                 AND i.symbol=ANY(%s) ORDER BY i.symbol""",
            (snapshot.run_id, day, day, day, [s for s, w in holdings.items() if w != 0]),
        )
        symbols = tuple(r["symbol"] for r in cur.fetchall())
    return assess_day(
        snapshot,
        model=model,
        day=day,
        holdings=holdings,
        coverage=RiskCoverage(model, day, snapshot.run_id, symbols),
        known_at=known_at,
    )
