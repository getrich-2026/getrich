"""``services/pick_import`` 的校验、入池日推算与写入语义。

用假游标按 SQL 片段路由响应，不需要真库。覆盖的关键场景来自设计文档
``个股推荐_数据库设计_P0.md`` §4 与附录 A 的走查。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import polars as pl
import pytest
from gr_api.errors import BadRequest, Conflict
from gr_api.services.pick_import import CARRY_OVER_NOTE, import_picks


pytestmark = pytest.mark.anyio

_STRATEGY_UUID = str(uuid4())
_TRADING_DAY = date(2026, 8, 12)
_PREV_DAY = date(2026, 8, 11)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeDb:
    """按 SQL 片段路由的假连接。"""

    def __init__(self) -> None:
        self.strategy: dict[str, Any] = {
            "id": _STRATEGY_UUID,
            "strategy_code": "STR_STK_001",
            "name": "预增精选",
            "strategy_kind": "pick",
        }
        self.max_day: date | None = None
        self.prev_day: date | None = _PREV_DAY
        self.active_batches: dict[date, dict[str, Any]] = {}
        #: 快路径：某一交易日整期池子（连续上传时只查这一次）。
        self.day_items: dict[date, list[dict[str, Any]]] = {}
        #: 慢路径：漏传 / 日历缺失时扫历史拿到的「最近一条」。
        self.last_symbol_rows: list[dict[str, Any]] = []
        self.last_product_rows: list[dict[str, Any]] = []
        self.instruments: list[dict[str, Any]] = []

        self.batch_id = 7
        self.superseded = 0
        self.deleted = 0
        self.batch_params: dict[str, Any] | None = None
        self.inserted: list[dict[str, Any]] = []
        self.commits = 0
        self.statements: list[str] = []

    # -- psycopg-ish API ----------------------------------------------------
    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    async def commit(self) -> None:
        self.commits += 1

    # -- routing ------------------------------------------------------------
    def route(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.statements.append(sql)
        if "FROM strategies WHERE" in sql:
            return [self.strategy]
        if "MAX(trading_day) AS latest" in sql:
            return [{"latest": self.max_day}]
        if "SELECT batch_id, item_count" in sql:
            batch = self.active_batches.get(params.get("td"))
            return [batch] if batch else []
        if "prev_trading_day" in sql and "meta.trading_calendar" in sql:
            return [{"prev_trading_day": self.prev_day}]
        if "MAX(trading_day) AS prev" in sql:
            return [{"prev": self.prev_day}]
        if "DISTINCT ON (symbol" in sql:
            return self.last_symbol_rows
        if "DISTINCT ON (product_code" in sql:
            return self.last_product_rows
        if "SELECT symbol, exchange, direction, product_code" in sql:
            return self.day_items.get(params.get("td"), [])
        if "FROM meta.instruments" in sql:
            return self.instruments
        if sql.lstrip().startswith("UPDATE pick.batch"):
            self.superseded += 1
            return []
        if "INSERT INTO pick.batch" in sql:
            self.batch_params = params
            return [{"batch_id": self.batch_id}]
        if sql.lstrip().startswith("DELETE FROM pick.item"):
            self.deleted += 1
            return []
        return []


class _FakeCursor:
    def __init__(self, db: _FakeDb) -> None:
        self._db = db
        self._rows: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self._rows = self._db.route(sql, dict(params) if isinstance(params, dict) else {})

    async def executemany(self, sql: str, seq: list[dict[str, Any]]) -> None:
        self._db.statements.append(sql)
        self._db.inserted.extend(seq)

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _frame(rows: list[dict[str, str]]) -> pl.DataFrame:
    """构造与 CSV 等价的全字符串 DataFrame。"""
    columns = [
        "symbol",
        "symbol_name",
        "entry_date",
        "rank",
        "score",
        "suggest_weight",
        "reason_text",
    ]
    return pl.DataFrame(
        [{col: row.get(col, "") for col in columns} for row in rows],
        schema={col: pl.Utf8 for col in columns},
    )


async def _run(db: _FakeDb, frame: Any, **kwargs: Any) -> Any:
    return await import_picks(
        db,
        strategy="STR_STK_001",
        trading_day=kwargs.pop("trading_day", _TRADING_DAY),
        source=frame,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 入参形态
# ---------------------------------------------------------------------------


async def test_import_from_polars_frame() -> None:
    db = _FakeDb()

    result = await _run(db, _frame([{"symbol": "600000.SH", "symbol_name": "示例股A"}]))

    assert result.status == "committed"
    assert result.batch_id == 7
    assert db.commits == 1
    assert len(db.inserted) == 1
    row = db.inserted[0]
    assert (row["symbol"], row["exchange"], row["asset_class"]) == ("600000", "SSE", "stock")
    assert (row["direction"], row["option_type"]) == ("long", None)


async def test_import_from_csv_file_keeps_leading_zeros(tmp_path: Any) -> None:
    csv_path = tmp_path / "picks.csv"
    csv_path.write_text(
        "symbol,symbol_name,entry_date,rank,score,suggest_weight,reason_text\n"
        "000001.SZ,示例股B,,2,82.1,0.25,理由\n",
        encoding="utf-8",
    )
    db = _FakeDb()

    result = await _run(db, csv_path)

    assert result.status == "committed"
    # 类型推断会把 000001 变成 1，导入路径必须全列按字符串读。
    assert db.inserted[0]["symbol"] == "000001"
    assert db.inserted[0]["rank"] == 2
    assert db.inserted[0]["score"] == Decimal("82.1")
    assert db.inserted[0]["suggest_weight"] == Decimal("0.25")


async def test_import_rejects_unsupported_source_type() -> None:
    with pytest.raises(BadRequest, match="unsupported source type"):
        await _run(_FakeDb(), 42)


async def test_missing_symbol_column_raises() -> None:
    frame = pl.DataFrame({"code": ["600000.SH"]}, schema={"code": pl.Utf8})

    with pytest.raises(BadRequest, match="missing required column"):
        await _run(_FakeDb(), frame)


async def test_unknown_columns_are_ignored_with_warning() -> None:
    frame = pl.DataFrame(
        {"symbol": ["600000.SH"], "sector": ["银行"]},
        schema={"symbol": pl.Utf8, "sector": pl.Utf8},
    )

    result = await _run(_FakeDb(), frame)

    assert result.status == "committed"
    assert any("sector" in w for w in result.warnings)


async def test_empty_pool_requires_explicit_flag() -> None:
    empty = _frame([])

    with pytest.raises(BadRequest, match="allow_empty"):
        await _run(_FakeDb(), empty)

    db = _FakeDb()
    result = await _run(db, empty, allow_empty=True)

    # item_count=0 是合法状态：基金经理确认当日空仓。
    assert result.status == "committed"
    assert db.batch_params is not None
    assert db.batch_params["item_count"] == 0
    assert db.inserted == []


# ---------------------------------------------------------------------------
# 校验清单（§4.5）
# ---------------------------------------------------------------------------


async def test_invalid_symbol_blocks_without_writing() -> None:
    db = _FakeDb()

    result = await _run(db, _frame([{"symbol": "600000"}]))

    assert result.status == "blocked"
    assert result.ok is False
    assert result.errors[0]["row_number"] == 2
    assert result.errors[0]["error_code"] == "invalid_symbol"
    assert db.inserted == []
    assert db.commits == 0


async def test_duplicate_symbol_in_file_blocks() -> None:
    result = await _run(
        _FakeDb(),
        _frame([{"symbol": "600000.SH"}, {"symbol": "600000.SH"}]),
    )

    assert result.status == "blocked"
    assert [e["error_code"] for e in result.errors] == ["duplicate"]
    assert result.errors[0]["row_number"] == 3


async def test_entry_date_after_trading_day_blocks() -> None:
    result = await _run(
        _FakeDb(),
        _frame([{"symbol": "600000.SH", "entry_date": "2026-08-20"}]),
    )

    assert [e["error_code"] for e in result.errors] == ["out_of_range"]


async def test_percentage_style_weight_blocks() -> None:
    """填百分数（25 而不是 0.25）是高频错误，这条专治它。"""
    result = await _run(
        _FakeDb(),
        _frame([{"symbol": "600000.SH", "suggest_weight": "25"}]),
    )

    assert result.errors[0]["column"] == "suggest_weight"
    assert "0.25 means 25%" in result.errors[0]["message"]


async def test_bad_rank_and_date_and_number_are_reported_together() -> None:
    result = await _run(
        _FakeDb(),
        _frame(
            [
                {"symbol": "600000.SH", "rank": "0"},
                {"symbol": "000001.SZ", "entry_date": "2026/08/11"},
                {"symbol": "300750.SZ", "score": "abc"},
            ]
        ),
    )

    # 一次把整份文件的问题都告诉用户，而不是逐行失败。
    assert {e["error_code"] for e in result.errors} == {
        "out_of_range",
        "invalid_date",
        "invalid_number",
    }
    assert result.summary["error_rows"] == 3
    assert result.summary["total_rows"] == 3


async def test_out_of_order_upload_is_rejected() -> None:
    db = _FakeDb()
    db.max_day = date(2026, 8, 14)

    with pytest.raises(BadRequest, match="out-of-order upload"):
        await _run(db, _frame([{"symbol": "600000.SH"}]))


async def test_same_day_reupload_needs_overwrite() -> None:
    db = _FakeDb()
    db.max_day = _TRADING_DAY
    db.active_batches[_TRADING_DAY] = {"batch_id": 3, "item_count": 4}

    with pytest.raises(Conflict, match="overwrite=True"):
        await _run(db, _frame([{"symbol": "600000.SH"}]))

    result = await _run(db, _frame([{"symbol": "600000.SH"}]), overwrite=True)

    assert result.status == "committed"
    assert db.superseded == 1
    # 先删后插：重传的池子可能比原来少几个标的，UPSERT 会留下脏行。
    assert db.deleted == 1
    assert result.summary["will_delete"] == 4


async def test_dry_run_validates_without_writing() -> None:
    db = _FakeDb()

    result = await _run(db, _frame([{"symbol": "600000.SH"}]), dry_run=True)

    assert result.status == "validated"
    assert result.batch_id is None
    assert db.inserted == []
    assert db.commits == 0


# ---------------------------------------------------------------------------
# 入池日推算（§4.3）
# ---------------------------------------------------------------------------


def _prev_item(trading_day: date, entry_date: date) -> dict[str, Any]:
    return {
        "symbol": "600000",
        "exchange": "SSE",
        "direction": "long",
        "product_code": "600000",
        "trading_day": trading_day,
        "entry_date": entry_date,
        "product_entry_date": entry_date,
    }


async def test_first_time_entry_date_defaults_to_trading_day() -> None:
    db = _FakeDb()

    await _run(db, _frame([{"symbol": "600000.SH"}]))

    row = db.inserted[0]
    assert row["entry_date"] == _TRADING_DAY
    assert row["entry_date_source"] == "derived"
    assert row["product_entry_date"] == _TRADING_DAY


async def test_provided_entry_date_wins_and_product_date_falls_back_to_it() -> None:
    """附录 A.2 的关键用例。

    兜底值若取 trading_day，``product_entry_date <= entry_date`` 会判假，
    **整批插入失败** —— 而「带入系统上线前的历史持仓」是每个基金经理首次
    接入的必经场景。
    """
    db = _FakeDb()

    await _run(db, _frame([{"symbol": "000001.SZ", "entry_date": "2026-08-05"}]))

    row = db.inserted[0]
    assert row["entry_date"] == date(2026, 8, 5)
    assert row["entry_date_source"] == "provided"
    assert row["product_entry_date"] == date(2026, 8, 5)
    assert row["product_entry_date"] <= row["entry_date"]


async def test_continuous_holding_inherits_entry_date() -> None:
    db = _FakeDb()
    db.max_day = _PREV_DAY
    db.active_batches[_PREV_DAY] = {"batch_id": 1, "item_count": 4}
    db.day_items[_PREV_DAY] = [_prev_item(_PREV_DAY, date(2026, 8, 5))]

    await _run(db, _frame([{"symbol": "600000.SH"}]))

    # provided 的历史口径跨日延续，不会漂回上传日。
    assert db.inserted[0]["entry_date"] == date(2026, 8, 5)
    assert db.inserted[0]["entry_date_source"] == "derived"
    # 连续上传时只看上一期池子，不该再去扫全量历史。
    assert not any("DISTINCT ON" in sql for sql in db.statements)


async def test_gap_in_pool_resets_entry_date() -> None:
    """中间确实断过（上一交易日有批次但这只票不在里面）→ 视为重新入池。"""
    db = _FakeDb()
    db.max_day = _PREV_DAY
    db.active_batches[_PREV_DAY] = {"batch_id": 1, "item_count": 4}
    db.day_items[_PREV_DAY] = [_prev_item(_PREV_DAY, date(2026, 8, 3)) | {"symbol": "000002"}]

    await _run(db, _frame([{"symbol": "600000.SH"}]))

    assert db.inserted[0]["entry_date"] == _TRADING_DAY


async def test_missing_previous_batch_carries_entry_date_over() -> None:
    """漏传：无法区分「出池了」和「那天没传」→ 沿用不重置，并写系统提示。"""
    db = _FakeDb()
    db.max_day = date(2026, 8, 10)
    db.last_symbol_rows = [_prev_item(date(2026, 8, 10), date(2026, 8, 5))]

    result = await _run(db, _frame([{"symbol": "600000.SH"}]), note="本期备注")

    assert db.inserted[0]["entry_date"] == date(2026, 8, 5)
    assert any(CARRY_OVER_NOTE in w for w in result.warnings)
    assert db.batch_params is not None
    assert db.batch_params["note"].startswith("本期备注")
    assert CARRY_OVER_NOTE in db.batch_params["note"]


async def test_missing_calendar_carries_over_and_warns() -> None:
    """交易日历还没 ingest 时，保守方向是沿用，绝不把入池日重置成今天。"""
    db = _FakeDb()
    db.prev_day = None
    db.max_day = date(2026, 8, 10)
    db.last_symbol_rows = [_prev_item(date(2026, 8, 10), date(2026, 8, 5))]

    result = await _run(db, _frame([{"symbol": "600000.SH"}]))

    assert db.inserted[0]["entry_date"] == date(2026, 8, 5)
    assert any("trading_calendar" in w for w in result.warnings)


async def test_product_entry_date_never_later_than_entry_date() -> None:
    """继承来的品种日比 provided 的 entry_date 晚时必须 clamp，否则违反 CHECK。"""
    db = _FakeDb()
    db.max_day = _PREV_DAY
    db.active_batches[_PREV_DAY] = {"batch_id": 1, "item_count": 1}
    db.day_items[_PREV_DAY] = [_prev_item(_PREV_DAY, date(2026, 8, 10))]

    await _run(db, _frame([{"symbol": "600000.SH", "entry_date": "2026-08-06"}]))

    row = db.inserted[0]
    assert row["entry_date"] == date(2026, 8, 6)
    assert row["product_entry_date"] == date(2026, 8, 6)


# ---------------------------------------------------------------------------
# instrument_id / symbol_name 回填
# ---------------------------------------------------------------------------


async def test_instrument_mapping_backfills_name() -> None:
    db = _FakeDb()
    db.instruments = [
        {"symbol": "600000.SH", "exchange": "XSHG", "instrument_id": 1001, "name": "浦发银行"}
    ]

    result = await _run(db, _frame([{"symbol": "600000.SH"}]))

    assert db.inserted[0]["instrument_id"] == 1001
    assert db.inserted[0]["symbol_name"] == "浦发银行"
    assert result.warnings == []


async def test_uploaded_name_wins_over_instrument_name() -> None:
    db = _FakeDb()
    db.instruments = [
        {"symbol": "600000.SH", "exchange": "XSHG", "instrument_id": 1001, "name": "浦发银行"}
    ]

    await _run(db, _frame([{"symbol": "600000.SH", "symbol_name": "快照名"}]))

    # symbol_name 是快照时点名称，上传方给了就以它为准。
    assert db.inserted[0]["symbol_name"] == "快照名"


async def test_unmapped_instrument_does_not_block() -> None:
    """北交所新标的可能还没同步到 meta.instruments，但池子仍是有效业务数据。"""
    db = _FakeDb()

    result = await _run(db, _frame([{"symbol": "830799.BJ"}]))

    assert result.status == "committed"
    assert db.inserted[0]["instrument_id"] is None
    assert any("meta.instruments" in w for w in result.warnings)


async def test_invalid_uploaded_by_is_rejected() -> None:
    with pytest.raises(BadRequest, match="invalid uploaded_by"):
        await _run(_FakeDb(), _frame([{"symbol": "600000.SH"}]), uploaded_by="not-a-uuid")


async def test_invalid_trading_day_is_rejected() -> None:
    with pytest.raises(BadRequest, match="invalid trading_day"):
        await _run(_FakeDb(), _frame([{"symbol": "600000.SH"}]), trading_day="2026/08/12")
