"""不可变观察、崩溃恢复及月份有界读取。"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from gr_data.common.ricequant_specs import RawIntegrityError
from gr_data.ingest.ricequant.supplement_adapter import iter_observations
from gr_data.raw.ricequant.shapes import decode_response
from gr_data.raw.ricequant.store import RqRawStore


NOW = datetime(2024, 1, 4, 16, tzinfo=ZoneInfo("Asia/Shanghai"))


def store_for(paths, options):
    return RqRawStore(paths, options.name, "v1", options.variant_id)


def publish(store, request, options, close=10.0):
    frame, _ = decode_response(
        request,
        pd.DataFrame({"date": request.trading_days, "close": [close] * len(request.trading_days)}),
    )
    with store.writer():
        plan = store.begin(request, sdk_version="fixture", evidence=options.evidence)
        return store.publish(plan, frame, status="complete", observed_at=NOW)


def test_unchanged_and_a_b_a_are_three_observations(tmp_raw_root, rq_options, rq_request):
    options, request = rq_options(), rq_request()
    store = store_for(tmp_raw_root, options)
    manifests = [publish(store, request, options, value) for value in (10.0, 11.0, 10.0)]
    assert [m["observation_seq"] for m in manifests] == [1, 2, 3]
    assert len({m["path"] for m in manifests}) == 3
    assert [store.read(m)["close"].iloc[0] for m in manifests] == [10.0, 11.0, 10.0]
    with store.writer(), pytest.raises(RawIntegrityError, match="覆盖"):
        store.publish(manifests[0], store.read(manifests[0]), status="complete", observed_at=NOW)
    assert store_for(tmp_raw_root, options).manifests() == json.loads(json.dumps(manifests))


def test_hash_tamper_and_manifest_tamper_rejected(tmp_raw_root, rq_options, rq_request):
    options = rq_options()
    store = store_for(tmp_raw_root, options)
    manifest = publish(store, rq_request(), options)
    bad = dict(manifest, rows=99)
    with pytest.raises(RawIntegrityError):
        store.read(bad)
    bad = dict(manifest, path="../../outside.parquet")
    with pytest.raises(RawIntegrityError):
        store.read(bad)
    bad = dict(manifest, observed_at="2024-01-04T16:00:00")
    with pytest.raises(RawIntegrityError):
        store.read(bad)
    (store.base / manifest["path"]).write_bytes(b"broken")
    with pytest.raises(RawIntegrityError, match="hash"):
        store.read(manifest)


def test_orphan_after_parquet_does_not_advance_or_get_overwritten(
    tmp_raw_root, rq_options, rq_request, monkeypatch
):
    import gr_data.raw.ricequant.store as module

    options, request = rq_options(), rq_request()
    store = store_for(tmp_raw_root, options)
    original_write = module._json_write

    def crash(path, value):
        if path.name == "manifest.json":
            raise OSError("simulated crash")
        return original_write(path, value)

    monkeypatch.setattr(module, "_json_write", crash)
    with pytest.raises(OSError):
        publish(store, request, options)
    orphan = list(store.base.rglob("*.parquet"))[0]
    original_bytes = orphan.read_bytes()
    assert not store.manifests()
    monkeypatch.setattr(module, "_json_write", original_write)
    recovered = publish(store_for(tmp_raw_root, options), request, options, 11.0)
    assert recovered["observation_seq"] == 2
    assert len(store.manifests()) == 1
    assert orphan.read_bytes() == original_bytes
    assert recovered["path"] != str(orphan.relative_to(store.base))


def test_lock_contention_and_unlocked_publish_fail(tmp_raw_root, rq_options, rq_request):
    options = rq_options()
    first = store_for(tmp_raw_root, options)
    second = store_for(tmp_raw_root, options)
    with pytest.raises(RawIntegrityError, match="持锁"):
        first.begin(rq_request(), sdk_version="fixture", evidence=options.evidence)
    with first.writer(), pytest.raises(RawIntegrityError, match="已有"), second.writer():
        pytest.fail("competing writer acquired lock")
    with second.writer():
        assert (
            second.begin(rq_request(), sdk_version="fixture", evidence=options.evidence)[
                "observation_seq"
            ]
            == 1
        )


def test_month_filter_does_not_read_other_metadata_or_parquet(tmp_raw_root, rq_options, rq_request):
    options = rq_options(start_date="2024-01-01", end_date="2024-02-29")
    store = store_for(tmp_raw_root, options)
    january = rq_request(start_date="2024-01-01", end_date="2024-02-29")
    publish(store, january, options)
    broken = store.base / "observations/2024-02/broken/manifest.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("broken")
    assert len(list(iter_observations(tmp_raw_root, options, months=("2024-01",)))) == 1
    assert store.manifests(months=()) == []
    with pytest.raises(RawIntegrityError):
        store.manifests()
    with pytest.raises(RawIntegrityError):
        store.manifests(months=("../escape",))


def test_symlink_escape_rejected(tmp_raw_root, tmp_path, rq_options, rq_request):
    options = rq_options()
    store = store_for(tmp_raw_root, options)
    manifest = publish(store, rq_request(), options)
    path = store.base / manifest["path"]
    path.unlink()
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"external")
    path.symlink_to(outside)
    with pytest.raises(RawIntegrityError, match="越界"):
        store.read(manifest)


def test_empty_components_retain_source_time_and_sequence(tmp_raw_root, rq_options, rq_request):
    options, request = rq_options("rq_index_components"), rq_request("rq_index_components")
    store = store_for(tmp_raw_root, options)
    frame, status = decode_response(request, ([], pd.Timestamp("2024-01-02 19:00")))
    with store.writer():
        plan = store.begin(request, sdk_version="fixture", evidence=options.evidence)
        manifest = store.publish(plan, frame, status=status, observed_at=NOW)
    assert store.read(manifest) is None
    assert manifest["source_metadata"]["create_tm"] == "2024-01-02T19:00:00"
    assert len(list(iter_observations(tmp_raw_root, options))) == 1


def test_evidence_mismatch_blocks_consumer(tmp_raw_root, rq_options, rq_request):
    options = rq_options()
    store = store_for(tmp_raw_root, options)
    publish(store, rq_request(), options)
    options.evidence["references"] = ["new-fixture"]
    with pytest.raises(RawIntegrityError, match="证据"):
        list(iter_observations(tmp_raw_root, options))


def test_duplicate_observation_sequence_rejected(tmp_raw_root, rq_options, rq_request):
    options = rq_options()
    store = store_for(tmp_raw_root, options)
    publish(store, rq_request(), options)
    second = publish(store, rq_request(), options)
    second["observation_seq"] = 1
    path = store.base / "observations" / "2024-01" / second["observation_id"] / "manifest.json"
    path.write_text(json.dumps(second))
    with pytest.raises(RawIntegrityError, match="序号"):
        store.manifests()
