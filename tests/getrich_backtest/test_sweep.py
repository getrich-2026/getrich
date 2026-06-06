from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    GridSearch,
    P,
    ParamSpace,
    Side,
    Strategy,
    SweepRunner,
    get_shanghai_tz,
)
from getrich_backtest.strategy import OrderIntent


def _bars() -> pl.DataFrame:
    tz = get_shanghai_tz()
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=tz),
                datetime(2026, 1, 2, 9, 30, tzinfo=tz),
                datetime(2026, 1, 3, 9, 30, tzinfo=tz),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [Decimal("10"), Decimal("11"), Decimal("12")],
            "high": [Decimal("10.5"), Decimal("11.5"), Decimal("12.5")],
            "low": [Decimal("9.5"), Decimal("10.5"), Decimal("11.5")],
            "close": [Decimal("10"), Decimal("11"), Decimal("12")],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class BuyQtyStrategy(Strategy):
    def __init__(self, qty: Decimal) -> None:
        self.qty = qty
        self.calls = 0

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        self.calls += 1
        if self.calls == 1:
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=self.qty)]
        return None


def _backtest(strategy: Strategy, run_id: str, params: dict[str, object]) -> Backtest:
    tz = get_shanghai_tz()
    return Backtest(
        strategy=strategy,
        bar_loader=DataFrameBarLoader(_bars()),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=tz),
        end=datetime(2026, 1, 4, tzinfo=tz),
        initial_cash=Decimal("1000"),
        run_id=run_id,
        strategy_params=params,
    )


def test_parameter_dimensions_generate_expected_values() -> None:
    assert P.categorical(["a", "b"]).values == ("a", "b")
    assert P.int_range(3, 7, step=2).values == (3, 5, 7)
    assert P.int_range(3, 7, step=2, inclusive=False).values == (3, 5)
    assert P.decimal_range("1.0", "1.5", step="0.25").values == (
        Decimal("1.0"),
        Decimal("1.25"),
        Decimal("1.50"),
    )


def test_param_space_iter_configs_is_deterministic_and_filters_constraints() -> None:
    space = ParamSpace(
        {
            "fast": P.int_range(3, 5),
            "slow": P.categorical([4, 6]),
        }
    )
    space.add_constraint(lambda cfg: int(cfg["fast"]) < int(cfg["slow"]))

    assert list(space.iter_configs()) == [
        {"fast": 3, "slow": 4},
        {"fast": 3, "slow": 6},
        {"fast": 4, "slow": 6},
        {"fast": 5, "slow": 6},
    ]


def test_grid_search_to_dict_exposes_param_space() -> None:
    search = GridSearch(ParamSpace({"qty": P.categorical([Decimal("1"), Decimal("2")])}))

    assert search.to_dict() == {
        "type": "grid",
        "space": {
            "dimensions": {"qty": {"kind": "categorical", "values": [Decimal("1"), Decimal("2")]}}
        },
    }


def test_grid_search_trial_ids_are_deterministic() -> None:
    search = GridSearch(ParamSpace({"qty": P.categorical([Decimal("1"), Decimal("2")])}))

    trials_1 = list(search.iter_trials(sweep_id="sweep-a"))
    trials_2 = list(search.iter_trials(sweep_id="sweep-a"))

    assert [trial.trial_id for trial in trials_1] == [trial.trial_id for trial in trials_2]
    assert [trial.run_id for trial in trials_1] == [trial.run_id for trial in trials_2]
    assert trials_1[0].params == {"qty": Decimal("1")}
    assert trials_1[0].param_fingerprint != trials_1[1].param_fingerprint


def test_sweep_runner_executes_fresh_trials_and_selects_best() -> None:
    created: list[BuyQtyStrategy] = []
    search = GridSearch(ParamSpace({"qty": P.categorical([Decimal("1"), Decimal("5")])}))
    runner = SweepRunner(sweep_id="sweep-a", search=search, select_metric="total_return")

    def strategy_factory(params: dict[str, object]) -> Strategy:
        strategy = BuyQtyStrategy(Decimal(str(params["qty"])))
        created.append(strategy)
        return strategy

    def backtest_factory(strategy: Strategy, trial) -> Backtest:
        return _backtest(strategy, trial.run_id, dict(trial.params))

    result = runner.run(
        strategy_factory=strategy_factory,
        backtest_factory=backtest_factory,
    )

    assert len(created) == 2
    assert created[0] is not created[1]
    assert len(result.completed()) == 2
    assert result.failed() == ()
    assert result.best_trial().trial.params == {"qty": Decimal("5")}
    assert result.summary() == {
        "sweep_id": "sweep-a",
        "select_metric": "total_return",
        "maximize": True,
        "total_trials": 2,
        "completed_trials": 2,
        "failed_trials": 0,
        "best_trial_id": result.trials[1].trial.trial_id,
        "best_run_id": result.trials[1].trial.run_id,
        "best_params": {"qty": Decimal("5")},
        "best_metric_value": result.trials[1].metrics.total_return,
    }
    frame = result.to_frame()
    assert frame.height == 2
    assert "param_qty" in frame.columns
    assert "total_return" in frame.columns
    assert result.trials[0].result is not None
    assert result.trials[0].result.config.strategy_params == {"qty": Decimal("1")}


def test_sweep_runner_captures_failures_when_not_fail_fast() -> None:
    search = GridSearch(ParamSpace({"qty": P.categorical([Decimal("1"), Decimal("2")])}))
    runner = SweepRunner(sweep_id="sweep-fail", search=search, fail_fast=False)

    def strategy_factory(params: dict[str, object]) -> Strategy:
        if params["qty"] == Decimal("2"):
            raise RuntimeError("bad params")
        return BuyQtyStrategy(Decimal(str(params["qty"])))

    def backtest_factory(strategy: Strategy, trial) -> Backtest:
        return _backtest(strategy, trial.run_id, dict(trial.params))

    result = runner.run(
        strategy_factory=strategy_factory,
        backtest_factory=backtest_factory,
    )

    assert len(result.completed()) == 1
    assert len(result.failed()) == 1
    assert result.failed()[0].error_message == "bad params"


def test_sweep_runner_reraises_failures_when_fail_fast() -> None:
    search = GridSearch(ParamSpace({"qty": P.categorical([Decimal("1")])}))
    runner = SweepRunner(sweep_id="sweep-fast", search=search, fail_fast=True)

    with pytest.raises(RuntimeError, match="boom"):
        runner.run(
            strategy_factory=lambda params: BuyQtyStrategy(Decimal("1")),
            backtest_factory=lambda strategy, trial: (_ for _ in ()).throw(RuntimeError("boom")),
        )
