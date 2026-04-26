"""策略模块业务逻辑。

所有 SQL 都使用参数化绑定，禁止字符串拼接用户输入。
返回的 dict 字段已对齐前端 src/types/strategy.ts。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from getrich.apps.web.errors import BadRequest


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


# 排序字段白名单 → snapshot 列名（None 代表 strategies 表自身字段）
_SORT_FIELD_MAP: dict[str, tuple[str, str]] = {
    "sharpe": ("ps.sharpe_ratio", "DESC NULLS LAST"),
    "annualized_return": ("ps.annualized_return", "DESC NULLS LAST"),
    "max_drawdown": ("ps.max_drawdown", "ASC NULLS LAST"),  # 回撤越小越好
    "subscribers": ("s.subscriber_count", "DESC"),
    "newest": ("s.published_at", "DESC NULLS LAST"),
}


# ---------------------------------------------------------------- categories

async def list_categories(db: AsyncConnection) -> list[dict[str, Any]]:
    """GET /strategies/categories"""
    sql = """
        SELECT
            c.id,
            c.name,
            COALESCE(c.description, '') AS description,
            COALESCE(c.icon_url, '')    AS icon_url,
            COUNT(s.id)::int             AS strategy_count
        FROM strategy_categories c
        LEFT JOIN strategies s
               ON s.category_id = c.id AND s.pub_status = 'published'
        GROUP BY c.id, c.name, c.description, c.icon_url, c.sort_order
        ORDER BY c.sort_order ASC, c.id ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql)
        return await cur.fetchall()


# ---------------------------------------------------------------- list

async def list_strategies(
    db: AsyncConnection,
    *,
    user_id: str | None,
    category_id: str | None,
    asset_class: str | None,
    risk_level: str | None,
    market: str | None,
    keyword: str | None,
    status: str | None,
    sort: str,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /strategies"""
    if sort not in _SORT_FIELD_MAP:
        raise BadRequest(f"invalid sort: {sort}")

    # 拼装 WHERE
    conds: list[str] = ["s.pub_status = 'published'"]
    params: dict[str, Any] = {}

    if category_id:
        conds.append("s.category_id = %(category_id)s")
        params["category_id"] = category_id
    if asset_class:
        conds.append("s.asset_class = %(asset_class)s")
        params["asset_class"] = asset_class
    if risk_level:
        conds.append("s.risk_level = %(risk_level)s")
        params["risk_level"] = risk_level
    if market:
        conds.append("s.market = %(market)s")
        params["market"] = market
    if status:
        # 前端 status: 'active' | 'inactive'。映射到 run_status。
        if status == "active":
            conds.append("(s.run_status IN ('paper', 'live') OR s.run_status IS NULL)")
        elif status == "inactive":
            conds.append("s.run_status IN ('paused', 'retired')")
    if keyword:
        conds.append("(s.name ILIKE %(kw)s OR s.summary ILIKE %(kw)s)")
        params["kw"] = f"%{keyword}%"

    where_sql = " AND ".join(conds)
    order_col, order_dir = _SORT_FIELD_MAP[sort]

    params["limit"] = page.limit
    params["offset"] = page.offset

    sub_select = "FALSE"
    sub_join = ""
    if user_id:
        params["uid"] = user_id
        sub_select = "uss.id IS NOT NULL"
        sub_join = (
            " LEFT JOIN user_strategy_subscriptions uss "
            "   ON uss.strategy_id = s.id AND uss.user_id = %(uid)s "
            "   AND uss.status = 'active' AND uss.expire_date >= CURRENT_DATE "
        )

    sql = f"""
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (strategy_id)
                strategy_id,
                annualized_return,
                max_drawdown,
                sharpe_ratio,
                win_rate,
                total_return,
                snapshot_date
            FROM strategy_performance_snapshot
            ORDER BY strategy_id, snapshot_date DESC
        )
        SELECT
            s.strategy_code               AS id,
            s.name,
            COALESCE(s.summary, '')       AS description,
            s.asset_class,
            s.market,
            s.risk_level,
            COALESCE(s.cover_image, '')   AS cover_image,
            s.subscriber_count,
            COALESCE(s.subscription_monthly, 0)::float AS subscription_monthly,
            COALESCE(s.subscription_yearly, 0)::float  AS subscription_yearly,
            ps.annualized_return,
            ps.max_drawdown,
            ps.sharpe_ratio,
            ps.win_rate,
            ps.total_return,
            {sub_select} AS is_subscribed,
            COUNT(*) OVER() AS _total
        FROM strategies s
        LEFT JOIN latest_snapshot ps ON ps.strategy_id = s.id
        {sub_join}
        WHERE {where_sql}
        ORDER BY {order_col} {order_dir}, s.id
        LIMIT %(limit)s OFFSET %(offset)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0

    items: list[dict[str, Any]] = []
    for r in rows:
        items.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "asset_class": r["asset_class"],
            "market": r["market"],
            "risk_level": r["risk_level"],
            "cover_image": r["cover_image"],
            "subscriber_count": r["subscriber_count"],
            "is_subscribed": bool(r["is_subscribed"]),
            "subscription_price": {
                "monthly": float(r["subscription_monthly"] or 0),
                "yearly": float(r["subscription_yearly"] or 0),
            },
            "performance": {
                "annualized_return": _f(r["annualized_return"]),
                "max_drawdown": _f(r["max_drawdown"]),
                "sharpe_ratio": _f(r["sharpe_ratio"]),
                "win_rate": _f(r["win_rate"]),
            },
        })
    return items, total


# ---------------------------------------------------------------- detail

async def get_strategy_detail(
    db: AsyncConnection,
    strategy_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """GET /strategies/{strategy_id}（strategy_id 已是 UUID）。"""
    sql = """
        WITH latest_snapshot AS (
            SELECT DISTINCT ON (strategy_id)
                strategy_id,
                total_return,
                annualized_return,
                max_drawdown,
                sharpe_ratio,
                sortino_ratio,
                win_rate,
                total_trades
            FROM strategy_performance_snapshot
            WHERE strategy_id = %(sid)s
            ORDER BY strategy_id, snapshot_date DESC
        )
        SELECT
            s.strategy_code,
            s.name,
            COALESCE(s.description, '')   AS description,
            COALESCE(s.detail_html, '')   AS detail_html,
            s.category_id,
            c.name                        AS category_name,
            s.asset_class,
            s.market,
            s.risk_level,
            s.run_status,
            s.subscriber_count,
            s.backtest_start,
            s.backtest_end,
            COALESCE(s.subscription_monthly, 0)::float AS subscription_monthly,
            COALESCE(s.subscription_yearly, 0)::float  AS subscription_yearly,
            s.published_at,
            s.updated_at,
            s.author_id,
            ps.total_return,
            ps.annualized_return,
            ps.max_drawdown,
            ps.sharpe_ratio,
            ps.sortino_ratio,
            ps.win_rate,
            ps.total_trades
        FROM strategies s
        LEFT JOIN strategy_categories c ON c.id = s.category_id
        LEFT JOIN latest_snapshot ps    ON ps.strategy_id = s.id
        WHERE s.id = %(sid)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"sid": strategy_id})
        row = await cur.fetchone()

        # 标签
        await cur.execute(
            """
            SELECT t.name
            FROM strategy_tags st
            JOIN tags t ON t.id = st.tag_id
            WHERE st.strategy_id = %s
            ORDER BY t.name
            """,
            (strategy_id,),
        )
        tag_rows = await cur.fetchall()

        # 创建者（users 表字段未知，取最小集，缺字段返回空串）
        await cur.execute(
            "SELECT id FROM users WHERE id = %s",
            (row["author_id"],) if row else (None,),
        )
        creator_row = await cur.fetchone() if row else None

    if row is None:
        from getrich.apps.web.errors import NotFound
        raise NotFound(f"strategy not found: {strategy_id}")

    # 订阅信息
    sub_info = None
    is_subscribed = False
    if user_id:
        async with db.cursor() as cur:
            await cur.execute(
                """
                SELECT id, plan_type, start_date, expire_date, auto_renew
                FROM user_strategy_subscriptions
                WHERE user_id = %s AND strategy_id = %s
                  AND status = 'active' AND expire_date >= CURRENT_DATE
                ORDER BY expire_date DESC
                LIMIT 1
                """,
                (user_id, strategy_id),
            )
            sub_row = await cur.fetchone()
        if sub_row:
            is_subscribed = True
            sub_info = {
                "subscription_id": str(sub_row["id"]),
                "plan_type": sub_row["plan_type"],
                "start_date": sub_row["start_date"].isoformat(),
                "expire_date": sub_row["expire_date"].isoformat(),
                "auto_renew": sub_row["auto_renew"],
            }

    # run_status → 前端 status 映射
    run_status = row["run_status"] or "paper"
    status = "active" if run_status in ("paper", "live") else "inactive"

    return {
        "id": row["strategy_code"],
        "name": row["name"],
        "description": row["description"],
        "detail_html": row["detail_html"],
        "category": {
            "id": row["category_id"] or "",
            "name": row["category_name"] or "",
        },
        "asset_class": row["asset_class"],
        "market": row["market"],
        "risk_level": row["risk_level"],
        "status": status,
        "tags": [t["name"] for t in tag_rows],
        "creator": {
            "id": str(creator_row["id"]) if creator_row else "",
            "name": "",
            "avatar": "",
            "bio": "",
        },
        "performance": {
            "total_return": _f(row["total_return"]),
            "annualized_return": _f(row["annualized_return"]),
            "max_drawdown": _f(row["max_drawdown"]),
            "sharpe_ratio": _f(row["sharpe_ratio"]),
            "sortino_ratio": _f(row["sortino_ratio"]),
            "win_rate": _f(row["win_rate"]),
            "total_trades": int(row["total_trades"] or 0),
        },
        "backtest_period": {
            "start": _d(row["backtest_start"]),
            "end": _d(row["backtest_end"]),
        },
        "subscriber_count": row["subscriber_count"],
        "is_subscribed": is_subscribed,
        "subscription_info": sub_info,
        "subscription_price": {
            "monthly": float(row["subscription_monthly"] or 0),
            "yearly": float(row["subscription_yearly"] or 0),
        },
        "published_at": _dt(row["published_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


# ---------------------------------------------------------------- equity curve

_PERIOD_DAYS: dict[str, int | None] = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "3y": 365 * 3,
    "all": None,
}


async def get_equity_curve(
    db: AsyncConnection,
    *,
    strategy_id: str,
    strategy_code: str,
    period: str | None,
    start_date: date | None,
    end_date: date | None,
    include_benchmark: bool,
    include_drawdown: bool,
) -> dict[str, Any]:
    """GET /strategies/{strategy_id}/equity-curve"""
    if period and period not in _PERIOD_DAYS:
        raise BadRequest(f"invalid period: {period}")

    # 计算起止
    if start_date is None and period:
        days = _PERIOD_DAYS[period]
        if days is not None:
            start_date = date.today() - timedelta(days=days)

    conds: list[str] = ["strategy_id = %(sid)s"]
    params: dict[str, Any] = {"sid": strategy_id}
    if start_date:
        conds.append("trade_date >= %(start)s")
        params["start"] = start_date
    if end_date:
        conds.append("trade_date <= %(end)s")
        params["end"] = end_date
    where_sql = " AND ".join(conds)

    sql = f"""
        SELECT trade_date, nav, cumulative_return, daily_return,
               drawdown, benchmark_nav, position_ratio
        FROM strategy_equity_curve
        WHERE {where_sql}
        ORDER BY trade_date ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    equity_curve = [
        {
            "date": _d(r["trade_date"]),
            "nav": _f(r["nav"]),
            "cumulative_return": _f(r["cumulative_return"]),
            "daily_return": _f(r["daily_return"]),
            "position_ratio": _f(r["position_ratio"]),
        }
        for r in rows
    ]
    benchmark_curve = (
        [{"date": _d(r["trade_date"]), "nav": _f(r["benchmark_nav"])}
         for r in rows if r["benchmark_nav"] is not None]
        if include_benchmark else []
    )
    drawdown_curve = (
        [{"date": _d(r["trade_date"]), "drawdown": _f(r["drawdown"])}
         for r in rows if r["drawdown"] is not None]
        if include_drawdown else []
    )

    return {
        "strategy_id": strategy_code,
        "period": {
            "start": _d(rows[0]["trade_date"]) if rows else "",
            "end": _d(rows[-1]["trade_date"]) if rows else "",
        },
        "equity_curve": equity_curve,
        "benchmark_curve": benchmark_curve,
        "drawdown_curve": drawdown_curve,
        "total_points": len(equity_curve),
    }


# ---------------------------------------------------------------- monthly returns

async def get_monthly_returns(
    db: AsyncConnection,
    *,
    strategy_id: str,
    strategy_code: str,
) -> dict[str, Any]:
    """GET /strategies/{strategy_id}/monthly-returns"""
    sql = """
        SELECT year, month, monthly_return
        FROM strategy_monthly_returns
        WHERE strategy_id = %s
        ORDER BY year ASC, month ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, (strategy_id,))
        rows = await cur.fetchall()

    matrix_map: dict[int, list[float | None]] = {}
    for r in rows:
        year = int(r["year"])
        month = int(r["month"])  # 1..12
        ret = _f(r["monthly_return"])
        if year not in matrix_map:
            matrix_map[year] = [None] * 12
        matrix_map[year][month - 1] = ret

    matrix: list[dict[str, Any]] = []
    for year in sorted(matrix_map.keys()):
        months = matrix_map[year]
        # 复利累计：(1+r1)(1+r2)... - 1，遇 None 跳过
        yr = 1.0
        any_value = False
        for m in months:
            if m is not None:
                yr *= 1 + m
                any_value = True
        yearly = (yr - 1.0) if any_value else 0.0
        matrix.append({"year": year, "months": months, "yearly_return": yearly})

    return {"strategy_id": strategy_code, "matrix": matrix}


# ---------------------------------------------------------------- backtest report

async def get_backtest_report(
    db: AsyncConnection,
    *,
    strategy_id: str,
    strategy_code: str,
) -> dict[str, Any]:
    """GET /strategies/{strategy_id}/backtest-report"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT s.backtest_start, s.backtest_end,
                   ps.total_return, ps.annualized_return, ps.max_drawdown,
                   ps.max_drawdown_start, ps.max_drawdown_end, ps.max_drawdown_recovery,
                   ps.sharpe_ratio,
                   ps.var_95, ps.cvar_95, ps.beta, ps.alpha,
                   ps.total_trades, ps.win_rate, ps.profit_factor,
                   ps.avg_win, ps.avg_loss, ps.avg_holding_days
            FROM strategies s
            LEFT JOIN LATERAL (
                SELECT *
                FROM strategy_performance_snapshot
                WHERE strategy_id = s.id
                ORDER BY snapshot_date DESC
                LIMIT 1
            ) ps ON TRUE
            WHERE s.id = %s
            """,
            (strategy_id,),
        )
        row = await cur.fetchone()

        # 单日最大盈亏（从 equity_curve 推）
        await cur.execute(
            """
            SELECT MIN(daily_return) AS max_loss, MAX(daily_return) AS max_gain
            FROM strategy_equity_curve
            WHERE strategy_id = %s
            """,
            (strategy_id,),
        )
        ec_row = await cur.fetchone()

        # 年度绩效（从 monthly returns 聚合）
        await cur.execute(
            """
            SELECT year,
                   EXP(SUM(LN(1 + monthly_return))) - 1 AS yearly_return,
                   COUNT(*) AS months_present
            FROM strategy_monthly_returns
            WHERE strategy_id = %s
            GROUP BY year
            ORDER BY year ASC
            """,
            (strategy_id,),
        )
        annual_rows = await cur.fetchall()

    if row is None:
        from getrich.apps.web.errors import NotFound
        raise NotFound(f"strategy not found: {strategy_code}")

    annual_performance = [
        {
            "year": int(r["year"]),
            "return": _f(r["yearly_return"]),
            # 年度 max_drawdown / sharpe / trades 暂未在 schema 中按年聚合，先填 0
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "trades": 0,
        }
        for r in annual_rows
    ]

    return {
        "strategy_id": strategy_code,
        "summary": {
            "backtest_start": _d(row["backtest_start"]),
            "backtest_end": _d(row["backtest_end"]),
            "initial_capital": 1_000_000.0,  # config 字段未拆分；先返回常量
            "final_capital": 1_000_000.0 * (1 + (_f(row["total_return"]) or 0)),
            "total_return": _f(row["total_return"]),
            "annualized_return": _f(row["annualized_return"]),
            "max_drawdown": _f(row["max_drawdown"]),
            "max_drawdown_start": _d(row["max_drawdown_start"]),
            "max_drawdown_end": _d(row["max_drawdown_end"]),
            "max_drawdown_recovery": _d(row["max_drawdown_recovery"]),
            "sharpe_ratio": _f(row["sharpe_ratio"]),
        },
        "risk_analysis": {
            "var_95": _f(row["var_95"]),
            "cvar_95": _f(row["cvar_95"]),
            "beta": _f(row["beta"]),
            "alpha": _f(row["alpha"]),
            "max_single_day_loss": _f(ec_row["max_loss"]) if ec_row else 0.0,
            "max_single_day_gain": _f(ec_row["max_gain"]) if ec_row else 0.0,
        },
        "trade_analysis": {
            "total_trades": int(row["total_trades"] or 0),
            "win_rate": _f(row["win_rate"]),
            "avg_trade_return": _f(row["avg_win"]),
            "avg_holding_days": _f(row["avg_holding_days"]),
            "profit_factor": _f(row["profit_factor"]),
        },
        "annual_performance": annual_performance,
    }


# ---------------------------------------------------------------- trades

async def list_trades(
    db: AsyncConnection,
    *,
    strategy_id: str,
    strategy_code: str,
    start_date: date | None,
    end_date: date | None,
    action: Literal["all", "buy", "sell"] | None,
    result: Literal["all", "win", "loss"] | None,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /strategies/{strategy_id}/trades

    注：strategy_trades 表在当前 PG schema 中尚未建表。
    本期返回空列表，待 schema 补齐后再实现。
    """
    _ = (db, strategy_id, start_date, end_date, action, result, page)
    # TODO: 待 strategy_trades 表上线后实现
    return [], 0


# ---------------------------------------------------------------- signals of strategy

async def list_signals_of_strategy(
    db: AsyncConnection,
    *,
    strategy_id: str,
    type_: str | None,
    action: str | None,
    status: str | None,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /strategies/{strategy_id}/signals"""
    conds: list[str] = ["strategy_id = %(sid)s"]
    params: dict[str, Any] = {"sid": strategy_id, "limit": page.limit, "offset": page.offset}
    if type_ and type_ != "all":
        conds.append("type = %(type)s")
        params["type"] = type_
    if action and action != "all":
        conds.append("action = %(action)s")
        params["action"] = action
    if status and status != "all":
        conds.append("status = %(status)s")
        params["status"] = status

    where_sql = " AND ".join(conds)

    sql = f"""
        SELECT signal_code AS id, type AS signal_type, action,
               symbol, trigger_price, confidence, urgency,
               published_at AS trigger_time, status,
               COUNT(*) OVER() AS _total
        FROM signals
        WHERE {where_sql}
        ORDER BY published_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    items = [
        {
            "id": r["id"],
            "signal_type": r["signal_type"],
            "action": r["action"],
            "symbol": r["symbol"],
            "trigger_price": _f(r["trigger_price"]),
            "confidence": _f(r["confidence"]),
            "urgency": r["urgency"],
            "trigger_time": _dt(r["trigger_time"]),
            "is_read": False,
            "is_executed": False,
            "status": r["status"],
        }
        for r in rows
    ]
    return items, total


# ---------------------------------------------------------------- helpers

def _f(v: Any) -> float:
    """Decimal/float/None → float（None 视为 0.0，避免前端 NaN）。"""
    if v is None:
        return 0.0
    return float(v)


def _d(v: date | None) -> str:
    if v is None:
        return ""
    return v.isoformat() if isinstance(v, date) else str(v)


def _dt(v: datetime | None) -> str:
    if v is None:
        return ""
    return v.isoformat() if isinstance(v, datetime) else str(v)
