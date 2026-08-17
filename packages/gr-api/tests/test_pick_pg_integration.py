"""选股模块打真实 PostgreSQL 的端到端用例。

假游标能验证控制流，但验证不了 SQL 本身 —— 列名写错、``pick.`` 前缀漏掉、
``DISTINCT ON`` 与 ``ORDER BY`` 不匹配这类问题只有真库能发现。这个文件用
``fixture_picks`` 的 30 天模拟数据把「导入 → 读接口」整条链路跑一遍。

默认跳过，需要真库时::

    GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_pick_pg_integration.py -v

用到的所有数据都挂在一个 ``STR_STK_MOCK_*`` 前缀的临时策略上，teardown 会
按前缀删干净，不碰其它数据。
"""

from __future__ import annotations

import os
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from gr_api.pagination import make_page_params
from gr_api.services import pick as pick_svc, pick_import
from gr_data.config import settings

from .fixture_picks import PICK_COLUMNS, day_slice, load_frame, trading_days


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GETRICH_TEST_PG") is None,
        reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
    ),
]

_CODE = "STR_STK_MOCK_001"
_DAYS = trading_days()
#: 刻意漏传第 10 天，用来验证「上一交易日无批次 → 入池日沿用不重置」。
_SKIPPED_DAY = _DAYS[9]
#: 第 20 天报空仓，用来验证 empty 与 not_updated 两种空态确实不同。
_EMPTY_DAY = _DAYS[19]


def _dsn() -> str:
    cfg = settings.postgres
    return f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"


@pytest.fixture
async def db() -> AsyncIterator[AsyncConnection]:
    """一条自带 search_path 的连接，跑完把模拟数据删干净。"""
    import psycopg
    from psycopg.rows import dict_row

    conn = await psycopg.AsyncConnection.connect(
        _dsn(),
        row_factory=dict_row,
        options="-c timezone=Asia/Shanghai -c search_path=app,market,meta,public",
    )
    try:
        await _seed(conn)
        yield conn
    finally:
        await _cleanup(conn)
        await conn.close()


async def _seed(conn: AsyncConnection) -> None:
    """建策略 / 作者 / 分类 / 交易日历 / 少量合约。"""
    await _cleanup(conn)
    author_id = uuid4()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app.users (id, email, password, name)
            VALUES (%s, %s, 'x', '模拟基金经理')
            ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (author_id, f"mock-pm-{author_id.hex[:8]}@example.invalid"),
        )
        author_id = (await cur.fetchone())["id"]
        await cur.execute(
            """
            INSERT INTO app.strategy_categories (id, name, sort_order)
            VALUES ('CAT_STOCK_PICK_MOCK', '模拟选股分类', 99)
            ON CONFLICT (id) DO NOTHING
            """
        )
        await cur.execute(
            """
            INSERT INTO app.strategies (
                id, strategy_code, name, summary, detail_html, category_id,
                asset_class, market, risk_level, run_status, pub_status,
                author_id, strategy_kind, subscription_monthly, subscription_yearly,
                published_at
            )
            VALUES (
                gen_random_uuid(), %s, '模拟预增精选', '模拟策略，数据全部为编造值',
                '<h2>模拟逻辑</h2>', 'CAT_STOCK_PICK_MOCK',
                'stock', 'cn', 'high', 'live', 'published',
                %s, 'pick', 99, 899, NOW()
            )
            """,
            (_CODE, author_id),
        )
        # 交易日历：与 fixture 用同一批日期，holding_trading_days 才对得上。
        await cur.executemany(
            """
            INSERT INTO meta.trading_calendar (exchange, trading_day, is_open, prev_trading_day)
            VALUES ('XSHG', %(day)s, TRUE, %(prev)s)
            ON CONFLICT (exchange, trading_day) DO UPDATE
                SET is_open = TRUE, prev_trading_day = EXCLUDED.prev_trading_day
            """,
            [{"day": day, "prev": _DAYS[i - 1] if i else None} for i, day in enumerate(_DAYS)],
        )
        # 只登记两只，剩下的走「映射失败静默置 NULL」那条路。
        await cur.executemany(
            """
            INSERT INTO meta.instruments (symbol, asset, exchange, name)
            VALUES (%(symbol)s, 'stock', %(exchange)s, %(name)s)
            ON CONFLICT (asset, exchange, symbol) DO NOTHING
            """,
            [
                {"symbol": "600000.SH", "exchange": "XSHG", "name": "库内名称A"},
                {"symbol": "000001.SZ", "exchange": "XSHE", "name": "库内名称B"},
            ],
        )
    await conn.commit()


async def _cleanup(conn: AsyncConnection) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM pick.item WHERE strategy_id IN (
                SELECT id FROM app.strategies WHERE strategy_code LIKE 'STR_STK_MOCK_%'
            )
            """
        )
        await cur.execute(
            """
            DELETE FROM pick.batch WHERE strategy_id IN (
                SELECT id FROM app.strategies WHERE strategy_code LIKE 'STR_STK_MOCK_%'
            )
            """
        )
        await cur.execute("DELETE FROM app.strategies WHERE strategy_code LIKE 'STR_STK_MOCK_%'")
        await cur.execute("DELETE FROM app.strategy_categories WHERE id = 'CAT_STOCK_PICK_MOCK'")
        await cur.execute("DELETE FROM app.users WHERE email LIKE 'mock-pm-%@example.invalid'")
        await cur.execute("DELETE FROM meta.instruments WHERE name IN ('库内名称A', '库内名称B')")
    # meta.trading_calendar 里的行**故意不删**：那些日期本来就是真实交易日，
    # 是参考数据不是测试垃圾；删掉反而会把同库里其它依赖日历的数据搞坏。
    await conn.commit()


async def _import_all(conn: AsyncConnection) -> None:
    """导入 30 天：跳过第 10 天，第 20 天报空仓。"""
    frame = load_frame()
    for day in _DAYS:
        if day == _SKIPPED_DAY:
            continue
        if day == _EMPTY_DAY:
            await pick_import.import_picks(
                conn,
                strategy=_CODE,
                trading_day=day,
                source=frame.head(0).drop("trading_day"),
                allow_empty=True,
                note="模拟：本期无符合条件标的",
            )
            continue
        result = await pick_import.import_picks(
            conn, strategy=_CODE, trading_day=day, source=day_slice(frame, day)
        )
        assert result.status == "committed", result.errors


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------


async def test_fixture_matches_import_contract() -> None:
    frame = load_frame()

    assert frame.columns == ["trading_day", *PICK_COLUMNS]
    assert frame["trading_day"].n_unique() == len(_DAYS)
    # 全列字符串：代码的前导零必须原样保留。
    assert all(dtype == frame.dtypes[0] for dtype in frame.dtypes)
    assert any(sym.startswith("0000") for sym in frame["symbol"].to_list())


async def test_import_thirty_days_and_read_back(db: AsyncConnection) -> None:
    await _import_all(db)

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT COUNT(*)::int AS batches,
                   SUM(item_count)::int AS items,
                   MIN(trading_day) AS first_day,
                   MAX(trading_day) AS last_day
            FROM pick.batch b
            JOIN app.strategies s ON s.id = b.strategy_id
            WHERE s.strategy_code = %s AND b.status = 'active'
            """,
            (_CODE,),
        )
        row = await cur.fetchone()

    assert row["batches"] == len(_DAYS) - 1  # 漏传的那天没有批次
    assert row["items"] == 29 * 20 - 20  # 28 天各 20 只，空仓那天 0 只
    assert row["first_day"] == _DAYS[0]
    assert row["last_day"] == _DAYS[-1]


async def test_reimport_supersedes_previous_batch(db: AsyncConnection) -> None:
    frame = load_frame()
    day = _DAYS[0]

    await pick_import.import_picks(
        db, strategy=_CODE, trading_day=day, source=day_slice(frame, day)
    )
    again = await pick_import.import_picks(
        db,
        strategy=_CODE,
        trading_day=day,
        source=day_slice(frame, day).head(5),
        overwrite=True,
    )

    assert again.status == "committed"
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT b.status, b.item_count, COUNT(i.symbol)::int AS rows
            FROM pick.batch b
            JOIN app.strategies s ON s.id = b.strategy_id
            LEFT JOIN pick.item i ON i.batch_id = b.batch_id
            WHERE s.strategy_code = %s
            GROUP BY b.batch_id, b.status, b.item_count
            ORDER BY b.batch_id
            """,
            (_CODE,),
        )
        rows = await cur.fetchall()

    assert [r["status"] for r in rows] == ["superseded", "active"]
    # 先删后插：旧批次的条目已经删掉，不会留下脏行。
    assert rows[0]["rows"] == 0
    assert rows[1]["rows"] == 5


async def test_entry_date_carries_over_across_missing_day(db: AsyncConnection) -> None:
    """漏传日的次日：老标的沿用入池日，只有当天新入池的才取当天。"""
    await _import_all(db)

    async def _items(day: date) -> dict[str, Any]:
        async with db.cursor() as cur:
            await cur.execute(
                """
                SELECT i.symbol, i.entry_date, i.product_entry_date
                FROM pick.item i
                JOIN app.strategies s ON s.id = i.strategy_id
                WHERE s.strategy_code = %s AND i.trading_day = %s
                """,
                (_CODE, day),
            )
            return {row["symbol"]: row for row in await cur.fetchall()}

    before_gap = await _items(_DAYS[8])
    after_gap = await _items(_DAYS[10])
    carried = set(before_gap) & set(after_gap)

    assert carried, "两侧应当有重合标的，否则这个用例没意义"
    for symbol in carried:
        # 沿用而不是重置成当天 —— 重置会静默破坏历史且不可恢复。
        assert after_gap[symbol]["entry_date"] == before_gap[symbol]["entry_date"]
        assert after_gap[symbol]["entry_date"] < _DAYS[10]
    assert all(row["product_entry_date"] <= row["entry_date"] for row in after_gap.values())


async def test_provided_entry_date_survives_thirty_days(db: AsyncConnection) -> None:
    await _import_all(db)

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT i.entry_date
            FROM pick.item i
            JOIN app.strategies s ON s.id = i.strategy_id
            WHERE s.strategy_code = %s AND i.trading_day = %s
            """,
            (_CODE, _DAYS[0]),
        )
        rows = await cur.fetchall()

    assert len(rows) == 1
    # 首日 CSV 给的是 7 个自然日前，provided 的历史口径要能带进来。
    assert rows[0]["entry_date"] < _DAYS[0]


async def test_instrument_mapping_and_name_backfill(db: AsyncConnection) -> None:
    frame = load_frame()
    day = _DAYS[0]
    await pick_import.import_picks(
        db, strategy=_CODE, trading_day=day, source=day_slice(frame, day)
    )

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT i.symbol, i.instrument_id, i.symbol_name
            FROM pick.item i
            JOIN app.strategies s ON s.id = i.strategy_id
            WHERE s.strategy_code = %s AND i.trading_day = %s AND i.symbol IN ('600000', '600001')
            ORDER BY i.symbol
            """,
            (_CODE, day),
        )
        rows = await cur.fetchall()

    mapped = {r["symbol"]: r for r in rows}
    assert mapped["600000"]["instrument_id"] is not None
    # CSV 自带名称时以快照名为准，不被库里的名字覆盖。
    assert mapped["600000"]["symbol_name"].startswith("模拟股")
    if "600001" in mapped:
        assert mapped["600001"]["instrument_id"] is None


# ---------------------------------------------------------------------------
# 读接口
# ---------------------------------------------------------------------------


async def test_read_endpoints_against_real_sql(db: AsyncConnection) -> None:
    await _import_all(db)
    page = make_page_params(page=1, page_size=50)

    items, total = await pick_svc.list_pick_strategies(
        db,
        user_id=None,
        category_id=None,
        keyword=None,
        data_state="all",
        status="active",
        sort="latest_trading_day",
        sort_order="desc",
        page=page,
    )
    assert total >= 1
    mine = next(row for row in items if row["id"] == _CODE)
    assert mine["latest_batch"]["trading_day"] == _DAYS[-1].isoformat()
    assert mine["latest_batch"]["data_state"] == "updated"
    assert mine["creator"]["name"] == "模拟基金经理"

    detail = await pick_svc.get_pick_strategy(db, strategy_ref=_CODE, user_id=None)
    assert detail["data_range"]["first_trading_day"] == _DAYS[0].isoformat()
    assert detail["data_range"]["total_days"] == len(_DAYS) - 1
    assert "模拟逻辑" in detail["detail_html"]

    picks = await pick_svc.list_strategy_picks(
        db, strategy_ref=_CODE, trading_day=None, sort="rank", page=page
    )
    assert picks["batch"]["data_state"] == "updated"
    assert picks["total"] == 20
    first = picks["list"][0]
    assert first["symbol_full"].endswith((".SH", ".SZ", ".BJ"))
    assert first["holding_trading_days"] >= 1
    assert "score" not in first and "suggest_weight" not in first
    ranks = [row["rank"] for row in picks["list"]]
    assert [r for r in ranks if r is None] == ranks[len([r for r in ranks if r is not None]) :]

    days = await pick_svc.list_pick_trading_days(
        db, strategy_ref=_CODE, start_date=None, end_date=None, limit=90
    )
    assert days["total"] == len(_DAYS) - 1
    assert _SKIPPED_DAY.isoformat() not in [row["trading_day"] for row in days["list"]]
    assert {"updated", "empty"} == {row["data_state"] for row in days["list"]}

    latest, latest_total = await pick_svc.list_latest_picks(
        db, user_id=None, category_id=None, subscribed_only=False, preview_size=5, page=page
    )
    assert latest_total >= 1
    entry = next(row for row in latest if row["strategy"]["id"] == _CODE)
    assert len(entry["items"]) == 5

    by_symbol = await pick_svc.list_picks_by_symbol(
        db,
        symbol_full=picks["list"][0]["symbol_full"],
        start_date=None,
        end_date=None,
        in_pool_only=False,
        page=page,
    )
    # 个股反查是跨策略的，同库里别的策略也可能选过这只票 —— 只挑自己的那条断言。
    mine = [r for r in by_symbol["list"] if r["strategy"]["id"] == _CODE]
    assert mine
    assert mine[0]["still_in_pool"] is True
    assert mine[0]["holding_trading_days"] >= 1

    batches, batch_total = await pick_svc.list_pick_batches(
        db, strategy_ref=_CODE, start_date=None, end_date=None, status="active", page=page
    )
    assert batch_total == len(_DAYS) - 1
    assert batches[0]["strategy"]["id"] == _CODE
    assert batches[0]["file_name"] is None


async def test_three_empty_states_on_real_data(db: AsyncConnection) -> None:
    await _import_all(db)
    page = make_page_params()

    updated = await pick_svc.list_strategy_picks(
        db, strategy_ref=_CODE, trading_day=_DAYS[0], sort="rank", page=page
    )
    empty = await pick_svc.list_strategy_picks(
        db, strategy_ref=_CODE, trading_day=_EMPTY_DAY, sort="rank", page=page
    )
    not_updated = await pick_svc.list_strategy_picks(
        db, strategy_ref=_CODE, trading_day=_SKIPPED_DAY, sort="rank", page=page
    )

    assert updated["batch"]["data_state"] == "updated"
    assert empty["batch"]["data_state"] == "empty"
    assert empty["batch"]["note"].startswith("模拟：本期无符合条件标的")
    assert empty["list"] == []
    assert not_updated["batch"]["data_state"] == "not_updated"
    assert not_updated["batch"]["trading_day"] is None
