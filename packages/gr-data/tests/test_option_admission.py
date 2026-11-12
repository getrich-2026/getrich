"""期权按用途准入在任何写库动作前生效。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.ingest import plan_importers
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.importers.asset_markets import (
    OptionBars1dImporter,
    OptionContractsImporter,
    OptionInstrumentsImporter,
    OptionSymbolMapImporter,
)
from gr_data.ingest.tushare.option_admission import (
    ADMITTED_DATASETS,
    QUOTE_SNAPSHOT_ADMISSION,
    require_option_admission,
    require_option_use,
)
from gr_tools.config import Environment


@pytest.mark.parametrize("dataset", sorted(ADMITTED_DATASETS))
def test_only_explicit_quote_snapshot_admission(dataset):
    require_option_admission(dataset, validation_only=False, admission=QUOTE_SNAPSHOT_ADMISSION)
    require_option_admission(dataset, validation_only=True, admission=None)
    with pytest.raises(IngestGateError):
        require_option_admission(dataset, validation_only=False, admission=None)
    with pytest.raises(IngestGateError):
        require_option_admission(dataset, validation_only=True, admission=QUOTE_SNAPSHOT_ADMISSION)


@pytest.mark.parametrize(
    "use", ["historical_parameters", "historical_pnl", "iv", "greeks", "trading"]
)
def test_historical_or_model_uses_remain_closed(use):
    with pytest.raises(IngestGateError):
        require_option_use(use)
    require_option_use("quote_history")
    require_option_use("current_contract_snapshot")


def test_unknown_dataset_or_admission_refused():
    with pytest.raises(IngestGateError):
        require_option_admission(
            "option_greeks_1d", validation_only=False, admission=QUOTE_SNAPSHOT_ADMISSION
        )
    with pytest.raises(IngestGateError):
        require_option_admission("option_bar_1d", validation_only=False, admission="all")


def test_prod_plan_accepts_purpose_without_validation_flag(tmp_path):
    cfg = Config(
        {},
        Environment(
            tmp_path,
            {"APP_ENV": "prod", "TUSHARE_OPTION_ADMISSION": QUOTE_SNAPSHOT_ADMISSION},
        ),
    )
    assert plan_importers("tushare", cfg, ["option_bars_1d", "option_reference"]) == [
        "option_instruments",
        "option_symbol_map",
        "option_contracts",
        "option_bar_1d",
    ]


@pytest.mark.parametrize("value", ["all", "true", "quote_history", "historical_parameters"])
def test_unknown_env_mode_fails_before_connection(tmp_path, value):
    cfg = Config({}, Environment(tmp_path, {"TUSHARE_OPTION_ADMISSION": value}))
    with pytest.raises(RuntimeError, match="admission"):
        plan_importers("tushare", cfg, ["option_reference"])


@pytest.mark.parametrize(
    "cls",
    [
        OptionInstrumentsImporter,
        OptionSymbolMapImporter,
        OptionContractsImporter,
        OptionBars1dImporter,
    ],
)
def test_default_library_gate_precedes_database_access(tmp_path, cls):
    conn = Mock()
    obj = cls(conn, IngestContext(RawPaths(tmp_path)))
    with pytest.raises(IngestGateError):
        obj.run()
    assert not conn.mock_calls
