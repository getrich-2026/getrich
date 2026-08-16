"""Strategy registry — resolve strategy names to instantiated Strategy objects.

Supports two sources:
  1. Built-in strategies from ``gr_backtest.strategies`` (auto-discovered)
  2. User strategies registered at runtime via ``register()``

Singleton access via ``get_registry()``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from gr_backtest.exceptions import StrategyRegistryError
from gr_backtest.strategies import BollingerMeanReversion, MACross
from gr_backtest.strategy import SignalStrategy, Strategy


@dataclass(frozen=True)
class StrategyEntry:
    """A registered strategy with its factory and default parameters.

    Attributes
    ----------
    name : str
        Unique registry key, e.g. ``"macross"``.
    display_name : str
        Human-readable label, e.g. ``"MA Crossover"``.
    factory : Callable[..., Strategy | SignalStrategy]
        Callable that returns a strategy instance when called with kwargs.
    default_kwargs : dict
        Default keyword arguments passed to the factory.
    """

    name: str
    display_name: str
    factory: Callable[..., Strategy | SignalStrategy]
    default_kwargs: dict = field(default_factory=dict)


class StrategyRegistry:
    """Global registry mapping strategy names to ``StrategyEntry`` records.

    Use ``get_registry()`` to obtain the singleton.

    Examples
    --------
    >>> registry = get_registry()
    >>> strategy = registry.build("macross", fast=5, slow=20)
    >>> isinstance(strategy, MACross)
    True
    """

    def __init__(self) -> None:
        self._entries: dict[str, StrategyEntry] = {}
        self._init_builtins()

    # ------------------------------------------------------------------
    # Built-in strategies
    # ------------------------------------------------------------------

    def _init_builtins(self) -> None:
        """Register built-in strategies from gr_backtest.strategies."""
        self._register_builtin(
            name="macross",
            display_name="MA Crossover",
            factory=MACross,
            default_kwargs={"fast": 10, "slow": 30},
        )
        self._register_builtin(
            name="bollinger_meanrev",
            display_name="Bollinger Mean Reversion",
            factory=BollingerMeanReversion,
            default_kwargs={"period": 20, "std": 2},
        )

    def _register_builtin(
        self,
        name: str,
        display_name: str,
        factory: Callable[..., Strategy | SignalStrategy],
        default_kwargs: dict | None = None,
    ) -> None:
        entry = StrategyEntry(
            name=name,
            display_name=display_name,
            factory=factory,
            default_kwargs=default_kwargs or {},
        )
        self._entries[name] = entry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        display_name: str,
        factory: Callable[..., Strategy | SignalStrategy],
        default_kwargs: dict | None = None,
    ) -> None:
        """Register a custom strategy.

        Parameters
        ----------
        name : str
            Unique name for the strategy. Must not already exist.
        display_name : str
            Human-readable label.
        factory : Callable
            Callable that returns a Strategy instance when called with
            ``**kwargs``.
        default_kwargs : dict, optional
            Default keyword arguments for the factory.

        Raises
        ------
        StrategyRegistryError
            If *name* is already registered.
        """
        if name in self._entries:
            raise StrategyRegistryError(
                f"Strategy '{name}' is already registered. "
                f"Use a different name or unregister first."
            )
        entry = StrategyEntry(
            name=name,
            display_name=display_name,
            factory=factory,
            default_kwargs=default_kwargs or {},
        )
        self._entries[name] = entry

    def get(self, name: str) -> StrategyEntry:
        """Look up a strategy entry by name.

        Raises
        ------
        StrategyRegistryError
            If *name* is not registered.
        """
        if name not in self._entries:
            available = ", ".join(sorted(self._entries))
            raise StrategyRegistryError(f"Unknown strategy '{name}'. Available: [{available}]")
        return self._entries[name]

    def build(self, name: str, **override_kwargs: object) -> Strategy | SignalStrategy:
        """Instantiate a strategy by name with optional parameter overrides.

        Parameters
        ----------
        name : str
            Registered strategy name.
        **override_kwargs
            Keyword arguments that override the strategy's default kwargs.

        Returns
        -------
        Strategy | SignalStrategy
            An instantiated strategy object.

        Raises
        ------
        StrategyRegistryError
            If the name is unknown or the factory callable fails.
        """
        entry = self.get(name)
        kwargs = {**entry.default_kwargs, **override_kwargs}
        try:
            return entry.factory(**kwargs)
        except Exception as exc:
            raise StrategyRegistryError(
                f"Failed to build strategy '{name}' with kwargs {kwargs}: {exc}"
            ) from exc

    def list_names(self) -> list[str]:
        """Return all registered strategy names, sorted alphabetically."""
        return sorted(self._entries)


# ------------------------------------------------------------------
# Singleton access
# ------------------------------------------------------------------

_registry: StrategyRegistry | None = None


def get_registry() -> StrategyRegistry:
    """Return the global ``StrategyRegistry`` singleton."""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
