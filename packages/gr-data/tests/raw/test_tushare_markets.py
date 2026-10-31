"""指数、期货日线的供应商契约回归；仅使用临时 raw 与模拟客户端。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.config.pipeline import Config
from gr_data.raw import _build_context
from gr_data.raw.tushare.client import TushareProClient
from gr_data.raw.tushare.context import TushareRawContext
from gr_data.raw.tushare.fetchers.market import FutureBars1dFetcher, IndexBars1dFetcher
from gr_data.raw.tushare.fetchers.reference import FutureCalendarFetcher


def _ctx(paths, start=20240101, end=20240131, **scope):
    scope.setdefault("index_codes", ("000300.SH",))
    return TushareRawContext(
        paths=paths,
        start_date=start,
        end_date=end,
        rate_limit={"sleep_between_requests_sec": 0, "max_retries": 1},
        **scope,
    )


@pytest.mark.parametrize(
    "code,continues", [("920047.BJ", True), ("600000.SH", False), ("000001.SZ", False)]
)
def test_only_bj_bad_raw_date_is_retained_for_pending(tmp_raw_root, code, continues):
    from gr_data.raw.tushare.fetchers.market import Bars1dFetcher

    _calendar(tmp_raw_root, days=("20240102",))
    client = Client(
        lambda api, params: pd.DataFrame(
            [
                {"ts_code": "600000.SH", "trade_date": params["trade_date"], "close": 30.0},
                {"ts_code": code, "trade_date": "bad-date", "close": 30.0},
            ]
        )
    )
    fetcher = Bars1dFetcher(client, _ctx(tmp_raw_root, start=20240102, end=20240102))
    path = tmp_raw_root.dataset_file("tushare", "daily", "2024-01")
    if continues:
        assert fetcher.fetch("init") == 1
        frame = pd.read_parquet(path)
        assert frame.trade_date.tolist() == ["20240102", "bad-date"]
    else:
        with pytest.raises(ValueError):
            fetcher.fetch("init")
        assert not path.exists()


def _write(paths, dataset, name, rows):
    write_parquet(pd.DataFrame(rows), paths.dataset_file("tushare", dataset, name), append=False)


def _calendar(paths, exchange="SSE", days=("20240102", "20240103"), dataset="calendar"):
    _write(
        paths,
        dataset,
        exchange,
        [
            {
                "exchange": exchange,
                "cal_date": d.strftime("%Y%m%d"),
                "is_open": int(d.strftime("%Y%m%d") in days),
            }
            for d in pd.date_range("2024-01-01", "2024-01-31")
        ],
    )


def _indexes(paths, rows=None):
    _write(
        paths,
        "instruments",
        "index",
        rows or [{"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None}],
    )


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def query_all(self, api, **params):
        self.calls.append((api, params))
        return self.response(api, params)


def _index_response(api, params):
    assert api == "index_daily"
    assert params["ts_code"] == "000300.SH"
    assert "trade_date" not in params
    return pd.DataFrame(
        [
            {"ts_code": params["ts_code"], "trade_date": d, "close": 3400.0}
            for d in ("20240102", "20240103")
        ]
    )


def test_index_requests_code_and_month(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    client = Client(_index_response)
    assert IndexBars1dFetcher(client, _ctx(tmp_raw_root)).fetch("init") == 1
    assert len(client.calls) == 1
    assert client.calls[0][1]["start_date"] == "20240101"
    assert client.calls[0][1]["end_date"] == "20240131"
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01"))
    assert frame["trade_date"].tolist() == ["20240102", "20240103"]


@pytest.mark.parametrize(
    "mutation", ["empty", "missing_day", "wrong_code", "wrong_date", "duplicate"]
)
def test_index_bad_response_keeps_old_partition(tmp_raw_root, mutation):
    _calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    _write(
        tmp_raw_root,
        "index_daily",
        "2024-01",
        [{"ts_code": "000300.SH", "trade_date": "20240102", "close": 1.0}],
    )
    path = tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01")
    before = path.read_bytes()

    def response(api, params):
        frame = _index_response(api, params)
        if mutation == "empty":
            return pd.DataFrame()
        if mutation == "missing_day":
            return frame.iloc[:1]
        if mutation == "wrong_code":
            frame["ts_code"] = "000001.SH"
        elif mutation == "wrong_date":
            frame.loc[0, "trade_date"] = "20231229"
        elif mutation == "duplicate":
            frame = pd.concat([frame, frame.iloc[:1]])
        return frame

    with pytest.raises(ValueError):
        IndexBars1dFetcher(Client(response), _ctx(tmp_raw_root)).fetch("update")
    assert path.read_bytes() == before


def test_index_listing_boundary_and_excluded_sw(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "market": "SSE", "list_date": "20240103", "exp_date": None},
            {"ts_code": "801010.SI", "market": "SSE", "list_date": "19990101", "exp_date": None},
            {"ts_code": "399001.SZ", "market": "SZSE", "list_date": "19950123", "exp_date": None},
        ],
    )
    client = Client(lambda api, params: _index_response(api, params).iloc[1:])
    ctx = _ctx(tmp_raw_root, index_codes=(), index_markets=("SSE",))
    assert IndexBars1dFetcher(client, ctx).fetch("init") == 1
    assert [p["ts_code"] for _, p in client.calls] == ["000300.SH"]


def _two_month_calendar(paths):
    open_days = {"20240102", "20240103", "20240201", "20240202"}
    _write(
        paths,
        "calendar",
        "SSE",
        [
            {"exchange": "SSE", "cal_date": d, "is_open": int(d in open_days)}
            for d in pd.date_range("2024-01-01", "2024-02-29").strftime("%Y%m%d")
        ],
    )
    return sorted(open_days)


def test_index_requests_each_code_once_across_months(tmp_raw_root):
    days = _two_month_calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None},
            {"ts_code": "399001.SZ", "list_date": "19950123", "exp_date": None},
        ],
    )

    def response(api, params):
        return pd.DataFrame([{"ts_code": params["ts_code"], "trade_date": d} for d in days])

    client = Client(response)
    ctx = _ctx(tmp_raw_root, end=20240229, index_codes=("000300.SH", "399001.SZ"))
    assert IndexBars1dFetcher(client, ctx).fetch("init") == 2
    assert [(p["ts_code"], p["start_date"], p["end_date"]) for _, p in client.calls] == [
        ("000300.SH", "20240101", "20240229"),
        ("399001.SZ", "20240101", "20240229"),
    ]
    for ym, expected in (("2024-01", days[:2]), ("2024-02", days[2:])):
        frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", ym))
        assert sorted(set(frame["trade_date"])) == expected
        assert len(frame) == 4


def test_index_update_only_publishes_selected_months(tmp_raw_root):
    days = _two_month_calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    jan = tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01")
    for ym, day in (("2024-01", "20240102"), ("2024-02", "20240201")):
        _write(tmp_raw_root, "index_daily", ym, [{"ts_code": "000300.SH", "trade_date": day}])
    before = jan.read_bytes()
    client = Client(
        lambda api, params: pd.DataFrame(
            [{"ts_code": "000300.SH", "trade_date": d} for d in days if d >= params["start_date"]]
        )
    )
    IndexBars1dFetcher(client, _ctx(tmp_raw_root, end=20240229)).fetch("update")
    # update 只重抓最新已有月（2 月），1 月分区原样保留。
    assert [p["start_date"] for _, p in client.calls] == ["20240201"]
    assert jan.read_bytes() == before
    feb = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-02"))
    assert feb["trade_date"].tolist() == days[2:]


def test_index_incomplete_codes_reported_together(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None},
            {"ts_code": "000905.SH", "list_date": "20070115", "exp_date": None},
            {"ts_code": "399001.SZ", "list_date": "19950123", "exp_date": None},
        ],
    )

    def response(api, params):
        if params["ts_code"] == "399001.SZ":
            return pd.DataFrame(
                [{"ts_code": "399001.SZ", "trade_date": d} for d in ("20240102", "20240103")]
            )
        return pd.DataFrame([{"ts_code": params["ts_code"], "trade_date": "20240102"}])

    client = Client(response)
    ctx = _ctx(tmp_raw_root, index_codes=("000300.SH", "000905.SH", "399001.SZ"))
    with pytest.raises(ValueError, match="codes=2") as err:
        IndexBars1dFetcher(client, ctx).fetch("init")
    assert "000300.SH" in str(err.value) and "000905.SH" in str(err.value)
    assert len(client.calls) == 3
    assert not tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01").exists()


@pytest.mark.parametrize(
    "scope,match",
    [
        ({"index_codes": ()}, "index_codes or index_markets"),
        ({"index_codes": ("999999.SH",)}, "Unknown index codes"),
        ({"index_codes": ("801010.XX",)}, "SW index codes"),
    ],
)
def test_index_scope_rejected_before_requests(tmp_raw_root, scope, match):
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "market": "SSE", "list_date": "20050408", "exp_date": None},
            {"ts_code": "801010.XX", "market": "SW", "list_date": "19990101", "exp_date": None},
        ],
    )
    client = Client(_index_response)
    with pytest.raises(ValueError, match=match):
        IndexBars1dFetcher(client, _ctx(tmp_raw_root, **scope)).fetch("init")
    assert client.calls == []


def test_index_update_preserves_unrequested_dates(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    _write(
        tmp_raw_root,
        "index_daily",
        "2024-01",
        [{"ts_code": "000300.SH", "trade_date": 20240102, "close": 1.0}],
    )
    client = Client(lambda api, params: _index_response(api, params).iloc[1:])
    IndexBars1dFetcher(client, _ctx(tmp_raw_root, start=20240103)).fetch("update")
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01"))
    assert frame["trade_date"].tolist() == ["20240102", "20240103"]
    assert frame["close"].tolist() == [1.0, 3400.0]


def test_index_update_replaces_non_sse_trading_dates(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    rows = _index_response("index_daily", {"ts_code": "000300.SH"})
    rows = pd.concat(
        [rows, pd.DataFrame([{"ts_code": "000300.SH", "trade_date": "20240106", "close": 1.0}])],
        ignore_index=True,
    )
    path = tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01")
    write_parquet(rows, path, append=False)
    updated = rows.copy()
    updated.loc[updated["trade_date"].eq("20240106"), "close"] = 2.0
    fetcher = IndexBars1dFetcher(Client(lambda api, params: updated.copy()), _ctx(tmp_raw_root))
    for _ in range(2):
        fetcher.fetch("update")
        frame = pd.read_parquet(path)
        assert len(frame) == 3
        assert not frame.duplicated(["ts_code", "trade_date"]).any()
        assert frame.loc[frame["trade_date"].eq("20240106"), "close"].tolist() == [2.0]


def test_index_calendar_gap_blocks_all_requests(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(tmp_raw_root)
    path = tmp_raw_root.dataset_file("tushare", "calendar", "SSE")
    frame = pd.read_parquet(path)
    write_parquet(frame.loc[frame["cal_date"].ne("20240103")], path, append=False)
    client = Client(_index_response)
    with pytest.raises(ValueError, match="Incomplete trading calendar"):
        IndexBars1dFetcher(client, _ctx(tmp_raw_root)).fetch("init")
    assert client.calls == []


def _futures(paths):
    _write(
        paths,
        "instruments",
        "future",
        [
            {"ts_code": "CU2401.SHF", "exchange": "SHFE"},
            {"ts_code": "A2401.DCE", "exchange": "DCE"},
        ],
    )
    _calendar(paths, "SHFE", ("20240102",), "future_calendar")
    _calendar(paths, "DCE", ("20240103",), "future_calendar")


def test_future_uses_exchange_calendars_not_sse(tmp_raw_root):
    _futures(tmp_raw_root)

    # 不提供 SSE 日历，两个期货所的交易日也刻意不同。
    def response(api, params):
        assert api == "fut_daily"
        code = {"SHFE": "CU2401.SHF", "DCE": "A2401.DCE"}[params["exchange"]]
        return pd.DataFrame([{"ts_code": code, "trade_date": params["trade_date"], "oi": 0.0}])

    client = Client(response)
    assert FutureBars1dFetcher(client, _ctx(tmp_raw_root)).fetch("init") == 1
    assert {(p["exchange"], p["trade_date"]) for _, p in client.calls} == {
        ("SHFE", "20240102"),
        ("DCE", "20240103"),
    }


@pytest.mark.parametrize(
    "mutation",
    ["empty", "wrong_exchange", "wrong_day", "bad_calendar", "missing_calendar", "calendar_gap"],
)
def test_future_incomplete_data_not_published(tmp_raw_root, mutation):
    _futures(tmp_raw_root)
    if mutation == "bad_calendar":
        _write(tmp_raw_root, "future_calendar", "DCE", [{"cal_date": "20240103", "is_open": "bad"}])
    elif mutation == "missing_calendar":
        tmp_raw_root.dataset_file("tushare", "future_calendar", "DCE").unlink()
    elif mutation == "calendar_gap":
        path = tmp_raw_root.dataset_file("tushare", "future_calendar", "DCE")
        frame = pd.read_parquet(path)
        write_parquet(frame.loc[frame["cal_date"].ne("20240103")], path, append=False)

    def response(api, params):
        if mutation == "empty":
            return pd.DataFrame()
        code = {"SHFE": "CU2401.SHF", "DCE": "A2401.DCE"}[params["exchange"]]
        return pd.DataFrame(
            [
                {
                    "ts_code": "IF2401.CFX" if mutation == "wrong_exchange" else code,
                    "trade_date": "20240104" if mutation == "wrong_day" else params["trade_date"],
                }
            ]
        )

    with pytest.raises(ValueError):
        FutureBars1dFetcher(Client(response), _ctx(tmp_raw_root)).fetch("init")
    assert not tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01").exists()


def _gfex(paths):
    _write(
        paths,
        "instruments",
        "future",
        [
            {"ts_code": "CU2401.SHF", "exchange": "SHFE"},
            {"ts_code": "SI2401.GFE", "exchange": "GFEX"},
        ],
    )
    _calendar(paths, "SHFE", ("20240102",), "future_calendar")


def _future_response(api, params):
    code = {"SHFE": "CU2401.SHF", "GFEX": "SI2401.GFE"}[params["exchange"]]
    return pd.DataFrame([{"ts_code": code, "trade_date": params["trade_date"]}])


def test_future_whitelist_skips_excluded_exchange(tmp_raw_root, caplog):
    # 白名单收窄到 SHFE：没有 GFEX 日历也能取其余交易所，且不请求 GFEX。
    _gfex(tmp_raw_root)
    client = Client(_future_response)
    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE",))
    assert FutureBars1dFetcher(client, ctx).fetch("init") == 1
    assert {p["exchange"] for _, p in client.calls} == {"SHFE"}
    assert "GFEX" in caplog.text


def test_future_gfex_included_when_whitelisted(tmp_raw_root):
    _gfex(tmp_raw_root)
    _calendar(tmp_raw_root, "GFEX", ("20240103",), "future_calendar")
    client = Client(_future_response)
    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE", "GFEX"))
    assert FutureBars1dFetcher(client, ctx).fetch("init") == 1
    assert {(p["exchange"], p["trade_date"]) for _, p in client.calls} == {
        ("SHFE", "20240102"),
        ("GFEX", "20240103"),
    }
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"))
    assert set(frame["ts_code"]) == {"CU2401.SHF", "SI2401.GFE"}


def test_future_whitelisted_gfex_without_calendar_fails(tmp_raw_root):
    _gfex(tmp_raw_root)
    client = Client(_future_response)
    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE", "GFEX"))
    with pytest.raises(ValueError, match=r"future_calendar\[GFEX\]"):
        FutureBars1dFetcher(client, ctx).fetch("init")
    assert client.calls == []


def test_future_calendar_uses_official_endpoint(tmp_raw_root, fake_tushare):
    assert FutureCalendarFetcher(fake_tushare, _ctx(tmp_raw_root)).fetch("init") == 6
    assert set(fake_tushare.calls) == {"fut_trade_cal"}
    assert tmp_raw_root.dataset_file("tushare", "future_calendar", "GFEX").exists()


def test_future_calendar_follows_whitelist(tmp_raw_root, fake_tushare):
    ctx = _ctx(tmp_raw_root, future_exchanges=("GFEX",))
    assert FutureCalendarFetcher(fake_tushare, ctx).fetch("init") == 1
    assert tmp_raw_root.dataset_file("tushare", "future_calendar", "GFEX").exists()


def test_future_pagination_respects_supplier_2000_cap():
    class Pro:
        def __init__(self):
            self.offsets = []

        def fut_daily(self, limit, offset, **params):
            self.offsets.append(offset)
            # 模拟真实供应商：即使调用方错误地传 5000，也只返回 2000。
            return pd.DataFrame({"row": range(offset, min(offset + min(limit, 2000), 4501))})

    client = TushareProClient("fake", sleep_between_requests=0)
    pro = Pro()
    client._pro = pro
    assert len(client.query_all("fut_daily", trade_date="20240102")) == 4501
    assert pro.offsets == [0, 2000, 4000]


def test_end_date_is_passed_and_clips_months(tmp_raw_root):
    cfg = Config(
        {
            "paths": {"raw_root": str(tmp_raw_root.root)},
            "providers": {"tushare": {"start_date": 20240101, "end_date": 20240203}},
        }
    )
    ctx = _build_context("tushare", cfg)
    assert IndexBars1dFetcher(None, ctx)._months_to_fetch("init") == [
        ("2024-01", date(2024, 1, 1), date(2024, 1, 31)),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 3)),
    ]


@pytest.mark.parametrize("end", [20230101, 20240230, "20240131", True])
def test_invalid_ranges_rejected_before_requests(end):
    cfg = Config({"providers": {"tushare": {"start_date": 20240101, "end_date": end}}})
    with pytest.raises(ValueError):
        _build_context("tushare", cfg)


def test_scope_config_parsed():
    cfg = Config(
        {
            "providers": {
                "tushare": {
                    "index_codes": [" 000300.SH", "000300.SH", "399001.SZ"],
                    "index_markets": ["SSE"],
                    "future_exchanges": ["SHFE", "GFEX"],
                }
            }
        }
    )
    ctx = _build_context("tushare", cfg)
    assert isinstance(ctx, TushareRawContext)
    assert ctx.index_codes == ("000300.SH", "399001.SZ")
    assert ctx.index_markets == ("SSE",)
    assert ctx.future_exchanges == ("SHFE", "GFEX")
    default = _build_context("tushare", Config({"providers": {"tushare": {}}}))
    assert isinstance(default, TushareRawContext)
    assert default.index_codes == () and "GFEX" in default.future_exchanges


@pytest.mark.parametrize(
    "key,value",
    [
        ("index_codes", "000300.SH"),
        ("index_codes", [""]),
        ("index_codes", ["801010.SI"]),
        ("index_markets", ["SW"]),
        ("index_markets", ["NYSE"]),
        ("future_exchanges", []),
        ("future_exchanges", ["SGX"]),
    ],
)
def test_invalid_scope_rejected(key, value):
    cfg = Config({"providers": {"tushare": {key: value}}})
    with pytest.raises(ValueError, match=key):
        _build_context("tushare", cfg)


def _open_calendar(paths, open_days, end="2024-03-31", exchange="SSE", dataset="calendar"):
    _write(
        paths,
        dataset,
        exchange,
        [
            {"exchange": exchange, "cal_date": d, "is_open": int(d in open_days)}
            for d in pd.date_range("2024-01-01", end).strftime("%Y%m%d")
        ],
    )


def _rows_in_range(days):
    def response(api, params):
        return pd.DataFrame(
            [
                {"ts_code": params["ts_code"], "trade_date": d}
                for d in days
                if params["start_date"] <= d <= params["end_date"]
            ]
        )

    return response


def test_index_update_backfills_new_code_into_old_months(tmp_raw_root):
    days = _two_month_calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None},
            {"ts_code": "399001.SZ", "list_date": "19950123", "exp_date": None},
        ],
    )
    for ym, month_days in (("2024-01", days[:2]), ("2024-02", days[2:])):
        _write(
            tmp_raw_root,
            "index_daily",
            ym,
            [{"ts_code": "000300.SH", "trade_date": d} for d in month_days],
        )
    client = Client(_rows_in_range(days))
    ctx = _ctx(tmp_raw_root, end=20240229, index_codes=("000300.SH", "399001.SZ"))
    assert IndexBars1dFetcher(client, ctx).fetch("update") == 2
    jan = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01"))
    assert set(jan["ts_code"]) == {"000300.SH", "399001.SZ"}
    assert len(jan) == 4


def test_index_update_splits_noncontiguous_months(tmp_raw_root):
    days = ["20240102", "20240201", "20240301"]
    _open_calendar(tmp_raw_root, set(days))
    _indexes(tmp_raw_root)
    for ym, day in (("2024-02", "20240201"), ("2024-03", "20240301")):
        _write(tmp_raw_root, "index_daily", ym, [{"ts_code": "000300.SH", "trade_date": day}])
    feb = tmp_raw_root.dataset_file("tushare", "index_daily", "2024-02")
    before = feb.read_bytes()
    client = Client(_rows_in_range(days))
    assert IndexBars1dFetcher(client, _ctx(tmp_raw_root, end=20240331)).fetch("update") == 2
    # 缺 1 月 + 最新 3 月：分两段请求，不跨越完整的 2 月。
    assert [(p["start_date"], p["end_date"]) for _, p in client.calls] == [
        ("20240101", "20240131"),
        ("20240301", "20240331"),
    ]
    assert feb.read_bytes() == before


def test_index_expired_and_union_scope(tmp_raw_root):
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "market": "SSE", "list_date": 20050408.0, "exp_date": None},
            # 1 月 2 日终止：3 日无数据不算缺口。list_date 整列存成浮点也能解析。
            {
                "ts_code": "000905.SH",
                "market": "CSI",
                "list_date": 20070115.0,
                "exp_date": "20240102",
            },
            {"ts_code": "399001.SZ", "market": "SZSE", "list_date": 19950123.0, "exp_date": None},
        ],
    )

    def response(api, params):
        days = ["20240102"] if params["ts_code"] == "000905.SH" else ["20240102", "20240103"]
        return pd.DataFrame([{"ts_code": params["ts_code"], "trade_date": d} for d in days])

    client = Client(response)
    ctx = _ctx(tmp_raw_root, index_codes=("000905.SH",), index_markets=("SSE",))
    assert IndexBars1dFetcher(client, ctx).fetch("init") == 1
    assert sorted(p["ts_code"] for _, p in client.calls) == ["000300.SH", "000905.SH"]


def test_future_update_backfills_newly_whitelisted_gfex(tmp_raw_root):
    _write(
        tmp_raw_root,
        "instruments",
        "future",
        [
            {"ts_code": "CU2401.SHF", "exchange": "SHFE"},
            {"ts_code": "SI2401.GFE", "exchange": "GFEX"},
        ],
    )
    days = {"20240102", "20240201"}
    for exchange in ("SHFE", "GFEX"):
        _open_calendar(tmp_raw_root, days, "2024-02-29", exchange, "future_calendar")
    for ym, day in (("2024-01", "20240102"), ("2024-02", "20240201")):
        _write(tmp_raw_root, "fut_daily", ym, [{"ts_code": "CU2401.SHF", "trade_date": day}])
    client = Client(_future_response)
    ctx = _ctx(tmp_raw_root, end=20240229, future_exchanges=("SHFE", "GFEX"))
    assert FutureBars1dFetcher(client, ctx).fetch("update") == 2
    assert ("GFEX", "20240102") in {(p["exchange"], p["trade_date"]) for _, p in client.calls}
    jan = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"))
    assert set(jan["ts_code"]) == {"CU2401.SHF", "SI2401.GFE"}


def test_index_narrowed_whitelist_keeps_out_of_scope_rows(tmp_raw_root):
    # 收窄 index_codes（或首次升级时旧 raw 含全量指数）后，最新月重抓不得删除范围外代码。
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None},
            {"ts_code": "000905.SH", "list_date": "20070115", "exp_date": None},
        ],
    )
    _write(
        tmp_raw_root,
        "index_daily",
        "2024-01",
        [
            {"ts_code": c, "trade_date": d, "close": 1.0}
            for c in ("000300.SH", "000905.SH")
            for d in ("20240102", "20240103")
        ],
    )
    IndexBars1dFetcher(Client(_index_response), _ctx(tmp_raw_root)).fetch("update")
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01"))
    assert len(frame) == 4
    assert not frame.duplicated(["ts_code", "trade_date"]).any()
    closes = frame.groupby("ts_code")["close"].unique().to_dict()
    assert closes["000300.SH"].tolist() == [3400.0]
    assert closes["000905.SH"].tolist() == [1.0]


def test_future_narrowed_exchanges_keep_other_exchange_rows(tmp_raw_root):
    _futures(tmp_raw_root)
    _write(
        tmp_raw_root,
        "fut_daily",
        "2024-01",
        [
            {"ts_code": "CU2401.SHF", "trade_date": "20240102", "close": 1.0},
            # 与 SHFE 同一天：只按日期替换会把它一起删掉。
            {"ts_code": "A2401.DCE", "trade_date": "20240102", "close": 1.0},
        ],
    )

    def response(api, params):
        assert params["exchange"] == "SHFE"
        return pd.DataFrame(
            [{"ts_code": "CU2401.SHF", "trade_date": params["trade_date"], "close": 2.0}]
        )

    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE",))
    FutureBars1dFetcher(Client(response), ctx).fetch("update")
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"))
    assert dict(zip(frame["ts_code"], frame["close"], strict=True)) == {
        "CU2401.SHF": 2.0,
        "A2401.DCE": 1.0,
    }


def _late_exchange(paths, gfex_open, gfex_from, shfe_open=("20221101", "20221222", "20240102")):
    # GFEX 2022-12-22 开业；gfex_from 决定供应商日历从哪天开始给出。
    _write(
        paths,
        "instruments",
        "future",
        [
            {"ts_code": "CU2301.SHF", "exchange": "SHFE", "list_date": "20220104"},
            {"ts_code": "SI2308.GFE", "exchange": "GFEX", "list_date": "20221222"},
            {"ts_code": "SIL.GFE", "exchange": "GFEX", "list_date": None},
        ],
    )
    for exchange, open_days, first in (
        ("SHFE", set(shfe_open), "2022-11-01"),
        ("GFEX", gfex_open, gfex_from),
    ):
        _write(
            paths,
            "future_calendar",
            exchange,
            [
                {"exchange": exchange, "cal_date": d, "is_open": int(d in open_days)}
                for d in pd.date_range(first, "2024-01-31").strftime("%Y%m%d")
            ],
        )


@pytest.mark.parametrize(
    "gfex_open,gfex_from",
    [
        ({"20221222", "20240102"}, "2022-12-22"),  # 开业前无日历
        ({"20221101", "20221222", "20240102"}, "2022-11-01"),  # 开业前也标开市
    ],
)
def test_future_exchange_scope_starts_at_first_listing(tmp_raw_root, gfex_open, gfex_from):
    _late_exchange(tmp_raw_root, gfex_open, gfex_from)
    for ym, code, day in (
        ("2022-11", "CU2301.SHF", "20221101"),
        ("2024-01", "CU2401.SHF", "20240102"),
    ):
        _write(tmp_raw_root, "fut_daily", ym, [{"ts_code": code, "trade_date": day}])
    nov = tmp_raw_root.dataset_file("tushare", "fut_daily", "2022-11")
    before = nov.read_bytes()

    def response(api, params):
        if params["exchange"] == "GFEX" and params["trade_date"] < "20221222":
            return pd.DataFrame()
        suffix = {"SHFE": "SHF", "GFEX": "GFE"}[params["exchange"]]
        return pd.DataFrame([{"ts_code": f"X.{suffix}", "trade_date": params["trade_date"]}])

    client = Client(response)
    FutureBars1dFetcher(client, _ctx(tmp_raw_root, start=20221101, end=20240131)).fetch("update")
    calls = {(p["exchange"], p["trade_date"]) for _, p in client.calls}
    # 开业前月份不因缺 .GFE 被判为过期，也不请求开业前日线。
    assert nov.read_bytes() == before
    assert not any(e == "GFEX" and d < "20221222" for e, d in calls)
    assert {("GFEX", "20221222"), ("GFEX", "20240102")} <= calls
    dec = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2022-12"))
    assert set(dec["ts_code"]) == {"X.SHF", "X.GFE"}


def test_future_exchange_without_list_dates_keeps_strict_start(tmp_raw_root):
    # 源清单缺上市日时不放宽：仍按 start_date 要求完整日历。
    _gfex(tmp_raw_root)
    _calendar(tmp_raw_root, "GFEX", ("20240103",), "future_calendar")
    path = tmp_raw_root.dataset_file("tushare", "future_calendar", "GFEX")
    frame = pd.read_parquet(path)
    write_parquet(frame.loc[frame["cal_date"].ge("20240103")], path, append=False)
    client = Client(_future_response)
    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE", "GFEX"))
    with pytest.raises(ValueError, match="Incomplete trading calendar"):
        FutureBars1dFetcher(client, ctx).fetch("init")
    assert client.calls == []


def test_index_init_full_month_keeps_out_of_scope_rows(tmp_raw_root):
    # 整月 init 只按当前白名单重建范围内代码；范围外旧行同样保留。
    _calendar(tmp_raw_root)
    _indexes(
        tmp_raw_root,
        [
            {"ts_code": "000300.SH", "list_date": "20050408", "exp_date": None},
            {"ts_code": "000905.SH", "list_date": "20070115", "exp_date": None},
        ],
    )
    _write(
        tmp_raw_root,
        "index_daily",
        "2024-01",
        [
            {"ts_code": c, "trade_date": d, "close": 1.0}
            for c in ("000300.SH", "000905.SH")
            for d in ("20240102", "20240103")
        ],
    )
    IndexBars1dFetcher(Client(_index_response), _ctx(tmp_raw_root)).fetch("init")
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "index_daily", "2024-01"))
    assert len(frame) == 4
    closes = frame.groupby("ts_code")["close"].unique().to_dict()
    assert closes["000300.SH"].tolist() == [3400.0]
    assert closes["000905.SH"].tolist() == [1.0]


def test_future_init_full_month_keeps_other_exchange_rows(tmp_raw_root):
    _futures(tmp_raw_root)
    _write(
        tmp_raw_root,
        "fut_daily",
        "2024-01",
        [
            {"ts_code": "CU2401.SHF", "trade_date": "20240102", "close": 1.0},
            {"ts_code": "A2401.DCE", "trade_date": "20240102", "close": 1.0},
        ],
    )

    def response(api, params):
        return pd.DataFrame(
            [{"ts_code": "CU2401.SHF", "trade_date": params["trade_date"], "close": 2.0}]
        )

    ctx = _ctx(tmp_raw_root, future_exchanges=("SHFE",))
    FutureBars1dFetcher(Client(response), ctx).fetch("init")
    frame = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2024-01"))
    assert dict(zip(frame["ts_code"], frame["close"], strict=True)) == {
        "CU2401.SHF": 2.0,
        "A2401.DCE": 1.0,
    }


def test_future_rows_before_exchange_start_kept(tmp_raw_root):
    # 清单最早上市日晚于旧 raw（如清单缺老合约）：同日重抓其他所时不得删掉起点前的旧行。
    _late_exchange(
        tmp_raw_root,
        {"20221222", "20240102"},
        "2022-12-22",
        shfe_open=("20221201", "20221222", "20240102"),
    )
    _write(
        tmp_raw_root,
        "fut_daily",
        "2022-12",
        [
            {"ts_code": "CU2301.SHF", "trade_date": "20221222"},
            {"ts_code": "OLD.GFE", "trade_date": "20221201"},
        ],
    )

    def response(api, params):
        suffix = {"SHFE": "SHF", "GFEX": "GFE"}[params["exchange"]]
        return pd.DataFrame([{"ts_code": f"X.{suffix}", "trade_date": params["trade_date"]}])

    ctx = _ctx(tmp_raw_root, start=20221201, end=20221231)
    FutureBars1dFetcher(Client(response), ctx).fetch("update")
    dec = pd.read_parquet(tmp_raw_root.dataset_file("tushare", "fut_daily", "2022-12"))
    assert set(zip(dec["ts_code"], dec["trade_date"], strict=True)) == {
        ("OLD.GFE", "20221201"),
        ("X.SHF", "20221201"),
        ("X.SHF", "20221222"),
        ("X.GFE", "20221222"),
    }
