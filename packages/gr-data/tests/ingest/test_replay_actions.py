from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from gr_data.ingest.tushare.replay_actions import normalize_actions


def _row(**updates: object) -> dict:
    return {
        "ts_code": "000001.SZ",
        "end_date": "20241231",
        "imp_ann_date": "20250501",
        "ann_date": "20250401",
        "record_date": "20250506",
        "ex_date": "20250507",
        "pay_date": None,
        "div_listdate": None,
        "div_proc": "实施",
        "cash_div_tax": "0.123456",
        "stk_div": None,
        **updates,
    }


def test_same_distribution_appearing_under_two_proposals_is_counted_once() -> None:
    frame = pl.DataFrame([_row(), _row(ann_date="20250402"), _row(div_proc="预案")])
    assert normalize_actions(frame, "dividend") == [
        (
            "000001.SZ",
            date(2024, 12, 31),
            date(2025, 5, 1),
            date(2025, 5, 6),
            date(2025, 5, 7),
            None,
            None,
            Decimal("0.123456"),
            None,
        )
    ]


@pytest.mark.parametrize("change", [{"cash_div_tax": "1.0"}, {"pay_date": "20250508"}])
def test_conflicting_terms_reject_whole_observation(change: dict) -> None:
    with pytest.raises(ValueError, match="Ambiguous"):
        normalize_actions(pl.DataFrame([_row(), _row(**change)]), "dividend")


@pytest.mark.parametrize(
    "change",
    [
        {"cash_div_tax": "NaN"},
        {"stk_div": "-1"},
        {"ex_date": "20251304"},
        {"imp_ann_date": None},
        {"div_proc": "unknown"},
    ],
)
def test_invalid_terms_fail_closed(change: dict) -> None:
    with pytest.raises(ValueError):
        normalize_actions(pl.DataFrame([_row(**change)]), "dividend")


def test_delisted_date_without_a_value_is_only_a_cutoff() -> None:
    frame = pl.DataFrame([{"ts_code": "603963.SH", "list_status": "D", "delist_date": "20250321"}])
    assert normalize_actions(frame, "stock_basic") == [("603963.SH", date(2025, 3, 21))]


def test_full_history_receipt_bound_to_bytes_and_null_terminal_page(tmp_path, monkeypatch) -> None:
    import json
    from hashlib import sha256

    import httpx
    from gr_data.common.paths import RawPaths
    from gr_data.ingest.tushare.replay_actions import read_dividend_coverage
    from gr_data.raw.tushare.dividend_capture import capture_dividend

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        fields = body["fields"].split(",")
        items = [[_row().get(f) for f in fields]] if body["params"]["offset"] == 0 else []
        return httpx.Response(200, json={"code": 0, "data": {"fields": fields, "items": items}})

    monkeypatch.setattr("gr_data.raw.tushare.dividend_capture.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        path = capture_dividend(client, "test", "000001.SZ", RawPaths(tmp_path))
    frame = pl.read_parquet(path)
    digest = sha256(path.read_bytes()).hexdigest()
    assert read_dividend_coverage(path, frame, digest)[0] == "000001.SZ"
    with pytest.raises(ValueError, match="Invalid full-history"):
        read_dividend_coverage(path, frame, "0" * 64)
    proof = json.loads(path.with_suffix(".coverage.json").read_text())
    proof["empty_page_offset"] = 0
    path.with_suffix(".coverage.json").write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="Invalid full-history"):
        read_dividend_coverage(path, frame, digest)


def test_revised_implementation_notice_cannot_double_the_distribution() -> None:
    frame = pl.DataFrame([_row(), _row(imp_ann_date="20250502")])
    with pytest.raises(ValueError, match="Conflicting implementation"):
        normalize_actions(frame, "dividend")


def test_changed_observation_preserves_previously_admitted_dividend(pg_conn, tmp_path) -> None:
    import json
    from hashlib import sha256

    from gr_data.common.replay_evidence import DIVIDEND_SIGNATURE_SQL
    from gr_data.ingest.tushare.replay_actions import import_actions

    with pg_conn.cursor() as cur:
        cur.execute("""INSERT INTO meta.instruments(symbol,asset,exchange)
                       VALUES ('000001.SZ','stock','XSHE') RETURNING instrument_id""")
        iid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
            "VALUES (%s,'tushare','000001.SZ')",
            (iid,),
        )
    path = tmp_path / "dividend.parquet"
    for amount in ("0.2", "0.5"):
        frame = pl.DataFrame([_row(cash_div_tax=amount)])
        frame.write_parquet(path)
        digest = sha256(path.read_bytes()).hexdigest()
        path.with_suffix(".coverage.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "source": "tushare",
                    "dataset": "dividend",
                    "scope": "symbol_full_history",
                    "rows": 1,
                    "empty_page_offset": 1,
                    "symbol": "000001.SZ",
                    "observed_at": "2025-06-01T00:00:00Z",
                    "sha256": digest,
                }
            )
        )
        for _ in range(2):
            assert import_actions(pg_conn, path, "dividend") == 1
    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT d.cash_per_share FROM finance.dividend d
                       JOIN finance.dividend_coverage c USING(instrument_id,raw_sha256)
                       WHERE d.instrument_id=%s ORDER BY 1""",
            (iid,),
        )
        assert cur.fetchall() == [(Decimal(".2"),), (Decimal(".5"),)]
        cur.execute(DIVIDEND_SIGNATURE_SQL, (iid, digest))
        count, original = cur.fetchone()
        assert count == 1
        cur.execute(
            "UPDATE finance.dividend SET cash_per_share=1 WHERE instrument_id=%s AND raw_sha256=%s",
            (iid, digest),
        )
        cur.execute(DIVIDEND_SIGNATURE_SQL, (iid, digest))
        changed_count, changed = cur.fetchone()
        assert changed_count == 1 and changed != original
        cur.execute(
            "DELETE FROM finance.dividend WHERE instrument_id=%s AND raw_sha256=%s", (iid, digest)
        )
        cur.execute(DIVIDEND_SIGNATURE_SQL, (iid, digest))
        deleted_count, deleted = cur.fetchone()
        assert deleted_count == 0 and deleted != original


def test_delisted_universe_is_complete_before_proving_absence(tmp_path, monkeypatch) -> None:
    import json
    from hashlib import sha256

    import httpx
    from gr_data.common.paths import RawPaths
    from gr_data.ingest.tushare.replay_actions import read_delisting_coverage
    from gr_data.raw.tushare.dividend_capture import capture_delistings

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["params"]["list_status"] == "D"
        fields = body["fields"].split(",")
        rows = (
            [["603963.SH", "测试", "SSE", "D", "20100101", "20250321"]]
            if body["params"]["offset"] == 0
            else []
        )
        return httpx.Response(200, json={"code": 0, "data": {"fields": fields, "items": rows}})

    monkeypatch.setattr("gr_data.raw.tushare.dividend_capture.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        path = capture_delistings(client, "test", RawPaths(tmp_path))
    frame = pl.read_parquet(path)
    digest = sha256(path.read_bytes()).hexdigest()
    assert read_delisting_coverage(path, frame, digest).utcoffset() is not None
    with pytest.raises(ValueError, match="Invalid full-history"):
        read_delisting_coverage(path, frame.clear(), digest)
