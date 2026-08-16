from datetime import datetime
from decimal import Decimal

import pytest
from gr_backtest import Backtest, DataFrameBarLoader, RunConfig, Strategy, get_shanghai_tz
from gr_backtest.runconfig import _to_bytes


def test_run_config_constructs_with_minimal_fields() -> None:
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="TestStrategy",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("100000"),
    )
    assert cfg.run_id == "run-1"
    assert cfg.strategy_name == "TestStrategy"
    assert cfg.symbols == ("000001.SZ",)
    assert cfg.freq == "1d"
    assert cfg.execution_lag_bars == 1
    assert cfg.created_at is None


def test_run_config_created_at_is_shanghai_aware() -> None:
    tz = get_shanghai_tz()
    created = datetime(2026, 5, 30, 10, 0, tzinfo=tz)
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        created_at=created,
    )
    assert cfg.created_at == created
    assert cfg.created_at.tzinfo is not None


def test_run_config_rejects_empty_run_id() -> None:
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="run_id"):
        RunConfig(
            run_id="",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
        )


def test_run_config_rejects_empty_symbols() -> None:
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="symbols"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=(),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
        )


def test_fingerprint_is_deterministic() -> None:
    tz = get_shanghai_tz()
    cfg1 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    cfg2 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    assert cfg1.fingerprint() == cfg2.fingerprint()


def test_fingerprint_changes_when_parameter_changes() -> None:
    tz = get_shanghai_tz()
    cfg1 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    cfg2 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("2000"),
    )
    assert cfg1.fingerprint() != cfg2.fingerprint()


def test_fingerprint_is_independent_of_run_id() -> None:
    tz = get_shanghai_tz()
    cfg1 = RunConfig(
        run_id="run-a",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    cfg2 = RunConfig(
        run_id="run-b",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    assert cfg1.fingerprint() == cfg2.fingerprint()


def test_fingerprint_changes_when_strategy_params_change() -> None:
    tz = get_shanghai_tz()
    cfg_fast = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        strategy_params={"fast": 5, "slow": 20},
    )
    cfg_slow = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        strategy_params={"fast": 10, "slow": 20},
    )
    assert cfg_fast.fingerprint() != cfg_slow.fingerprint()


def test_strategy_params_mapping_order_does_not_change_fingerprint() -> None:
    tz = get_shanghai_tz()
    cfg1 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        strategy_params={"fast": 5, "slow": 20},
    )
    cfg2 = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        strategy_params={"slow": 20, "fast": 5},
    )
    assert cfg1.fingerprint() == cfg2.fingerprint()


def test_decimal_strategy_params_serialize_stably() -> None:
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        strategy_params={"atr_mult": Decimal("1.50")},
    )
    assert cfg.to_dict()["strategy_params"] == {"atr_mult": Decimal("1.50")}
    assert _to_bytes(cfg.strategy_params) == b"{atr_mult:1.50}"


def test_to_bytes_deterministic() -> None:
    """Private serialization helper should produce consistent output."""
    assert _to_bytes(Decimal("1000")) == b"1000"
    assert _to_bytes("hello") == b"hello"
    assert _to_bytes((1, 2, 3)) == b"(1,2,3)"


def test_backtest_run_result_has_config() -> None:
    """An actual Backtest.run() should populate BacktestResult.config."""
    import polars as pl

    bars = pl.DataFrame(
        {
            "dt": [datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())],
            "symbol": ["000001.SZ"],
            "open": [Decimal("10")],
            "high": [Decimal("11")],
            "low": [Decimal("9")],
            "close": [Decimal("10.5")],
            "volume": [1000.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    bt = Backtest(
        strategy=type("DummyStrategy", (Strategy,), {})(),
        bar_loader=DataFrameBarLoader(bars),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 2, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
        run_id="test-run",
        strategy_params={"window": 5},
    )
    result = bt.run()
    assert result.config.run_id == "test-run"
    assert result.config.symbols == ("000001.SZ",)
    assert result.config.strategy_name == "DummyStrategy"
    assert result.config.initial_cash == Decimal("1000")
    assert result.config.freq == "1d"
    assert result.config.strategy_params == {"window": 5}
    assert result.config.created_at is not None


# ── Freq validation (P10 Phase 1) ────────────────────────────────────────

ALL_VALID_FREQS = ["1m", "5m", "15m", "30m", "60m", "1h", "1d"]


@pytest.mark.parametrize("freq", ALL_VALID_FREQS)
def test_run_config_accepts_all_valid_frequencies(freq: str) -> None:
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq=freq,
    )
    assert cfg.freq == freq


def test_run_config_rejects_invalid_frequency() -> None:
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="freq must be one of"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
            freq="2m",
        )


def test_fingerprint_changes_when_freq_changes() -> None:
    tz = get_shanghai_tz()
    cfg_1d = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="1d",
    )
    cfg_5m = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
    )
    assert cfg_1d.fingerprint() != cfg_5m.fingerprint()


def test_fingerprint_changes_when_strategy_freqs_change() -> None:
    tz = get_shanghai_tz()
    cfg_fast = RunConfig(
        run_id="run-1",
        strategy_name="_combined",
        strategy_names=("Fast", "Slow"),
        strategy_freqs=(("Fast", "5m"), ("Slow", "1d")),
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
    )
    cfg_slow = RunConfig(
        run_id="run-1",
        strategy_name="_combined",
        strategy_names=("Fast", "Slow"),
        strategy_freqs=(("Fast", "1d"), ("Slow", "1d")),
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
    )
    assert cfg_fast.fingerprint() != cfg_slow.fingerprint()


# ── extra_freqs validation (P10 Phase 3) ──────────────────────────────────


def test_extra_freqs_default_empty() -> None:
    """Default extra_freqs is an empty tuple."""
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    assert cfg.extra_freqs == ()


def test_extra_freqs_accepts_single_coarser() -> None:
    """Primary "5m" with extra "1d" is accepted."""
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
        extra_freqs=("1d",),
    )
    assert cfg.extra_freqs == ("1d",)


def test_extra_freqs_accepts_multiple() -> None:
    """Primary "5m" with extras ("1h", "1d") is accepted."""
    tz = get_shanghai_tz()
    cfg = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
        extra_freqs=("1h", "1d"),
    )
    assert cfg.extra_freqs == ("1h", "1d")


def test_extra_freqs_rejects_invalid() -> None:
    """Invalid frequency string is rejected."""
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="extra_freqs contains invalid frequency"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
            freq="5m",
            extra_freqs=("2m",),
        )


def test_extra_freqs_rejects_duplicate() -> None:
    """Duplicate frequencies are rejected."""
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="duplicate"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
            freq="5m",
            extra_freqs=("1d", "1d"),
        )


def test_extra_freqs_rejects_finer_than_primary() -> None:
    """Extra freq finer than primary (1d extra when primary is 1d) is rejected."""
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="must be coarser"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
            freq="1d",
            extra_freqs=("5m",),
        )


def test_extra_freqs_rejects_same_as_primary() -> None:
    """Extra freq same as primary is rejected."""
    tz = get_shanghai_tz()
    with pytest.raises(ValueError, match="must not contain the primary freq"):
        RunConfig(
            run_id="run-1",
            strategy_name="Test",
            symbols=("000001.SZ",),
            start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
            end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
            initial_cash=Decimal("1000"),
            freq="5m",
            extra_freqs=("5m",),
        )


def test_fingerprint_includes_extra_freqs() -> None:
    """Different extra_freqs produce different fingerprints."""
    tz = get_shanghai_tz()
    cfg_no_extra = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
    )
    cfg_with_extra = RunConfig(
        run_id="run-1",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
        freq="5m",
        extra_freqs=("1d",),
    )
    assert cfg_no_extra.fingerprint() != cfg_with_extra.fingerprint()
