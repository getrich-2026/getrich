"""选股展示模块的读逻辑。

接口契约：``getrich-design/strategy-signal/api-spec/选股展示模块.openapi.json``。

三条贯穿全模块的口径，改代码前务必先读：

1. **不返回任何业绩数字**（年化、胜率、净值）—— P0 的选股策略压根没有这些数据，
   全部返 null 会让前端误以为策略跑输了。
2. **不返回 ``score`` / ``suggest_weight``** —— 各策略评分量纲自定、跨策略不可比，
   且未声明取值范围，前端无法正确渲染。启用前需先补 ``score_percentile``。
3. **三种空态必须能区分**，且全部走 HTTP 200：``updated`` 有标的 /
   ``empty`` 基金经理确认空仓 / ``not_updated`` 尚未上传。后两者混为一谈会让
   用户误以为策略失效。

``pick`` schema 不在连接池的 search_path 里，所有 SQL 显式写 ``pick.`` 前缀。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from gr_api.errors import BadRequest
from gr_api.services import pick_symbols
from gr_api.services.resolver import resolve_strategy_ref


if TYPE_CHECKING:
    from gr_api.pagination import PageParams
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)

#: 列表页排序白名单 → (SQL 表达式, 是否可反向)。
_LIST_SORT_MAP = {
    "latest_trading_day": "lb.trading_day",
    "subscribers": "s.subscriber_count",
    "newest": "s.published_at",
}

#: 标的池排序白名单。``rank`` 为空的行统一排末尾（基金经理没填时系统不推断）。
_ITEM_SORT_MAP = {
    "rank": "i.rank ASC NULLS LAST, i.symbol ASC",
    "entry_date": "i.entry_date ASC, i.symbol ASC",
    "symbol": "i.symbol ASC",
}

#: 计算 ``holding_trading_days`` 的子查询：按交易日计数，不是自然日。
_HOLDING_DAYS_SQL = """
    COALESCE((
        SELECT COUNT(*)::int
        FROM meta.trading_calendar c
        WHERE c.exchange = %(calendar_exchange)s
          AND c.is_open
          AND c.trading_day BETWEEN i.entry_date AND i.trading_day
    ), 0)
"""

_ITEM_COLUMNS_SQL = f"""
    i.symbol, i.exchange, i.symbol_name, i.asset_class, i.direction,
    i.option_type, i.rank, i.entry_date, i.entry_date_source,
    i.reason_text, i.trading_day,
    {_HOLDING_DAYS_SQL} AS calendar_days
"""

_STRATEGY_BASE_SQL = """
    s.strategy_code                 AS id,
    s.name,
    COALESCE(s.summary, s.description, '') AS description,
    s.category_id,
    cat.name                        AS category_name,
    s.asset_class,
    s.market,
    s.risk_level,
    s.run_status,
    COALESCE(s.cover_image, '')     AS cover_image,
    s.author_id,
    u.name                          AS author_name,
    COALESCE(s.subscription_monthly, 0)::float AS subscription_monthly,
    COALESCE(s.subscription_yearly, 0)::float  AS subscription_yearly,
    COALESCE((
        SELECT array_agg(t.name ORDER BY t.id)
        FROM strategy_tags st JOIN tags t ON t.id = st.tag_id
        WHERE st.strategy_id = s.id
    ), '{}') AS tags,
    lb.trading_day  AS batch_trading_day,
    lb.item_count   AS batch_item_count,
    lb.created_at   AS batch_created_at,
    lb.note         AS batch_note
"""

#: 每个策略最新一期的 active 批次。LATERAL 一次取到，避免按策略数 N+1 查询。
_LATEST_BATCH_JOIN = """
    LEFT JOIN LATERAL (
        SELECT b.trading_day, b.item_count, b.created_at, b.note
        FROM pick.batch b
        WHERE b.strategy_id = s.id AND b.status = 'active'
        ORDER BY b.trading_day DESC
        LIMIT 1
    ) lb ON TRUE
"""


# ---------------------------------------------------------------- 策略列表


async def list_pick_strategies(
    db: AsyncConnection,
    *,
    user_id: str | None,
    category_id: str | None,
    keyword: str | None,
    data_state: str,
    status: str,
    sort: str,
    sort_order: str,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /pick-strategies —— 选股策略列表。

    只返回 ``strategy_kind = 'pick'`` 的已发布策略：未回填 ``strategy_kind``
    的策略不会误入选股列表（见迁移 035 的说明）。
    """
    if sort not in _LIST_SORT_MAP:
        raise BadRequest(f"invalid sort: {sort}")
    if sort_order not in ("asc", "desc"):
        raise BadRequest(f"invalid sort_order: {sort_order}")

    conds = ["s.strategy_kind = 'pick'", "s.pub_status = 'published'"]
    params: dict[str, Any] = {"limit": page.limit, "offset": page.offset}

    if category_id:
        conds.append("s.category_id = %(category_id)s")
        params["category_id"] = category_id
    if keyword:
        conds.append(
            "(s.name ILIKE %(kw)s OR s.summary ILIKE %(kw)s OR EXISTS ("
            "  SELECT 1 FROM strategy_tags st JOIN tags t ON t.id = st.tag_id"
            "  WHERE st.strategy_id = s.id AND t.name ILIKE %(kw)s))"
        )
        params["kw"] = f"%{keyword}%"
    if status == "active":
        conds.append("(s.run_status IN ('paper', 'live') OR s.run_status IS NULL)")
    elif status != "all":
        raise BadRequest(f"invalid status: {status}")

    # data_state 是批次层面的状态，不是策略状态：updated 有标的、
    # empty 确认空仓、not_updated 从未上传过。
    if data_state == "updated":
        conds.append("lb.item_count > 0")
    elif data_state == "empty":
        conds.append("lb.item_count = 0")
    elif data_state == "not_updated":
        conds.append("lb.trading_day IS NULL")
    elif data_state != "all":
        raise BadRequest(f"invalid data_state: {data_state}")

    sub_select, sub_join = _subscription_fragments(user_id, params)
    direction = "DESC NULLS LAST" if sort_order == "desc" else "ASC NULLS LAST"

    sql = f"""
        SELECT
            {_STRATEGY_BASE_SQL},
            {sub_select} AS is_subscribed,
            COUNT(*) OVER() AS _total
        FROM strategies s
        LEFT JOIN strategy_categories cat ON cat.id = s.category_id
        LEFT JOIN users u ON u.id = s.author_id
        {_LATEST_BATCH_JOIN}
        {sub_join}
        WHERE {" AND ".join(conds)}
        ORDER BY {_LIST_SORT_MAP[sort]} {direction}, s.strategy_code
        LIMIT %(limit)s OFFSET %(offset)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return [_format_strategy_brief(row) for row in rows], total


# ---------------------------------------------------------------- 策略详情


async def get_pick_strategy(
    db: AsyncConnection,
    *,
    strategy_ref: str,
    user_id: str | None,
) -> dict[str, Any]:
    """GET /pick-strategies/{strategy_id} —— 详情页头部。

    标的池不在本接口返回（走 ``/picks``），这样详情页能先出骨架、
    表格异步加载。
    """
    strategy = await resolve_strategy_ref(db, strategy_ref)
    params: dict[str, Any] = {"sid": strategy["id"]}
    sub_select, sub_join = _subscription_fragments(user_id, params)

    sql = f"""
        SELECT
            {_STRATEGY_BASE_SQL},
            COALESCE(s.detail_html, '') AS detail_html,
            s.created_at,
            s.updated_at,
            {sub_select} AS is_subscribed,
            dr.first_trading_day,
            dr.last_trading_day,
            dr.total_days
        FROM strategies s
        LEFT JOIN strategy_categories cat ON cat.id = s.category_id
        LEFT JOIN users u ON u.id = s.author_id
        {_LATEST_BATCH_JOIN}
        LEFT JOIN LATERAL (
            SELECT MIN(b.trading_day) AS first_trading_day,
                   MAX(b.trading_day) AS last_trading_day,
                   COUNT(*)::int      AS total_days
            FROM pick.batch b
            WHERE b.strategy_id = s.id AND b.status = 'active'
        ) dr ON TRUE
        {sub_join}
        WHERE s.id = %(sid)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()

    if row is None:  # pragma: no cover — resolve_strategy_ref 已经保证存在
        raise BadRequest(f"strategy not found: {strategy_ref}")

    data = _format_strategy_brief(row)
    data.update(
        {
            "detail_html": row["detail_html"],
            "data_range": {
                # 「有 active 批次的交易日总数」，不含漏传的日子。
                "first_trading_day": _d(row["first_trading_day"]),
                "last_trading_day": _d(row["last_trading_day"]),
                "total_days": int(row["total_days"] or 0),
            },
            "created_at": _dt(row["created_at"]),
            "updated_at": _dt(row["updated_at"]),
        }
    )
    return data


# ---------------------------------------------------------------- 标的池


async def list_strategy_picks(
    db: AsyncConnection,
    *,
    strategy_ref: str,
    trading_day: date | None,
    sort: str,
    page: PageParams,
) -> dict[str, Any]:
    """GET /pick-strategies/{strategy_id}/picks —— 某一交易日的完整标的池。

    ``trading_day`` 留空取最新一期（由后端决定「最新」，免得前端算错节假日）。
    三种空态都返 200，靠 ``batch.data_state`` 区分。
    """
    if sort not in _ITEM_SORT_MAP:
        raise BadRequest(f"invalid sort: {sort}")

    strategy = await resolve_strategy_ref(db, strategy_ref)
    strategy_id = strategy["id"]
    batch = await _batch_of_day(db, strategy_id, trading_day)

    header = {
        "strategy": {"id": strategy["strategy_code"], "name": strategy["name"]},
        "batch": _format_batch_info(batch),
    }
    if batch is None:
        # 该交易日没有 active 批次：尚未上传，不是错误，照样返 200。
        return {**header, "list": [], "total": 0}

    params = {
        "sid": strategy_id,
        "td": batch["trading_day"],
        "calendar_exchange": pick_symbols.CALENDAR_EXCHANGE,
        "limit": page.limit,
        "offset": page.offset,
    }
    sql = f"""
        SELECT {_ITEM_COLUMNS_SQL},
               COUNT(*) OVER() AS _total
        FROM pick.item i
        WHERE i.strategy_id = %(sid)s AND i.trading_day = %(td)s
        ORDER BY {_ITEM_SORT_MAP[sort]}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return {**header, "list": [_format_item(row) for row in rows], "total": total}


async def list_pick_trading_days(
    db: AsyncConnection,
    *,
    strategy_ref: str,
    start_date: date | None,
    end_date: date | None,
    limit: int,
) -> dict[str, Any]:
    """GET /pick-strategies/{strategy_id}/trading-days —— 历史日期选择器数据源。

    只列出**确实有批次**的交易日，漏传的日期不会出现 —— 这是有意的，
    与 ``data_state='not_updated'`` 的语义一致。
    """
    strategy = await resolve_strategy_ref(db, strategy_ref)
    conds = ["b.strategy_id = %(sid)s", "b.status = 'active'"]
    params: dict[str, Any] = {"sid": strategy["id"], "limit": limit}
    if start_date:
        conds.append("b.trading_day >= %(start)s")
        params["start"] = start_date
    if end_date:
        conds.append("b.trading_day <= %(end)s")
        params["end"] = end_date

    sql = f"""
        SELECT b.trading_day, b.item_count, COUNT(*) OVER() AS _total
        FROM pick.batch b
        WHERE {" AND ".join(conds)}
        ORDER BY b.trading_day DESC
        LIMIT %(limit)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    return {
        "list": [
            {
                "trading_day": _d(row["trading_day"]),
                "item_count": int(row["item_count"]),
                "data_state": "updated" if row["item_count"] > 0 else "empty",
            }
            for row in rows
        ],
        "total": int(rows[0]["_total"]) if rows else 0,
    }


# ---------------------------------------------------------------- 跨策略汇总


async def list_latest_picks(
    db: AsyncConnection,
    *,
    user_id: str | None,
    category_id: str | None,
    subscribed_only: bool,
    preview_size: int,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /picks/latest —— 首页「今日推荐」聚合视图。

    **各策略的 trading_day 可能不同**（有的今天已更新、有的还没传），
    所以日期挂在每个策略的 batch 上，不在响应顶层。

    两条 SQL 搞定：先取每策略最新批次，再用窗口函数一次取出各批次的 TopN，
    不按策略数 N+1 查询。
    """
    conds = ["s.strategy_kind = 'pick'", "s.pub_status = 'published'"]
    params: dict[str, Any] = {"limit": page.limit, "offset": page.offset}
    if category_id:
        conds.append("s.category_id = %(category_id)s")
        params["category_id"] = category_id

    sub_select, sub_join = _subscription_fragments(user_id, params)
    if subscribed_only:
        if not user_id:
            return [], 0
        conds.append("uss.id IS NOT NULL")

    sql = f"""
        SELECT
            s.strategy_code AS id,
            s.name,
            s.category_id,
            cat.name AS category_name,
            lb.batch_id,
            lb.trading_day  AS batch_trading_day,
            lb.item_count   AS batch_item_count,
            lb.created_at   AS batch_created_at,
            lb.note         AS batch_note,
            {sub_select} AS is_subscribed,
            COUNT(*) OVER() AS _total
        FROM strategies s
        LEFT JOIN strategy_categories cat ON cat.id = s.category_id
        JOIN LATERAL (
            SELECT b.batch_id, b.trading_day, b.item_count, b.created_at, b.note
            FROM pick.batch b
            WHERE b.strategy_id = s.id AND b.status = 'active'
            ORDER BY b.trading_day DESC
            LIMIT 1
        ) lb ON TRUE
        {sub_join}
        WHERE {" AND ".join(conds)}
        ORDER BY lb.trading_day DESC, s.strategy_code
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    if not rows:
        return [], 0

    total = int(rows[0]["_total"])
    batch_ids = [int(row["batch_id"]) for row in rows]
    preview = await _preview_items(db, batch_ids, preview_size)

    return [
        {
            "strategy": {
                "id": row["id"],
                "name": row["name"],
                "category": {"id": row["category_id"], "name": row["category_name"]},
            },
            "batch": _format_batch_info(
                {
                    "trading_day": row["batch_trading_day"],
                    "item_count": row["batch_item_count"],
                    "created_at": row["batch_created_at"],
                    "note": row["batch_note"],
                }
            ),
            "items": preview.get(int(row["batch_id"]), []),
            "is_subscribed": bool(row["is_subscribed"]),
        }
        for row in rows
    ], total


async def list_picks_by_symbol(
    db: AsyncConnection,
    *,
    symbol_full: str,
    start_date: date | None,
    end_date: date | None,
    in_pool_only: bool,
    page: PageParams,
) -> dict[str, Any]:
    """GET /picks/by-symbol/{symbol} —— 这只票被哪些策略选过。

    按「连续在池区间」聚合而不是逐日返回：同一策略连续持有 30 个交易日应
    返回 1 条（含 ``entry_date`` 与 ``last_seen_trading_day``），不是 30 条。
    区间由 ``entry_date`` 相同的记录归并得到 —— 重新入池会拿到新的
    ``entry_date``，自然分成两段。
    """
    try:
        parsed = pick_symbols.parse_symbol(symbol_full)
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc

    conds = ["i.symbol = %(symbol)s", "i.exchange = %(exchange)s"]
    params: dict[str, Any] = {
        "symbol": parsed.symbol,
        "exchange": parsed.exchange,
        "calendar_exchange": pick_symbols.CALENDAR_EXCHANGE,
        "limit": page.limit,
        "offset": page.offset,
    }
    if start_date:
        conds.append("i.trading_day >= %(start)s")
        params["start"] = start_date
    if end_date:
        conds.append("i.trading_day <= %(end)s")
        params["end"] = end_date

    outer_conds = ["TRUE"]
    if in_pool_only:
        outer_conds.append("r.last_seen = lb.latest_day")

    sql = f"""
        WITH runs AS (
            SELECT i.strategy_id,
                   i.entry_date,
                   MAX(i.trading_day) AS last_seen
            FROM pick.item i
            WHERE {" AND ".join(conds)}
            GROUP BY i.strategy_id, i.entry_date
        ),
        latest AS (
            -- 只算命中的那几个策略。不加这条限制就会对整张 batch 表做
            -- 聚合，代价随平台上所有策略的历史线性增长，而这里只需要
            -- 反查到的这几个。
            SELECT b.strategy_id, MAX(b.trading_day) AS latest_day
            FROM pick.batch b
            WHERE b.status = 'active'
              AND b.strategy_id IN (SELECT strategy_id FROM runs)
            GROUP BY b.strategy_id
        )
        SELECT
            s.strategy_code AS strategy_id,
            s.name          AS strategy_name,
            r.entry_date,
            r.last_seen,
            (r.last_seen = lb.latest_day) AS still_in_pool,
            i.rank          AS latest_rank,
            i.reason_text   AS latest_reason_text,
            i.symbol_name,
            COALESCE((
                SELECT COUNT(*)::int
                FROM meta.trading_calendar c
                WHERE c.exchange = %(calendar_exchange)s
                  AND c.is_open
                  AND c.trading_day BETWEEN r.entry_date AND r.last_seen
            ), 0) AS calendar_days,
            COUNT(*) OVER() AS _total
        FROM runs r
        JOIN strategies s ON s.id = r.strategy_id
        LEFT JOIN latest lb ON lb.strategy_id = r.strategy_id
        JOIN pick.item i
          ON i.strategy_id = r.strategy_id
         AND i.trading_day = r.last_seen
         AND i.symbol = %(symbol)s
         AND i.exchange = %(exchange)s
        WHERE {" AND ".join(outer_conds)}
        ORDER BY r.last_seen DESC, s.strategy_code
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return {
        "symbol": parsed.symbol_full,
        "symbol_name": rows[0]["symbol_name"] if rows else None,
        "list": [
            {
                "strategy": {"id": row["strategy_id"], "name": row["strategy_name"]},
                "entry_date": _d(row["entry_date"]),
                "last_seen_trading_day": _d(row["last_seen"]),
                "still_in_pool": bool(row["still_in_pool"]),
                "holding_trading_days": _holding_days(
                    row["calendar_days"], row["entry_date"], row["last_seen"]
                ),
                "latest_rank": row["latest_rank"],
                "latest_reason_text": row["latest_reason_text"],
            }
            for row in rows
        ],
        "total": total,
    }


# ---------------------------------------------------------------- 管理端


async def list_pick_batches(
    db: AsyncConnection,
    *,
    strategy_ref: str | None,
    start_date: date | None,
    end_date: date | None,
    status: str,
    page: PageParams,
) -> tuple[list[dict[str, Any]], int]:
    """GET /admin/pick-batches —— 上传批次列表（管理端）。

    默认只返回 ``active``。``superseded`` 是重传后被替换的历史批次，
    保留用于追溯「这一期重传过几次」，需显式传 ``status=all``。
    """
    if status not in ("active", "superseded", "all"):
        raise BadRequest(f"invalid status: {status}")

    conds: list[str] = []
    params: dict[str, Any] = {"limit": page.limit, "offset": page.offset}
    if status != "all":
        conds.append("b.status = %(status)s")
        params["status"] = status
    if strategy_ref:
        strategy = await resolve_strategy_ref(db, strategy_ref)
        conds.append("b.strategy_id = %(sid)s")
        params["sid"] = strategy["id"]
    if start_date:
        conds.append("b.trading_day >= %(start)s")
        params["start"] = start_date
    if end_date:
        conds.append("b.trading_day <= %(end)s")
        params["end"] = end_date

    where_sql = " AND ".join(conds) if conds else "TRUE"
    sql = f"""
        SELECT
            b.batch_id, b.trading_day, b.source, b.item_count, b.status,
            b.note, b.created_at, b.import_job_id, b.uploaded_by,
            s.strategy_code, s.name AS strategy_name,
            u.name AS uploaded_by_name,
            COUNT(*) OVER() AS _total
        FROM pick.batch b
        JOIN strategies s ON s.id = b.strategy_id
        LEFT JOIN users u ON u.id = b.uploaded_by
        WHERE {where_sql}
        ORDER BY b.trading_day DESC, b.batch_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return [
        {
            "batch_id": int(row["batch_id"]),
            "strategy": {"id": row["strategy_code"], "name": row["strategy_name"]},
            "trading_day": _d(row["trading_day"]),
            "source": row["source"],
            "item_count": int(row["item_count"]),
            "status": row["status"],
            "uploaded_by": {
                "id": str(row["uploaded_by"]) if row["uploaded_by"] else None,
                "name": row["uploaded_by_name"],
            },
            # 本仓还没有 import_jobs 表，这两个字段目前恒为 null；
            # 接上管理后台上传通道后自然有值。
            "import_job_id": str(row["import_job_id"]) if row["import_job_id"] else None,
            "file_name": None,
            "note": row["note"],
            "created_at": _dt(row["created_at"]),
        }
        for row in rows
    ], total


# ---------------------------------------------------------------- 内部工具


def _subscription_fragments(user_id: str | None, params: dict[str, Any]) -> tuple[str, str]:
    """订阅状态的 SELECT 片段与 JOIN 片段（口径与 services/strategy.py 一致）。"""
    if not user_id:
        return "FALSE", ""
    params["uid"] = user_id
    return (
        "uss.id IS NOT NULL",
        " LEFT JOIN user_strategy_subscriptions uss "
        "   ON uss.strategy_id = s.id AND uss.user_id = %(uid)s "
        "   AND uss.status = 'active' AND uss.expire_date >= CURRENT_DATE ",
    )


async def _batch_of_day(
    db: AsyncConnection,
    strategy_id: Any,
    trading_day: date | None,
) -> dict[str, Any] | None:
    """取指定交易日的 active 批次；``trading_day`` 为空则取最新一期。"""
    conds = ["b.strategy_id = %(sid)s", "b.status = 'active'"]
    params: dict[str, Any] = {"sid": strategy_id}
    if trading_day is not None:
        conds.append("b.trading_day = %(td)s")
        params["td"] = trading_day

    sql = f"""
        SELECT b.batch_id, b.trading_day, b.item_count, b.created_at, b.note
        FROM pick.batch b
        WHERE {" AND ".join(conds)}
        ORDER BY b.trading_day DESC
        LIMIT 1
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def _preview_items(
    db: AsyncConnection,
    batch_ids: list[int],
    preview_size: int,
) -> dict[int, list[dict[str, Any]]]:
    """一次取出多个批次各自的前 N 条，按 batch_id 分组返回。"""
    sql = f"""
        SELECT * FROM (
            SELECT i.batch_id,
                   {_ITEM_COLUMNS_SQL},
                   ROW_NUMBER() OVER (
                       PARTITION BY i.batch_id
                       ORDER BY i.rank ASC NULLS LAST, i.symbol ASC
                   ) AS rn
            FROM pick.item i
            WHERE i.batch_id = ANY(%(ids)s)
        ) ranked
        WHERE rn <= %(n)s
        ORDER BY batch_id, rn
    """
    async with db.cursor() as cur:
        await cur.execute(
            sql,
            {
                "ids": batch_ids,
                "n": preview_size,
                "calendar_exchange": pick_symbols.CALENDAR_EXCHANGE,
            },
        )
        rows = await cur.fetchall()

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["batch_id"]), []).append(_format_item(row))
    return grouped


def _format_strategy_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "category": {"id": row["category_id"], "name": row["category_name"]},
        "asset_class": row["asset_class"],
        "market": row["market"],
        "risk_level": row["risk_level"],
        "status": _run_status_to_public(row["run_status"]),
        "cover_image": row["cover_image"],
        "tags": list(row["tags"] or []),
        "creator": {
            "id": str(row["author_id"]) if row["author_id"] else None,
            "name": row["author_name"],
        },
        "latest_batch": _format_batch_info(
            {
                "trading_day": row["batch_trading_day"],
                "item_count": row["batch_item_count"],
                "created_at": row["batch_created_at"],
                "note": row["batch_note"],
            }
        ),
        "is_subscribed": bool(row["is_subscribed"]),
        "subscription_price": {
            "monthly": float(row["subscription_monthly"] or 0),
            "yearly": float(row["subscription_yearly"] or 0),
        },
    }


def _format_batch_info(batch: dict[str, Any] | None) -> dict[str, Any]:
    """批次元信息 + 三种空态的判定。

    ``empty``（基金经理确认空仓）与 ``not_updated``（尚未上传）语义完全不同，
    前端文案必须区分，混为一谈会让用户误以为策略失效。
    """
    if batch is None or batch.get("trading_day") is None:
        return {
            "trading_day": None,
            "item_count": 0,
            "data_state": "not_updated",
            "updated_at": None,
            "note": None,
        }
    item_count = int(batch["item_count"] or 0)
    return {
        "trading_day": _d(batch["trading_day"]),
        "item_count": item_count,
        "data_state": "updated" if item_count > 0 else "empty",
        "updated_at": _dt(batch.get("created_at")),
        "note": batch.get("note"),
    }


def _format_item(row: dict[str, Any]) -> dict[str, Any]:
    """一条标的记录。**刻意不返回 score / suggest_weight**，见模块 docstring。"""
    return {
        "symbol": row["symbol"],
        "exchange": row["exchange"],
        "symbol_full": pick_symbols.to_symbol_full(row["symbol"], row["exchange"]),
        "symbol_name": row["symbol_name"],
        "asset_class": row["asset_class"],
        "direction": row["direction"],
        "option_type": row["option_type"],
        "rank": row["rank"],
        "entry_date": _d(row["entry_date"]),
        "entry_date_source": row["entry_date_source"],
        "holding_trading_days": _holding_days(
            row["calendar_days"], row["entry_date"], row["trading_day"]
        ),
        "reason_text": row["reason_text"],
    }


def _holding_days(calendar_days: Any, entry_date: date, trading_day: date) -> int:
    """入池时长，按**交易日**计数（前端展示务必标明单位）。

    ``meta.trading_calendar`` 还没 ingest 时区间内会数出 0 条 —— 那时退化成
    自然日计数并记 WARN。两种口径会差出周末和节假日，所以这条日志不能删：
    看到它就说明该把交易日历补上了。
    """
    count = int(calendar_days or 0)
    if count > 0:
        return count
    logger.warning(
        "meta.trading_calendar has no open day between %s and %s; "
        "falling back to calendar days for holding_trading_days",
        entry_date,
        trading_day,
    )
    return (trading_day - entry_date).days + 1


def _run_status_to_public(run_status: str | None) -> str:
    """``strategies.run_status`` → 接口契约的 active / paused / archived。"""
    if run_status in ("paused",):
        return "paused"
    if run_status in ("retired", "archived"):
        return "archived"
    return "active"


def _d(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
