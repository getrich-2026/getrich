"""显式观察仅缩小读取范围，不选择最新或改变不可变绑定。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from gr_data.cli import build_parser, cmd_ingest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import RawIntegrityError
from gr_data.ingest import UnknownImporterError, validate_observation_selection
from gr_data.raw.ricequant import riskmodel


@pytest.fixture
def selection(tmp_path, monkeypatch):
    paths = RawPaths(tmp_path)
    options = SimpleNamespace(
        contract_version="v1",
        variant_id="a" * 64,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    root = paths.ricequant_variant("rq_risk_model", "v1", "a" * 64)

    def add(day, obs, variant="a" * 64):
        path = paths.ricequant_variant("rq_risk_model", "v1", variant) / day / obs / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        return path

    monkeypatch.setattr(
        riskmodel,
        "_load",
        lambda path, opts: (
            {"observation_id": path.parent.name, "day": path.parent.parent.name},
            {},
        ),
    )
    return paths, options, root, add


def test_exact_selection_preserves_default_and_ignores_newer_observation(selection):
    paths, options, _, add = selection
    add("2024-01-02", "1" * 32)
    add("2024-01-02", "2" * 32)
    assert len(list(riskmodel.read_bundles(paths, options))) == 2
    result = list(riskmodel.read_bundles(paths, options, observation_id="1" * 32))
    assert [x[0]["observation_id"] for x in result] == ["1" * 32]


@pytest.mark.parametrize("case", ["absent", "date", "month", "variant", "duplicate"])
def test_selection_missing_or_outside_scope_never_falls_back(selection, case):
    paths, options, _, add = selection
    add("2024-01-02", "2" * 32)
    if case == "date":
        add("2024-01-04", "1" * 32)
    elif case == "variant":
        add("2024-01-02", "1" * 32, "b" * 64)
    elif case in {"month", "duplicate"}:
        add("2024-01-02", "1" * 32)
        if case == "duplicate":
            add("2024-01-03", "1" * 32)
    with pytest.raises(RawIntegrityError):
        list(
            riskmodel.read_bundles(
                paths,
                options,
                months=("2024-02",) if case == "month" else None,
                observation_id="1" * 32,
            )
        )


@pytest.mark.parametrize("obs", ["latest", "../x", "A" * 32, "1" * 31, "1" * 33, ""])
def test_invalid_selector_rejected_before_loading(selection, obs):
    paths, options, _, _ = selection
    with pytest.raises(RawIntegrityError):
        list(riskmodel.read_bundles(paths, options, observation_id=obs))
    with pytest.raises(UnknownImporterError):
        validate_observation_selection("ricequant", ["rq_risk_model"], obs)


@pytest.mark.parametrize(
    "provider,only",
    [("tushare", "rq_risk_model"), ("ricequant", None), ("ricequant", "rq_risk_model,rq_daily")],
)
def test_cli_rejects_unsupported_scope_before_database(provider, only, monkeypatch):
    from gr_data import cli

    args = ["ingest", provider, "--observation-id", "1" * 32]
    if only:
        args += ["--only", only]
    monkeypatch.setattr(cli, "connect", lambda *a, **k: pytest.fail("Must not connect"))
    with pytest.raises(UnknownImporterError):
        cmd_ingest(build_parser().parse_args(args), None)
