"""Tests for StrategyRegistry."""

from dataclasses import FrozenInstanceError

import pytest
from gr_backtest.registry import (
    StrategyEntry,
    StrategyRegistry,
    get_registry,
)
from gr_backtest.strategies import BollingerMeanReversion, MACross
from gr_backtest.strategy import SignalStrategy, Strategy
from gr_signal.errors import StrategyRegistryError


# ── Helpers ────────────────────────────────────────────────────────────────


def _fresh_registry() -> StrategyRegistry:
    """Return a fresh registry (not the singleton)."""
    return StrategyRegistry()


# ── StrategyEntry dataclass ─────────────────────────────────────────────────


def test_strategy_entry_frozen() -> None:
    """StrategyEntry is frozen (immutable)."""
    entry = StrategyEntry(name="test", display_name="T", factory=Strategy)
    with pytest.raises(FrozenInstanceError):
        entry.name = "other"  # type: ignore[misc]


def test_strategy_entry_default_kwargs_empty() -> None:
    """default_kwargs defaults to empty dict."""
    entry = StrategyEntry(name="test", display_name="T", factory=Strategy)
    assert entry.default_kwargs == {}


# ── Built-in strategy registration ──────────────────────────────────────────


def test_registry_has_macross() -> None:
    """MACross is registered as 'macross'."""
    reg = _fresh_registry()
    entry = reg.get("macross")
    assert entry.name == "macross"
    assert entry.display_name == "MA Crossover"
    assert entry.default_kwargs == {"fast": 10, "slow": 30}


def test_registry_has_bollinger() -> None:
    """BollingerMeanReversion is registered as 'bollinger_meanrev'."""
    reg = _fresh_registry()
    entry = reg.get("bollinger_meanrev")
    assert entry.name == "bollinger_meanrev"
    assert entry.display_name == "Bollinger Mean Reversion"
    assert entry.default_kwargs == {"period": 20, "std": 2}


# ── build() ─────────────────────────────────────────────────────────────────


def test_build_macross_defaults() -> None:
    """build('macross') with no overrides uses defaults."""
    reg = _fresh_registry()
    strategy = reg.build("macross")
    assert isinstance(strategy, MACross)
    assert strategy.fast == 10  # type: ignore[attr-defined]
    assert strategy.slow == 30  # type: ignore[attr-defined]


def test_build_macross_with_overrides() -> None:
    """build('macross', fast=5, slow=20) overrides defaults."""
    reg = _fresh_registry()
    strategy = reg.build("macross", fast=5, slow=20)
    assert isinstance(strategy, MACross)
    assert strategy.fast == 5  # type: ignore[attr-defined]
    assert strategy.slow == 20  # type: ignore[attr-defined]


def test_build_bollinger_defaults() -> None:
    """build('bollinger_meanrev') returns BollingerMeanReversion."""
    reg = _fresh_registry()
    strategy = reg.build("bollinger_meanrev")
    assert isinstance(strategy, BollingerMeanReversion)
    assert strategy.period == 20  # type: ignore[attr-defined]
    assert strategy.std == 2  # type: ignore[attr-defined]


def test_build_unknown_name_raises() -> None:
    """build() with unknown name raises StrategyRegistryError."""
    reg = _fresh_registry()
    with pytest.raises(StrategyRegistryError, match="Unknown strategy"):
        reg.build("nonexistent")


def test_build_bad_kwargs_raises() -> None:
    """build() with invalid kwargs wraps the factory error."""
    reg = _fresh_registry()
    # MACross(fast=100, slow=10) raises ValueError (fast >= slow)
    with pytest.raises(StrategyRegistryError, match="Failed to build"):
        reg.build("macross", fast=100, slow=10)


def test_build_distinct_instances() -> None:
    """Two builds of the same name produce distinct objects."""
    reg = _fresh_registry()
    s1 = reg.build("macross")
    s2 = reg.build("macross")
    assert s1 is not s2


# ── register() custom strategies ────────────────────────────────────────────


def test_register_custom_strategy() -> None:
    """Custom strategy can be registered and retrieved."""
    reg = _fresh_registry()

    class MyStrategy(Strategy):
        def __init__(self, threshold: float = 0.5) -> None:
            self.threshold = threshold

    reg.register("my_strat", "My Strategy", MyStrategy, {"threshold": 0.7})
    entry = reg.get("my_strat")
    assert entry.display_name == "My Strategy"
    assert entry.default_kwargs == {"threshold": 0.7}

    s = reg.build("my_strat")
    assert isinstance(s, MyStrategy)
    assert s.threshold == 0.7  # type: ignore[attr-defined]


def test_register_duplicate_raises() -> None:
    """Registering the same name twice raises StrategyRegistryError."""
    reg = _fresh_registry()
    reg.register("dup", "Dup", Strategy)
    with pytest.raises(StrategyRegistryError, match="already registered"):
        reg.register("dup", "Dup 2", Strategy)


def test_register_signal_strategy() -> None:
    """SignalStrategy subclass can be registered and built."""
    reg = _fresh_registry()

    class MySignalStrategy(SignalStrategy):
        def compute_signal(self, ctx):  # type: ignore[override]
            return None

    reg.register("my_signal", "My Signal", MySignalStrategy)
    s = reg.build("my_signal")
    assert isinstance(s, SignalStrategy)


# ── list_names() ────────────────────────────────────────────────────────────


def test_list_names_includes_builtins_and_customs() -> None:
    """list_names() returns all registered names sorted."""
    reg = _fresh_registry()
    names = reg.list_names()
    assert "bollinger_meanrev" in names
    assert "macross" in names

    reg.register("aaa_custom", "AAA", Strategy)
    names = reg.list_names()
    assert names[0] == "aaa_custom"  # alphabetical


# ── get() error handling ────────────────────────────────────────────────────


def test_get_unknown_name_raises_with_available() -> None:
    """get() with unknown name includes available names in error."""
    reg = _fresh_registry()
    with pytest.raises(StrategyRegistryError, match="Available:"):
        reg.get("unknown")


# ── Singleton ───────────────────────────────────────────────────────────────


def test_get_registry_returns_same_instance() -> None:
    """get_registry() always returns the same singleton."""
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
