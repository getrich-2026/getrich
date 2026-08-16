"""信号模块业务逻辑。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from gr_api.errors import NotFound
from gr_api.services.sanitize import normalize_reason
from gr_signal.trade_reconciler import reconcile_trades


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from gr_api.schemas.signal import ExecuteSignalIn
    from psycopg import AsyncConnection


_TZ_SH = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------- list


async def list_signals(
    db: AsyncConnection,
    *,
    user_id: str | None,
    strategy_id: str | None,  # 可以是 strategy_code
    strategy_ids: list[str] | None,
    signal_type: str | None,
    action: str | None,
    asset_class: str | None,
    is_read: bool | None,
    confidence_min: float | None,
    start_date: date | None,
    end_date: date | None,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int, int]:
    """GET /signals。返回 (items, total, unread_count)。

    user_id 为 None 时 is_read 字段恒为 False、unread_count 为 0。
    """
    conds: list[str] = []
    params: dict[str, Any] = {"limit": page.limit, "offset": page.offset}

    # strategy_id / strategy_ids 都用 strategy_code 过滤（需 JOIN strategies）
    code_filters: list[str] = []
    if strategy_id:
        code_filters.append(strategy_id)
    if strategy_ids:
        code_filters.extend(strategy_ids)
    if code_filters:
        conds.append("st.strategy_code = ANY(%(codes)s)")
        params["codes"] = code_filters

    if signal_type:
        conds.append("s.type = %(stype)s")
        params["stype"] = signal_type
    if action:
        conds.append("s.action = %(action)s")
        params["action"] = action
    if asset_class:
        # 通过 strategy 关联 asset_class（signals 表本身没有 asset_class）
        conds.append("st.asset_class = %(asset_class)s")
        params["asset_class"] = asset_class
    if confidence_min is not None:
        conds.append("s.confidence >= %(cmin)s")
        params["cmin"] = confidence_min
    if start_date:
        conds.append("s.published_at >= %(start)s")
        params["start"] = start_date
    if end_date:
        conds.append("s.published_at < (%(end)s::date + INTERVAL '1 day')")
        params["end"] = end_date

    if is_read is not None and user_id:
        if is_read:
            conds.append("usr.user_id IS NOT NULL")
        else:
            conds.append("usr.user_id IS NULL")

    where_sql = "WHERE " + " AND ".join(conds) if conds else ""

    user_join = ""
    if user_id:
        user_join = (
            "LEFT JOIN user_signal_reads usr ON usr.signal_id = s.id AND usr.user_id = %(uid)s"
        )
        params["uid"] = user_id

    sql = f"""
        SELECT
            s.signal_code           AS id,
            st.strategy_code        AS strategy_code,
            st.name                 AS strategy_name,
            s.type                  AS signal_type,
            s.action,
            s.direction,
            s.symbol,
            COALESCE(s.symbol_name, '') AS symbol_name,
            COALESCE(s.exchange, '')    AS exchange,
            s.trigger_price,
            s.target_price,
            s.stop_loss_price,
            s.confidence,
            s.urgency,
            COALESCE(s.reason, '')      AS reason,
            s.published_at              AS trigger_time,
            s.status,
            {"usr.user_id IS NOT NULL" if user_id else "FALSE"} AS is_read,
            {"COALESCE(usr.is_executed, FALSE)" if user_id else "FALSE"} AS is_executed,
            COUNT(*) OVER() AS _total
        FROM signals s
        JOIN strategies st ON st.id = s.strategy_id
        {user_join}
        {where_sql}
        ORDER BY s.published_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

        unread_count = 0
        if user_id:
            await cur.execute(
                """
                SELECT COUNT(*)::int
                FROM signals s
                LEFT JOIN user_signal_reads usr
                       ON usr.signal_id = s.id AND usr.user_id = %s
                WHERE s.status = 'active' AND usr.user_id IS NULL
                """,
                (user_id,),
            )
            row = await cur.fetchone()
            unread_count = next(iter(row.values())) if row else 0

    total = int(rows[0]["_total"]) if rows else 0
    items = [
        {
            "id": r["id"],
            "strategy": {"id": r["strategy_code"], "name": r["strategy_name"]},
            "signal_type": r["signal_type"],
            "action": r["action"],
            "direction": r["direction"] or "long",
            "symbol": r["symbol"],
            "symbol_name": r["symbol_name"],
            "exchange": r["exchange"],
            "trigger_price": _f(r["trigger_price"]),
            "target_price": _f(r["target_price"]),
            "stop_loss_price": _f(r["stop_loss_price"]),
            "confidence": _f(r["confidence"]),
            "urgency": r["urgency"],
            "reason": normalize_reason(r["reason"]),
            "trigger_time": _dt(r["trigger_time"]),
            "is_read": bool(r["is_read"]),
            "is_executed": bool(r["is_executed"]),
            "status": r["status"],
        }
        for r in rows
    ]
    return items, total, unread_count


# ---------------------------------------------------------------- unread summary


async def unread_summary(
    db: AsyncConnection,
    *,
    user_id: str | None,
) -> dict[str, Any]:
    """GET /signals/unread-summary

    user_id 为 None 时返回零值结构。
    """
    if not user_id:
        return {
            "total_unread": 0,
            "by_strategy": [],
            "by_urgency": {"critical": 0, "high": 0, "normal": 0, "low": 0},
        }

    async with db.cursor() as cur:
        # 总未读
        await cur.execute(
            """
            SELECT COUNT(*)::int AS cnt
            FROM signals s
            LEFT JOIN user_signal_reads usr
                   ON usr.signal_id = s.id AND usr.user_id = %s
            WHERE s.status = 'active' AND usr.user_id IS NULL
            """,
            (user_id,),
        )
        total = (await cur.fetchone())["cnt"]

        # 按策略
        await cur.execute(
            """
            SELECT st.strategy_code, st.name AS strategy_name,
                   COUNT(*)::int AS unread_count,
                   MAX(s.published_at) AS latest
            FROM signals s
            JOIN strategies st ON st.id = s.strategy_id
            LEFT JOIN user_signal_reads usr
                   ON usr.signal_id = s.id AND usr.user_id = %s
            WHERE s.status = 'active' AND usr.user_id IS NULL
            GROUP BY st.strategy_code, st.name
            ORDER BY unread_count DESC
            """,
            (user_id,),
        )
        by_strat_rows = await cur.fetchall()

        # 按紧急度
        await cur.execute(
            """
            SELECT s.urgency, COUNT(*)::int AS cnt
            FROM signals s
            LEFT JOIN user_signal_reads usr
                   ON usr.signal_id = s.id AND usr.user_id = %s
            WHERE s.status = 'active' AND usr.user_id IS NULL
            GROUP BY s.urgency
            """,
            (user_id,),
        )
        by_urg_rows = await cur.fetchall()

    by_urgency = {"critical": 0, "high": 0, "normal": 0, "low": 0}
    for r in by_urg_rows:
        if r["urgency"] in by_urgency:
            by_urgency[r["urgency"]] = r["cnt"]

    return {
        "total_unread": total,
        "by_strategy": [
            {
                "strategy_id": r["strategy_code"],
                "strategy_name": r["strategy_name"],
                "unread_count": r["unread_count"],
                "latest_signal_time": _dt(r["latest"]),
            }
            for r in by_strat_rows
        ],
        "by_urgency": by_urgency,
    }


# ---------------------------------------------------------------- detail


async def get_signal_detail(
    db: AsyncConnection,
    *,
    signal_id: str,
    signal_code: str,
    user_id: str | None,
) -> dict[str, Any]:
    """GET /signals/{signal_id}（signal_id 已是 UUID）。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT
                s.signal_code,
                st.strategy_code,
                st.name           AS strategy_name,
                st.category_id    AS strategy_category,
                st.risk_level     AS strategy_risk_level,
                s.type, s.action, s.direction,
                s.symbol, COALESCE(s.symbol_name, '') AS symbol_name,
                COALESCE(s.exchange, '') AS exchange,
                s.trigger_price, s.target_price, s.stop_loss_price,
                s.suggested_quantity, s.position_pct,
                s.confidence, s.urgency,
                COALESCE(s.reason, '') AS reason,
                s.reason_detail,
                s.published_at AS trigger_time,
                s.status, s.expire_at
            FROM signals s
            JOIN strategies st ON st.id = s.strategy_id
            WHERE s.id = %s
            """,
            (signal_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFound(f"signal not found: {signal_code}")

        # 行情快照（取最新一条）
        await cur.execute(
            """
            SELECT symbol, snapshot_time, open, high, low, close,
                   volume, open_interest, indicators
            FROM signal_market_snapshot
            WHERE signal_id = %s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (signal_id,),
        )
        snap = await cur.fetchone()

        # 用户状态
        user_state_row = None
        if user_id:
            await cur.execute(
                """
                SELECT read_at, is_executed, executed_price, note
                FROM user_signal_reads
                WHERE user_id = %s AND signal_id = %s
                """,
                (user_id, signal_id),
            )
            user_state_row = await cur.fetchone()

        # 历史表现：同 strategy + 同 type + 同 action，已结束的信号
        await cur.execute(
            """
            SELECT
                COUNT(*)::int                                                  AS cnt,
                COUNT(*) FILTER (WHERE result = 'win')::float
                  / NULLIF(COUNT(*) FILTER (WHERE result IN ('win','loss')), 0) AS win_rate,
                AVG(pnl_pct)                                                   AS avg_return,
                AVG(EXTRACT(EPOCH FROM (resolved_at - published_at)) / 86400.0) AS avg_holding_days
            FROM signals
            WHERE strategy_id = (SELECT strategy_id FROM signals WHERE id = %s)
              AND type = (SELECT type FROM signals WHERE id = %s)
              AND action = (SELECT action FROM signals WHERE id = %s)
              AND status != 'active'
              AND id != %s
            """,
            (signal_id, signal_id, signal_id, signal_id),
        )
        hist = await cur.fetchone() or {}

    reason_detail = row["reason_detail"] or {}
    market_snapshot = (
        _build_market_snapshot(snap) if snap else _empty_market_snapshot(row["symbol"])
    )

    return {
        "id": row["signal_code"],
        "strategy": {
            "id": row["strategy_code"],
            "name": row["strategy_name"],
            "category": row["strategy_category"] or "",
            "risk_level": row["strategy_risk_level"],
        },
        "signal_type": row["type"],
        "action": row["action"],
        "direction": row["direction"] or "long",
        "symbol": row["symbol"],
        "symbol_name": row["symbol_name"],
        "exchange": row["exchange"],
        "trigger_price": _f(row["trigger_price"]),
        "target_price": _f(row["target_price"]),
        "stop_loss_price": _f(row["stop_loss_price"]),
        "suggested_quantity": int(row["suggested_quantity"] or 0),
        "position_pct": _f(row["position_pct"]),
        "confidence": _f(row["confidence"]),
        "urgency": row["urgency"],
        "reason": normalize_reason(row["reason"]),
        "reason_detail": {
            "spread_current": _f(reason_detail.get("spread_current")),
            "spread_mean": _f(reason_detail.get("spread_mean")),
            "z_score": _f(reason_detail.get("z_score")),
            "trigger_rule": reason_detail.get("trigger_rule") or "",
        },
        "trigger_time": _dt(row["trigger_time"]),
        "status": row["status"],
        "expired_at": _dt(row["expire_at"]) if row["expire_at"] else None,
        "market_snapshot": market_snapshot,
        "historical_performance": {
            "similar_signals_count": int(hist.get("cnt") or 0),
            "win_rate": _f(hist.get("win_rate")),
            "avg_return": _f(hist.get("avg_return")),
            "avg_holding_days": _f(hist.get("avg_holding_days")),
        },
        "user_state": {
            "is_read": user_state_row is not None,
            "read_at": _dt(user_state_row["read_at"]) if user_state_row else None,
            "is_executed": bool(user_state_row["is_executed"]) if user_state_row else False,
            "executed_price": (
                float(user_state_row["executed_price"])
                if user_state_row and user_state_row["executed_price"] is not None
                else None
            ),
            "note": user_state_row["note"] if user_state_row else None,
        },
    }


def _build_market_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    indicators = snap.get("indicators") or {}
    return {
        "symbol": snap["symbol"],
        "snapshot_time": _dt(snap["snapshot_time"]),
        "open": _f(snap["open"]),
        "high": _f(snap["high"]),
        "low": _f(snap["low"]),
        "close": _f(snap["close"]),
        "volume": int(snap["volume"] or 0),
        "open_interest": int(snap["open_interest"] or 0),
        "indicators": {
            "ma5": _f(indicators.get("ma5")),
            "ma20": _f(indicators.get("ma20")),
            "rsi_14": _f(indicators.get("rsi_14")),
            "atr_14": _f(indicators.get("atr_14")),
        },
    }


def _empty_market_snapshot(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "snapshot_time": "",
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "close": 0.0,
        "volume": 0,
        "open_interest": 0,
        "indicators": {"ma5": 0.0, "ma20": 0.0, "rsi_14": 0.0, "atr_14": 0.0},
    }


# ---------------------------------------------------------------- mark read


async def mark_read(
    db: AsyncConnection,
    *,
    user_id: str,
    signal_id: str,
    signal_code: str,
) -> dict[str, Any]:
    """POST /signals/{signal_id}/read。幂等。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO user_signal_reads (user_id, signal_id, read_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id, signal_id) DO UPDATE SET
                read_at = COALESCE(user_signal_reads.read_at, EXCLUDED.read_at)
            RETURNING read_at
            """,
            (user_id, signal_id),
        )
        row = await cur.fetchone()

        # 计算 remaining_unread
        await cur.execute(
            """
            SELECT COUNT(*)::int AS cnt
            FROM signals s
            LEFT JOIN user_signal_reads usr
                   ON usr.signal_id = s.id AND usr.user_id = %s
            WHERE s.status = 'active' AND usr.user_id IS NULL
            """,
            (user_id,),
        )
        remaining = (await cur.fetchone())["cnt"]
        await db.commit()

    return {
        "signal_id": signal_code,
        "is_read": True,
        "read_at": _dt(row["read_at"]),
        "remaining_unread": remaining,
    }


# ---------------------------------------------------------------- execute


async def record_execute(
    db: AsyncConnection,
    *,
    user_id: str,
    signal_id: str,
    signal_code: str,
    body: ExecuteSignalIn,
) -> dict[str, Any]:
    """POST /signals/{signal_id}/execute。

    复用 user_signal_reads 表（schema 中执行字段挂在已读记录上）。
    UPSERT user_signal_reads 写入 is_executed / executed_price / executed_qty /
    executed_at / note。
    """
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT trigger_price, symbol, action, strategy_id, published_at
            FROM signals
            WHERE id = %s
            """,
            (signal_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFound(f"signal not found: {signal_code}")

        trigger_price = _f(row["trigger_price"])
        signal_symbol = row["symbol"]
        signal_action = row["action"]
        signal_sid = row["strategy_id"]
        signal_bar_dt = row["published_at"]
        executed_price = body.executed_price if body.executed_price is not None else trigger_price
        slippage = executed_price - trigger_price
        slippage_pct = (slippage / trigger_price) if trigger_price else 0.0
        executed_qty = body.executed_quantity or 0

        executed_at = body.executed_at or datetime.now(_TZ_SH)
        if executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc).astimezone(_TZ_SH)

        await cur.execute(
            """
            INSERT INTO user_signal_reads
                (user_id, signal_id, read_at, is_executed,
                 executed_price, executed_qty, executed_at, note)
            VALUES (%s, %s, NOW(), TRUE, %s, %s, %s, %s)
            ON CONFLICT (user_id, signal_id) DO UPDATE SET
                is_executed = TRUE,
                executed_price = EXCLUDED.executed_price,
                executed_qty = EXCLUDED.executed_qty,
                executed_at = EXCLUDED.executed_at,
                note = COALESCE(EXCLUDED.note, user_signal_reads.note)
            """,
            (
                user_id,
                signal_id,
                executed_price,
                body.executed_quantity,
                executed_at,
                body.note,
            ),
        )

        # Also write a strategy-level trade record for the trade journal.
        executed_price_decimal = Decimal(str(executed_price))
        notional = executed_price_decimal * Decimal(str(executed_qty))
        trade_bar_dt = signal_bar_dt or executed_at
        await cur.execute(
            """
            INSERT INTO strategy_trades
                (id, strategy_id, signal_id, symbol, action,
                 quantity, price, notional, fee, slippage, executed_at, bar_dt, tag)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                str(uuid4()),
                signal_sid,
                signal_id,
                signal_symbol,
                signal_action,
                executed_qty,
                executed_price_decimal,
                notional,
                Decimal("0"),  # fee — unknown at execution time
                Decimal(str(slippage)),
                executed_at,
                trade_bar_dt,
                body.note,
            ),
        )
        await reconcile_trades(signal_sid, conn=db)
        await db.commit()

    return {
        "signal_id": signal_code,
        "is_executed": True,
        "executed_price": executed_price,
        "executed_at": executed_at.isoformat(),
        "slippage": slippage,
        "slippage_pct": slippage_pct,
    }


# ---------------------------------------------------------------- helpers


def _f(v: Any) -> float:
    if v is None:
        return 0.0
    return float(v)


def _dt(v: datetime | None) -> str:
    if v is None:
        return ""
    return v.isoformat() if isinstance(v, datetime) else str(v)
