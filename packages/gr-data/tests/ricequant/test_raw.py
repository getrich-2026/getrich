"""计划、源形态、预算和分片恢复；无网络和数据库。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RawIntegrityError,
)
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.ingest.ricequant.supplement_adapter import iter_observations
from gr_data.raw.ricequant.fetchers.supplements import _check_quota, run_supplement
from gr_data.raw.ricequant.planner import plan_slices
from gr_data.raw.ricequant.shapes import decode_response
from gr_data.raw.ricequant.store import RqRawStore


def test_month_leap_boundary_batches_and_replay(rq_options):
    options = rq_options(
        start_date="2024-01-01",
        end_date="2024-03-04",
        index_codes=["866001.RI", "866002.RI"],
        max_symbols_per_request=1,
    )
    days = tuple(pd.bdate_range(options.start_date, options.end_date).date)
    requests = plan_slices(options, days, "a" * 64, mode="init", completed=set())
    assert len(requests) == 6
    assert requests[2].end_date == "2024-02-29"
    complete = {r.request_id for r in requests}
    updated = plan_slices(options, days, "a" * 64, mode="update", completed=complete)
    assert {r.month for r in updated} == {"2024-02", "2024-03"}
    complete.remove(requests[0].request_id)
    updated = plan_slices(options, days, "a" * 64, mode="update", completed=complete)
    assert requests[0] in updated
    assert requests[1] not in updated


def test_snapshot_plan_uses_each_day_and_vx_not_applicable(rq_options):
    options = rq_options("rq_index_components", index_codes=["866002.RI", "VX0001.RI"])
    requests = plan_slices(
        options, (date(2024, 1, 2), date(2024, 1, 3)), "a" * 64, mode="init", completed=set()
    )
    assert len(requests) == 4
    assert sum(r.not_applicable for r in requests) == 2
    assert all(r.start_date == r.end_date for r in requests)


@pytest.mark.parametrize("shape", ["multi", "date", "columns", "duplicate_index_column"])
def test_daily_shapes_preserve_values(rq_request, shape):
    req = rq_request()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "order_book_id": ["866002.RI"] * 2,
            "close": [10.0, 11.0],
        }
    )
    if shape == "multi":
        frame = frame.set_index(["order_book_id", "date"])
    elif shape == "date":
        frame = frame.drop(columns="order_book_id").set_index("date")
    elif shape == "duplicate_index_column":
        frame = frame.set_index(["order_book_id", "date"], drop=False)
    decoded, status = decode_response(req, frame)
    assert status == "complete"
    assert decoded["close"].tolist() == [10.0, 11.0]
    assert decoded["date"].dtype == pd.to_datetime(["2024-01-02"]).dtype


@pytest.mark.parametrize("bad", [None, pd.DataFrame(), pd.DataFrame({"close": [1]})])
def test_ambiguous_daily_empty_never_completes(rq_request, bad):
    with pytest.raises(ContractViolationError):
        decode_response(rq_request(), bad)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_day",
        "unknown_code",
        "duplicate",
        "nan",
        "inf",
        "bad_date",
        "high_low",
        "index_conflict",
    ],
)
def test_invalid_daily_response(rq_request, mutation):
    req = rq_request(fields=["close", "high", "low"])
    frame = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "order_book_id": ["866002.RI"] * 2,
            "close": [10.0, 11.0],
            "high": [12.0, 12.0],
            "low": [9.0, 9.0],
        }
    )
    if mutation == "missing_day":
        frame = frame.iloc[:1]
    elif mutation == "unknown_code":
        frame.loc[0, "order_book_id"] = "866006.RI"
    elif mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif mutation in {"nan", "inf"}:
        frame.loc[0, "close"] = float(mutation)
    elif mutation == "bad_date":
        frame.loc[0, "date"] = "not-a-date"
    elif mutation == "high_low":
        frame.loc[0, "high"] = 8
    else:
        frame = frame.set_index("date", drop=False)
        frame.iloc[0, frame.columns.get_loc("date")] = "2024-01-03"
    with pytest.raises(ContractViolationError):
        decode_response(req, frame)


def test_date_representation_does_not_hide_duplicate(rq_request):
    req = rq_request()
    frame = pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "20240102"], "close": [10, 11, 10]})
    with pytest.raises(ContractViolationError, match="重复"):
        decode_response(req, frame)


def test_snapshot_retains_query_date_source_time_and_native_weight(rq_request):
    req = rq_request("rq_index_components")
    frame, status = decode_response(req, (["000001.XSHE"], pd.Timestamp("2024-01-02 20:00")))
    assert status == "complete"
    assert frame.loc[0, "query_date"] == "2024-01-02"
    assert frame.loc[0, "create_tm"] == pd.Timestamp("2024-01-02 20:00")
    assert frame.attrs["source_metadata"]["pit_status"] == "unverified"
    frame, status = decode_response(req, ([], pd.Timestamp("2024-01-02")))
    assert status == "valid_empty" and frame.empty
    frame, _ = decode_response(
        rq_request("rq_index_weights"), pd.Series([40, 60], index=["000001.XSHE", "600000.XSHG"])
    )
    assert frame["weight"].tolist() == [40, 60]
    assert "effective_date" not in frame


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        (["000001.XSHE"], None),
        (["000001.XSHE"], "NaT"),
        (["000001.XSHE"] * 2, "2024-01-02"),
        ([123], "2024-01-02"),
    ],
)
def test_invalid_components(rq_request, response):
    with pytest.raises(ContractViolationError):
        decode_response(rq_request("rq_index_components"), response)


@pytest.mark.parametrize("values", [[], [-1], [float("nan")], [float("inf")]])
def test_invalid_weights(rq_request, values):
    with pytest.raises(ContractViolationError):
        decode_response(
            rq_request("rq_index_weights"), pd.Series(values, index=["000001.XSHE"] * len(values))
        )


@pytest.mark.parametrize(
    "name,expected", [("rq_index_daily", 1), ("rq_index_components", 2), ("rq_index_weights", 2)]
)
def test_fake_end_to_end_observations(rq_context, rq_options, rq_client, name, expected):
    options = rq_options(name)
    assert (
        run_supplement(
            rq_client, rq_context, options, RicequantImportOptions({name: options}), mode="init"
        )
        == expected
    )
    parts = list(iter_observations(rq_context.paths, options, months=("2024-01",)))
    assert len(parts) == expected
    assert all(p.frame is not None and not p.frame.empty for p in parts)
    assert all(p.manifest["sdk_version"] for p in parts)


def test_quota_zero_is_unlimited_and_reserve_pauses(rq_client):
    rq_client.get_quota = lambda: {"bytes_limit": 0, "bytes_used": 5000}
    _check_quota(rq_client, 0.1)
    rq_client.get_quota = lambda: {"bytes_limit": 1000, "bytes_used": 900}
    with pytest.raises(BudgetDeferredError):
        _check_quota(rq_client, 0.1)


def test_quota_defer_preserves_plan_then_resumes(rq_context, rq_options, rq_client):
    options = rq_options()
    shared = RicequantImportOptions({options.name: options})
    rq_client.quota_used = 900
    with pytest.raises(BudgetDeferredError):
        run_supplement(rq_client, rq_context, options, shared, mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert not store.manifests()
    plans = list(store.base.glob("observations/*/*/plan.json"))
    assert len(plans) == 1
    rq_client.quota_used = 0
    assert run_supplement(rq_client, rq_context, options, shared, mode="update") == 1
    assert len(list(store.base.glob("observations/*/*/plan.json"))) == 1


def test_vx_no_member_or_quota_calls(rq_context, rq_options, rq_client):
    options = rq_options("rq_index_weights", index_codes=["VX0001.RI"])
    assert (
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init") == 0
    )
    assert not rq_client.calls
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert [m["status"] for m in store.manifests()] == ["not_applicable"] * 2


def test_network_retries_and_retains_failed_state(rq_context, rq_options, rq_client):
    options = rq_options(end_date="2024-01-02")
    shared = RicequantImportOptions({})
    rq_client.failures = [ConnectionError("fixture")] * 2
    with pytest.raises(ContractViolationError):
        run_supplement(rq_client, rq_context, options, shared, mode="init")
    assert len([c for c in rq_client.calls if c[0] == "price"]) == 2
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert store.manifests()[0]["status"] == "failed"
    assert run_supplement(rq_client, rq_context, options, shared, mode="update") == 1
    assert store.manifests()[0]["observation_seq"] == 1
    assert store.manifests()[0]["status"] == "complete"


def test_contract_failure_does_not_publish_empty_success(rq_context, rq_options, rq_client):
    options = rq_options()
    rq_client.close = float("nan")
    with pytest.raises(ContractViolationError):
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert store.manifests()[0]["status"] == "blocked"
    assert not list(store.base.rglob("*.parquet"))


def test_missing_calendar_fails_before_sdk(rq_context, rq_options, rq_client):
    rq_context.paths.dataset_file("tushare", "calendar", "SSE").unlink()
    with pytest.raises(RawIntegrityError):
        run_supplement(rq_client, rq_context, rq_options(), RicequantImportOptions({}), mode="init")
    assert not rq_client.calls


def test_timed_out_range_splits_and_only_all_children_complete_parent(
    rq_context, rq_options, rq_client
):
    options = rq_options()
    rq_client.failures = [ConnectionError("fixture")] * 2
    assert (
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init") == 2
    )
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    manifests = store.manifests()
    assert [m["status"] for m in manifests] == ["split", "complete", "complete"]
    assert manifests[0]["request_id"] in store.completed_requests()
    assert len(list(iter_observations(rq_context.paths, options))) == 2


def test_partial_split_does_not_complete_parent_and_resumes(rq_context, rq_options, rq_client):
    options = rq_options(start_date="2024-01-02", end_date="2024-03-01")
    normal = rq_client.get_price
    failed_once = True

    def fail_range_or_second_day(codes, start, end, **kwargs):
        if start == "2024-01-02" and end == "2024-01-31":
            raise ConnectionError("range too wide")
        if start == "2024-01-17" and failed_once:
            raise ConnectionError("offline second half")
        return normal(codes, start, end, **kwargs)

    rq_client.get_price = fail_range_or_second_day
    with pytest.raises(ContractViolationError):
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    manifests = store.manifests()
    parent = next(
        m
        for m in manifests
        if m["status"] == "split" and m["request"]["start_date"] == "2024-01-02"
    )
    assert parent["request_id"] not in store.completed_requests()
    first_half = next(
        m
        for m in manifests
        if m["status"] == "complete" and m["request"]["start_date"] == "2024-01-02"
    )
    failed_once = False
    run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="update")
    assert parent["request_id"] in store.completed_requests()
    assert len([m for m in store.manifests() if m["request_id"] == first_half["request_id"]]) == 1


def test_memory_budget_splits_dates_then_symbols(rq_context, rq_options, rq_client):
    options = rq_options(index_codes=["866001.RI", "866002.RI"], max_pending_bytes=170)
    assert (
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init") == 4
    )
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    parts = list(iter_observations(rq_context.paths, options))
    assert len(parts) == 4 and all(len(p.frame) == 1 for p in parts)
    assert store.manifests()[0]["request_id"] in store.completed_requests()


def test_quota_network_failure_does_not_split_or_fetch(rq_context, rq_options, rq_client):
    def offline():
        raise ConnectionError("fixture")

    rq_client.get_quota = offline
    options = rq_options()
    with pytest.raises(BudgetDeferredError, match="暂不可读"):
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert not store.manifests()
    assert len(list(store.base.glob("observations/*/*/plan.json"))) == 1
    assert not rq_client.calls


@pytest.mark.parametrize("dtype", ["Float64", "Int64", "float64[pyarrow]", "int64[pyarrow]"])
@pytest.mark.parametrize("values", [[pd.NA], [10, pd.NA]])
def test_nullable_close_missing_is_rejected(rq_request, dtype, values):
    request = rq_request(end_date="2024-01-02" if len(values) == 1 else "2024-01-03")
    frame = pd.DataFrame({"date": request.trading_days, "close": pd.Series(values, dtype=dtype)})
    with pytest.raises(ContractViolationError, match="close"):
        decode_response(request, frame)


@pytest.mark.parametrize("dtype", ["Float64", "Int64", "float64[pyarrow]", "int64[pyarrow]"])
def test_nullable_close_valid_values_are_preserved(rq_request, dtype):
    request = rq_request()
    frame = pd.DataFrame({"date": request.trading_days, "close": pd.Series([0, 10], dtype=dtype)})
    decoded, status = decode_response(request, frame)
    assert status == "complete"
    pd.testing.assert_series_equal(decoded["close"], frame["close"])


@pytest.mark.parametrize("existing_history", [False, True])
def test_quota_resume_finishes_round_before_replaying(
    rq_context, rq_options, rq_client, existing_history
):
    options = rq_options("rq_index_weights")
    shared = RicequantImportOptions({})
    if existing_history:
        assert run_supplement(rq_client, rq_context, options, shared, mode="init") == 2
    original = rq_client.index_weights
    fetched = []

    def one_slice_per_quota(code, *, date):
        fetched.append(date)
        result = original(code, date=date)
        rq_client.quota_used = 900
        return result

    rq_client.index_weights = one_slice_per_quota
    for mode in ("update" if existing_history else "init", "update"):
        rq_client.quota_used = 0
        with pytest.raises(BudgetDeferredError):
            run_supplement(rq_client, rq_context, options, shared, mode=mode)
    assert fetched == ["2024-01-02", "2024-01-03"]
    # 最后一个 manifest 发布后暂停：恢复只确认该轮完成，不再下载第一片。
    rq_client.quota_used = 0
    assert run_supplement(rq_client, rq_context, options, shared, mode="update") == 0
    assert fetched == ["2024-01-02", "2024-01-03"]
    # 该轮完成后，下一次正常 update 仍会创建新的观察，不永久跳过回扫。
    rq_client.index_weights = original
    assert run_supplement(rq_client, rq_context, options, shared, mode="update") == 2
    parts = list(iter_observations(rq_context.paths, options))
    assert len(parts) == (6 if existing_history else 4)


def test_split_round_resumes_children_without_repeating_parent(rq_context, rq_options, rq_client):
    options = rq_options()
    shared = RicequantImportOptions({})
    assert run_supplement(rq_client, rq_context, options, shared, mode="init") == 1
    original = rq_client.get_price
    fetched = []
    parents = []

    def split_then_pause(codes, start, end, **kwargs):
        if start != end:
            parents.append((start, end))
            raise ConnectionError("fixture range timeout")
        fetched.append(start)
        frame = original(codes, start, end, **kwargs)
        rq_client.quota_used = 900
        return frame

    rq_client.get_price = split_then_pause
    for _ in range(2):
        rq_client.quota_used = 0
        with pytest.raises(BudgetDeferredError):
            run_supplement(rq_client, rq_context, options, shared, mode="update")
    assert fetched == ["2024-01-02", "2024-01-03"]
    assert len(parents) == rq_context.max_retries
    rq_client.quota_used = 0
    assert run_supplement(rq_client, rq_context, options, shared, mode="update") == 0


def test_existing_gap_is_filled_before_replay_without_round_checkpoint(
    rq_context, rq_options, rq_client
):
    options = rq_options("rq_index_weights")
    shared = RicequantImportOptions({})
    original = rq_client.index_weights
    fetched = []

    def one_slice(code, *, date):
        fetched.append(date)
        frame = original(code, date=date)
        rq_client.quota_used = 900
        return frame

    rq_client.index_weights = one_slice
    with pytest.raises(BudgetDeferredError):
        run_supplement(rq_client, rq_context, options, shared, mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    # 模拟修复前只保存观察、没有本轮检查点的已有分区。
    for checkpoint in (store.base / "rounds").glob("*.json"):
        checkpoint.unlink()
    rq_client.quota_used = 0
    with pytest.raises(BudgetDeferredError):
        run_supplement(rq_client, rq_context, options, shared, mode="update")
    assert fetched == ["2024-01-02", "2024-01-03"]


@pytest.mark.parametrize("dtype", ["Float64", "Int64"])
def test_nullable_missing_close_cannot_publish_success(rq_context, rq_options, rq_client, dtype):
    options = rq_options(end_date="2024-01-02")
    rq_client.get_price = lambda *args, **kwargs: pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "close": pd.Series([pd.NA], dtype=dtype),
        }
    )
    with pytest.raises(ContractViolationError):
        run_supplement(rq_client, rq_context, options, RicequantImportOptions({}), mode="init")
    store = RqRawStore(rq_context.paths, options.name, "v1", options.variant_id)
    assert store.manifests()[0]["status"] == "blocked"
    assert not store.completed_requests()
    assert not list(store.base.rglob("*.parquet"))
