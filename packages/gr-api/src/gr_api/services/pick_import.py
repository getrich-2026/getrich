"""选股标的池导入：CSV / Parquet / DataFrame → ``pick.batch`` + ``pick.item``。

P0 阶段基金经理在本地产出信号后导入，系统只做接收与展示，**不校验选股逻辑**。
本模块提供函数接口（:func:`import_picks` / :func:`import_picks_sync`），
命令行入口见 :mod:`gr_api.picks_cli`。

设计依据：``getrich-design/strategy-signal/个股推荐_数据库设计_P0.md`` §4。

校验原则（§4.5）：**只保留「不做就会 DB 抛异常」或「不做会静默产生错误数据」的检查**。
前者本质上是把 DB 约束翻译成带行号的友好提示，后者只有一条 —— 乱序上传。
其余（是否为合法交易日、标的是否停牌退市、``rank`` 是否连续、``symbol_name``
是否与代码匹配）**有意省略**：出错后前端一眼可见，基金经理自己会发现并重传。

写入语义（§4.6）：单事务，先把旧批次置 ``superseded``、删掉该交易日的旧条目，
再整批插入。**不用 UPSERT** —— 重传的池子可能比原来少几个标的，UPSERT 会把
它们留成脏行。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import polars as pl
from gr_api.errors import BadRequest, Conflict
from gr_api.services import pick_symbols
from gr_api.services.resolver import resolve_strategy_ref
from gr_tools import cast_all_utf8, read_frame


if TYPE_CHECKING:
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)

#: CSV / Parquet 里认识的列，多余列忽略并告警。
KNOWN_COLUMNS = (
    "symbol",
    "symbol_name",
    "entry_date",
    "rank",
    "score",
    "suggest_weight",
    "reason_text",
)

#: ``pick.item.symbol_name`` 是 VARCHAR(64)。展示字段超长直接截断，
#: 不因为一个名字太长就让整批入库失败。
_SYMBOL_NAME_MAX = 64

#: 上一交易日无 active 批次时追加到 ``pick.batch.note`` 的系统提示。
CARRY_OVER_NOTE = "上一交易日无数据，入池时间按沿用处理"


@dataclass(frozen=True)
class PickImportResult:
    """一次导入的结果。

    Attributes:
        status: ``blocked`` 有阻断错误未写库 / ``validated`` 预检通过但
            ``dry_run`` 未写库 / ``committed`` 已落库。
        batch_id: 落库后的批次号；未落库为 None。
        summary: 行数统计。
        errors: 带行号的错误明细，形状与 ``import_job_errors`` 对齐。
        warnings: 不阻断的提示（入池日沿用、日历缺失、未知列等）。
    """

    status: str
    strategy_id: str
    strategy_code: str
    trading_day: date
    batch_id: int | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否没有阻断错误。"""
        return self.status != "blocked"


async def import_picks(
    db: AsyncConnection,
    *,
    strategy: str,
    trading_day: date | str,
    source: str | Path | pl.DataFrame | Any,
    uploaded_by: str | None = None,
    note: str | None = None,
    overwrite: bool = False,
    allow_empty: bool = False,
    dry_run: bool = False,
) -> PickImportResult:
    """把一个交易日的完整标的池导入数据库。

    Args:
        db: PostgreSQL 异步连接。
        strategy: 策略 UUID 或 ``strategy_code``。
        trading_day: 池子归属的交易日（``date`` 或 ``YYYY-MM-DD``）。
        source: ``.csv`` / ``.parquet`` 文件路径，或直接给 polars / pandas
            DataFrame。**文件一律按全列字符串读**，否则 ``000001`` 会被
            类型推断成整数、丢掉前导零。
        uploaded_by: 操作者 user UUID，可空。
        note: 基金经理对本期的备注。
        overwrite: 该交易日已有 active 批次时是否覆盖。默认 False，
            即报 409 —— 误选日期会不可逆地覆盖正确数据。
        allow_empty: 是否接受 0 行的池子。``item_count=0`` 是合法状态
            （确认空仓），但空文件更常见的原因是导错了，所以要显式声明。
        dry_run: 只预检不写库。

    Returns:
        :class:`PickImportResult`。行级错误放在 ``errors`` 里返回而不是抛异常，
        这样一次能把整份文件的问题都告诉用户。

    Raises:
        BadRequest: 结构性问题（缺 ``symbol`` 列、空文件、乱序上传）。
        Conflict: 该交易日已有 active 批次且 ``overwrite=False``。
        NotFound: 策略不存在。

    Time Complexity:
        O(n + m)，n 为文件行数，m 为该策略的历史条目数（推算入池日要扫一遍）。
    Space Complexity:
        O(n + m)。
    """
    day = _coerce_date(trading_day, "trading_day")
    strategy_row = await resolve_strategy_ref(db, strategy)
    strategy_id = str(strategy_row["id"])

    rows, warnings = _load_rows(source)
    if not rows and not allow_empty:
        raise BadRequest(
            "source has no data row; pass allow_empty=True to record an empty pool "
            "(item_count=0 means the manager confirmed no holdings)"
        )

    parsed, errors = _validate_rows(rows, day)

    # 批次级校验 5：乱序上传。这是清单里唯一会**静默**产生错误数据的场景 ——
    # 补传历史会让后续所有日期的 entry_date 推算错乱，且从数据本身看不出来。
    latest_day = await _max_trading_day(db, strategy_id)
    if latest_day is not None and day < latest_day:
        raise BadRequest(
            f"out-of-order upload: strategy already has data up to {latest_day}, "
            f"refusing to import {day}"
        )

    # 批次级校验 6：覆盖既有批次。
    existing = await _active_batch(db, strategy_id, day)
    if existing is not None and not overwrite:
        raise Conflict(
            f"an active batch already exists for {day} with {existing['item_count']} item(s); "
            "pass overwrite=True to supersede it"
        )

    summary: dict[str, Any] = {
        "total_rows": len(rows),
        "valid_rows": len(parsed),
        "error_rows": len(errors),
        "will_insert": len(parsed),
        "will_delete": int(existing["item_count"]) if existing else 0,
        "overwrite": bool(existing),
    }

    if errors:
        return PickImportResult(
            status="blocked",
            strategy_id=strategy_id,
            strategy_code=strategy_row["strategy_code"],
            trading_day=day,
            summary=summary,
            errors=errors,
            warnings=warnings,
        )

    items, derive_warnings = await _derive_items(db, strategy_id, day, parsed)
    warnings.extend(derive_warnings)

    if dry_run:
        return PickImportResult(
            status="validated",
            strategy_id=strategy_id,
            strategy_code=strategy_row["strategy_code"],
            trading_day=day,
            summary=summary,
            warnings=warnings,
        )

    batch_note = _compose_note(note, derive_warnings)
    batch_id = await _write_batch(
        db,
        strategy_id=strategy_id,
        trading_day=day,
        items=items,
        uploaded_by=uploaded_by,
        note=batch_note,
    )
    logger.info(
        "pick import committed: strategy=%s trading_day=%s batch_id=%s items=%d",
        strategy_row["strategy_code"],
        day,
        batch_id,
        len(items),
    )
    return PickImportResult(
        status="committed",
        strategy_id=strategy_id,
        strategy_code=strategy_row["strategy_code"],
        trading_day=day,
        batch_id=batch_id,
        summary=summary,
        warnings=warnings,
    )


def import_picks_sync(**kwargs: Any) -> PickImportResult:
    """:func:`import_picks` 的同步封装，给脚本 / CLI / notebook 用。

    自己负责连接池的开关，所以**不要**在已经跑着事件循环的进程里调用它
    （FastAPI 路由里请直接 await :func:`import_picks`）。
    """
    from gr_data.db import pg_pool

    async def _run() -> PickImportResult:
        await pg_pool.init()
        try:
            async with pg_pool.connection() as conn:
                return await import_picks(conn, **kwargs)
        finally:
            await pg_pool.close()

    return asyncio.run(_run())


# ---------------------------------------------------------------- 读取与校验


def _load_rows(source: Any) -> tuple[list[dict[str, str | None]], list[str]]:
    """把三种入参形态统一成「全字符串」的行字典列表。"""
    warnings: list[str] = []

    if isinstance(source, pl.DataFrame):
        frame = cast_all_utf8(source)
    elif isinstance(source, str | Path):
        frame = read_frame(Path(source), all_string=True)
    elif hasattr(source, "to_dict") and hasattr(source, "columns"):
        # pandas.DataFrame：不硬依赖 pandas 的类型，鸭子类型判断即可。
        frame = cast_all_utf8(pl.from_pandas(source))
    else:
        raise BadRequest(
            f"unsupported source type: {type(source).__name__}; "
            "expected a .csv/.parquet path, a polars DataFrame or a pandas DataFrame"
        )

    frame = frame.rename({name: name.strip().lower() for name in frame.columns})
    if "symbol" not in frame.columns:
        raise BadRequest(f"missing required column 'symbol'; got {list(frame.columns)}")

    unknown = [name for name in frame.columns if name not in KNOWN_COLUMNS]
    if unknown:
        warnings.append(f"ignored unknown column(s): {', '.join(unknown)}")

    keep = [name for name in KNOWN_COLUMNS if name in frame.columns]
    return [
        {key: _clean(value) for key, value in row.items()} for row in frame.select(keep).to_dicts()
    ], warnings


def _validate_rows(
    rows: list[dict[str, str | None]],
    trading_day: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """逐行校验并解析。返回 ``(有效行, 错误明细)``。

    行号从 2 起算，对齐 CSV 里的物理行号（第 1 行是表头）。
    """
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=2):
        row_errors: list[dict[str, Any]] = []

        # 1. symbol 必须匹配 ^\d{6}\.(SH|SZ|BJ)$ ——
        #    解析不出 exchange / product_code 就写不进 NOT NULL 列。
        raw_symbol = row.get("symbol")
        parsed_symbol = None
        if not raw_symbol:
            row_errors.append(_err(index, "symbol", "required", "symbol is required", row))
        else:
            try:
                parsed_symbol = pick_symbols.parse_symbol(raw_symbol)
            except ValueError as exc:
                row_errors.append(_err(index, "symbol", "invalid_symbol", str(exc), row))

        # 2. 同一文件内 symbol 重复 —— 违反主键，人工编辑 CSV 时很常见。
        if parsed_symbol is not None:
            if parsed_symbol.symbol_full in seen:
                row_errors.append(
                    _err(index, "symbol", "duplicate", "duplicate symbol in this file", row)
                )
            seen.add(parsed_symbol.symbol_full)

        # 3. entry_date <= trading_day —— 违反 chk_item_entry_date。
        entry_date = _parse_date_cell(row.get("entry_date"), index, "entry_date", row, row_errors)
        if entry_date is not None and entry_date > trading_day:
            row_errors.append(
                _err(
                    index,
                    "entry_date",
                    "out_of_range",
                    f"entry_date {entry_date} must not be later than trading_day {trading_day}",
                    row,
                )
            )

        # 4. suggest_weight ∈ [0, 1] —— 违反 chk_item_weight。
        #    填百分数（25 而不是 0.25）是高频错误，这条专治它。
        weight = _parse_decimal_cell(
            row.get("suggest_weight"), index, "suggest_weight", row, row_errors
        )
        if weight is not None and not (0 <= weight <= 1):
            row_errors.append(
                _err(
                    index,
                    "suggest_weight",
                    "out_of_range",
                    "suggest_weight must be a decimal in [0, 1]; 0.25 means 25%, not 25",
                    row,
                )
            )

        # rank / score 也是把 DB 约束翻译成友好提示（chk_item_rank / NUMERIC 类型）。
        rank = _parse_int_cell(row.get("rank"), index, "rank", row, row_errors)
        if rank is not None and rank < 1:
            row_errors.append(_err(index, "rank", "out_of_range", "rank must be >= 1", row))
        score = _parse_decimal_cell(row.get("score"), index, "score", row, row_errors)

        if row_errors or parsed_symbol is None:
            errors.extend(row_errors)
            continue

        symbol_name = row.get("symbol_name")
        valid.append(
            {
                "symbol": parsed_symbol.symbol,
                "exchange": parsed_symbol.exchange,
                "symbol_full": parsed_symbol.symbol_full,
                "asset_class": parsed_symbol.asset_class,
                "product_code": parsed_symbol.product_code,
                "direction": "long",
                "option_type": None,
                "symbol_name": symbol_name[:_SYMBOL_NAME_MAX] if symbol_name else None,
                "entry_date": entry_date,
                "rank": rank,
                "score": score,
                "suggest_weight": weight,
                "reason_text": row.get("reason_text"),
            }
        )
    return valid, errors


# ---------------------------------------------------------------- 入池日推算


async def _derive_items(
    db: AsyncConnection,
    strategy_id: str,
    trading_day: date,
    parsed: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """补齐 ``entry_date`` / ``product_entry_date`` / ``instrument_id`` / ``symbol_name``。

    两个日期必须**按先后顺序**推算：先定 ``entry_date``，再以它为兜底定
    ``product_entry_date`` —— 兜底值取 ``trading_day`` 会在「首次入池 +
    上传方给了更早的 entry_date」这个必经场景下违反 ``chk_item_prod_entry``，
    整批插入失败（设计文档附录 A.6 第 1 条）。
    """
    warnings: list[str] = []
    if not parsed:
        return [], warnings

    prev_day = await _prev_trading_day(db, trading_day)
    if prev_day is None:
        warnings.append(
            "meta.trading_calendar has no previous trading day for "
            f"{trading_day}; entry dates are carried over instead of reset"
        )
        logger.warning("pick import: trading calendar unavailable for %s", trading_day)
        prev_batch_exists = False
    else:
        prev_batch_exists = await _active_batch(db, strategy_id, prev_day) is not None

    # 正常情况（上一交易日有 active 批次）只需要看上一交易日那一批：
    # 在里面的继承、不在的就是重新入池，与扫全量历史的结论完全一致，
    # 但代价从 O(该策略全部历史) 降到 O(上一期池子大小)。
    # 只有漏传 / 日历缺失才需要回退到扫历史找「最近一条」。
    carry_over_mode = prev_day is None or not prev_batch_exists
    if carry_over_mode:
        last_by_symbol = await _last_items(db, strategy_id, trading_day, by="symbol")
        last_by_product = await _last_items(db, strategy_id, trading_day, by="product")
    else:
        last_by_symbol, last_by_product = await _items_on_day(db, strategy_id, prev_day)
    instruments = await _load_instruments(db, parsed)

    carried_over = 0
    items: list[dict[str, Any]] = []
    for row in parsed:
        previous = last_by_symbol.get((row["symbol"], row["exchange"], row["direction"]))
        previous_product = last_by_product.get((row["product_code"], row["direction"]))

        if row["entry_date"] is not None:
            entry_date = row["entry_date"]
            entry_source = "provided"
        elif previous is None:
            entry_date = trading_day  # 首次入池，或上一期不在池里（重新入池）
            entry_source = "derived"
        else:
            entry_date = previous["entry_date"]
            entry_source = "derived"
            carried_over += int(carry_over_mode)

        # 品种级入池逻辑上不可能晚于合约级入池（chk_item_prod_entry）。
        # 上传方给了很早的 entry_date 时，继承来的品种日可能反而更晚，得 clamp。
        product_entry_date = entry_date
        if previous_product is not None:
            product_entry_date = min(previous_product["product_entry_date"], entry_date)

        instrument = instruments.get((row["symbol_full"], row["exchange"]))
        fallback_name = instrument["name"] if instrument and instrument["name"] else None
        items.append(
            {
                **row,
                "entry_date": entry_date,
                "entry_date_source": entry_source,
                "product_entry_date": product_entry_date,
                # 映射失败静默置 NULL 不阻断：新股/北交所标的可能还没同步到
                # meta.instruments，但基金经理提交的池子是有效业务数据。
                "instrument_id": instrument["instrument_id"] if instrument else None,
                "symbol_name": row["symbol_name"] or (fallback_name or None),
            }
        )

    unmapped = sum(1 for item in items if item["instrument_id"] is None)
    if unmapped:
        warnings.append(f"{unmapped} symbol(s) could not be mapped to meta.instruments")
    if carried_over:
        warnings.append(f"{CARRY_OVER_NOTE}（{carried_over} 条）")
    return items, warnings


def _compose_note(note: str | None, derive_warnings: list[str]) -> str | None:
    """把系统提示追加到基金经理的备注后面。"""
    system_notes = [w for w in derive_warnings if w.startswith(CARRY_OVER_NOTE)]
    parts = [part for part in (note, *system_notes) if part]
    return "\n".join(parts) if parts else None


# ---------------------------------------------------------------- 数据库读写


async def _max_trading_day(db: AsyncConnection, strategy_id: str) -> date | None:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT MAX(trading_day) AS latest
            FROM pick.batch
            WHERE strategy_id = %(sid)s AND status = 'active'
            """,
            {"sid": strategy_id},
        )
        row = await cur.fetchone()
    return row["latest"] if row else None


async def _active_batch(
    db: AsyncConnection,
    strategy_id: str,
    trading_day: date,
) -> dict[str, Any] | None:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT batch_id, item_count
            FROM pick.batch
            WHERE strategy_id = %(sid)s AND trading_day = %(td)s AND status = 'active'
            """,
            {"sid": strategy_id, "td": trading_day},
        )
        return await cur.fetchone()


async def _prev_trading_day(db: AsyncConnection, trading_day: date) -> date | None:
    """取上一交易日。日历里没有这一天时退回「日历中小于它的最大开市日」。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT prev_trading_day
            FROM meta.trading_calendar
            WHERE exchange = %(ex)s AND trading_day = %(td)s
            """,
            {"ex": pick_symbols.CALENDAR_EXCHANGE, "td": trading_day},
        )
        row = await cur.fetchone()
        if row and row["prev_trading_day"]:
            return row["prev_trading_day"]

        await cur.execute(
            """
            SELECT MAX(trading_day) AS prev
            FROM meta.trading_calendar
            WHERE exchange = %(ex)s AND is_open AND trading_day < %(td)s
            """,
            {"ex": pick_symbols.CALENDAR_EXCHANGE, "td": trading_day},
        )
        row = await cur.fetchone()
    return row["prev"] if row else None


async def _items_on_day(
    db: AsyncConnection,
    strategy_id: str,
    trading_day: date,
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]]]:
    """取某一交易日整期池子，一次查询同时给出两套分组索引。

    正常连续上传时，入池日只可能继承自**上一交易日那一期**，所以走这条
    单次索引扫描就够了（``idx_item_strategy_day``），不必对整段历史做
    ``DISTINCT ON``。
    """
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT symbol, exchange, direction, product_code, entry_date, product_entry_date
            FROM pick.item
            WHERE strategy_id = %(sid)s AND trading_day = %(td)s
            """,
            {"sid": strategy_id, "td": trading_day},
        )
        rows = await cur.fetchall()

    by_symbol = {(r["symbol"], r["exchange"], r["direction"]): r for r in rows}
    by_product = {(r["product_code"], r["direction"]): r for r in rows}
    return by_symbol, by_product


async def _last_items(
    db: AsyncConnection,
    strategy_id: str,
    trading_day: date,
    *,
    by: str,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    """取每个分组键在本期之前的最近一条记录（漏传 / 日历缺失时的兜底路径）。

    ``by='symbol'`` 分组键 ``(symbol, exchange, direction)`` —— 当前这只证券
    持有了多久；``by='product'`` 分组键 ``(product_code, direction)`` ——
    这个品种看多/看空了多久，跨换月连续。``direction`` 进分组键是因为
    多头转空头是一次新的入池，不该继承旧的入池时间。

    这条要扫该策略的全部历史，只在「无法判断标的是出池了还是那天没上传」
    时才走 —— 那时必须找到最近一条记录来沿用它的入池日。
    """
    if by == "symbol":
        keys = "symbol, exchange, direction"
    elif by == "product":
        keys = "product_code, direction"
    else:  # pragma: no cover — 内部调用，穷举了
        raise ValueError(f"unknown grouping: {by}")

    sql = f"""
        SELECT DISTINCT ON ({keys})
               {keys}, trading_day, entry_date, product_entry_date
        FROM pick.item
        WHERE strategy_id = %(sid)s AND trading_day < %(td)s
        ORDER BY {keys}, trading_day DESC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"sid": strategy_id, "td": trading_day})
        rows = await cur.fetchall()

    if by == "symbol":
        return {(r["symbol"], r["exchange"], r["direction"]): r for r in rows}
    return {(r["product_code"], r["direction"]): r for r in rows}


async def _load_instruments(
    db: AsyncConnection,
    parsed: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """按带后缀全码 + canonical 交易所码查 ``meta.instruments``。

    ``meta.instruments.symbol`` 存的是完整带后缀代码（``600000.SH``），
    ``exchange`` 是 canonical 码（``XSHG``）—— 用 ``pick.item`` 那套
    ``SSE`` 码去查会一条都查不到。
    """
    if not parsed:
        return {}

    codes = sorted({row["symbol_full"] for row in parsed})
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT symbol, exchange, instrument_id, name
            FROM meta.instruments
            WHERE symbol = ANY(%(codes)s)
              AND asset = ANY(%(assets)s)
            """,
            {"codes": codes, "assets": ["stock", "etf", "fund"]},
        )
        rows = await cur.fetchall()

    to_contract = pick_symbols.CANONICAL_TO_EXCHANGE
    return {
        (row["symbol"], to_contract[row["exchange"]]): row
        for row in rows
        if row["exchange"] in to_contract
    }


async def _write_batch(
    db: AsyncConnection,
    *,
    strategy_id: str,
    trading_day: date,
    items: list[dict[str, Any]],
    uploaded_by: str | None,
    note: str | None,
) -> int:
    """单事务写入：置旧批次 superseded → 建新批次 → 删旧条目 → 批量插入。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            UPDATE pick.batch
            SET status = 'superseded'
            WHERE strategy_id = %(sid)s AND trading_day = %(td)s AND status = 'active'
            """,
            {"sid": strategy_id, "td": trading_day},
        )
        await cur.execute(
            """
            INSERT INTO pick.batch (
                strategy_id, trading_day, source, uploaded_by,
                item_count, status, note
            )
            VALUES (
                %(sid)s, %(td)s, 'upload', %(uploaded_by)s,
                %(item_count)s, 'active', %(note)s
            )
            RETURNING batch_id
            """,
            {
                "sid": strategy_id,
                "td": trading_day,
                "uploaded_by": _as_uuid(uploaded_by),
                "item_count": len(items),
                "note": note,
            },
        )
        row = await cur.fetchone()
        batch_id = int(row["batch_id"])

        # 先删后插：重传的池子可能比原来少几个标的，UPSERT 会把它们留成脏行。
        await cur.execute(
            "DELETE FROM pick.item WHERE strategy_id = %(sid)s AND trading_day = %(td)s",
            {"sid": strategy_id, "td": trading_day},
        )
        if items:
            await cur.executemany(
                """
                INSERT INTO pick.item (
                    strategy_id, trading_day, symbol, exchange, batch_id,
                    asset_class, product_code, direction, option_type,
                    symbol_name, instrument_id,
                    entry_date, entry_date_source, product_entry_date,
                    rank, score, suggest_weight, reason_text
                )
                VALUES (
                    %(strategy_id)s, %(trading_day)s, %(symbol)s, %(exchange)s, %(batch_id)s,
                    %(asset_class)s, %(product_code)s, %(direction)s, %(option_type)s,
                    %(symbol_name)s, %(instrument_id)s,
                    %(entry_date)s, %(entry_date_source)s, %(product_entry_date)s,
                    %(rank)s, %(score)s, %(suggest_weight)s, %(reason_text)s
                )
                """,
                [
                    {
                        "strategy_id": strategy_id,
                        "trading_day": trading_day,
                        "batch_id": batch_id,
                        **{key: item[key] for key in _ITEM_COLUMNS},
                    }
                    for item in items
                ],
            )
    await db.commit()
    return batch_id


_ITEM_COLUMNS = (
    "symbol",
    "exchange",
    "asset_class",
    "product_code",
    "direction",
    "option_type",
    "symbol_name",
    "instrument_id",
    "entry_date",
    "entry_date_source",
    "product_entry_date",
    "rank",
    "score",
    "suggest_weight",
    "reason_text",
)


# ---------------------------------------------------------------- 小工具


def _clean(value: Any) -> str | None:
    """空串与纯空白一律归一成 None —— CSV 里「留空」就是「没填」。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_date(value: date | str, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise BadRequest(f"invalid {field_name}: {value!r}, expected YYYY-MM-DD") from exc


def _as_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise BadRequest(f"invalid uploaded_by: {value!r}, expected a user UUID") from exc


def _parse_date_cell(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, Any],
    errors: list[dict[str, Any]],
) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(
            _err(row_number, column, "invalid_date", "invalid date, expected YYYY-MM-DD", raw_row)
        )
        return None


def _parse_int_cell(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, Any],
    errors: list[dict[str, Any]],
) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(_err(row_number, column, "invalid_integer", "invalid integer", raw_row))
        return None


def _parse_decimal_cell(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, Any],
    errors: list[dict[str, Any]],
) -> Decimal | None:
    """数值一律用 Decimal —— score / suggest_weight 都是 NUMERIC 列，
    走 float 会引入十进制表示误差。"""
    if not value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        errors.append(_err(row_number, column, "invalid_number", "invalid number", raw_row))
        return None
    if not parsed.is_finite():
        errors.append(
            _err(row_number, column, "invalid_number", "NaN and Inf are not allowed", raw_row)
        )
        return None
    return parsed


def _err(
    row_number: int,
    column: str,
    code: str,
    message: str,
    raw_row: dict[str, Any],
) -> dict[str, Any]:
    """错误明细的形状与 ``import_job_errors`` 对齐，便于以后接进导入通道。"""
    return {
        "row_number": row_number,
        "column": column,
        "error_code": code,
        "message": message,
        "raw_row": dict(raw_row),
    }


__all__ = [
    "CARRY_OVER_NOTE",
    "KNOWN_COLUMNS",
    "PickImportResult",
    "import_picks",
    "import_picks_sync",
]
