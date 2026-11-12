from __future__ import annotations

from decimal import Decimal

import pytest
from gr_data.diagnostic_publication import portfolio_hash


def test_portfolio_hash_uses_exact_nonzero_scope() -> None:
    assert portfolio_hash({2: Decimal("0.60"), 1: Decimal("0.4"), 3: Decimal(0)}) == portfolio_hash(
        {1: Decimal("0.4000"), 2: Decimal("0.6")}
    )
    assert portfolio_hash({1: Decimal("0.4"), 2: Decimal("0.6")}) != portfolio_hash(
        {1: Decimal("0.6"), 2: Decimal("0.4")}
    )


@pytest.mark.parametrize("weight", ["NaN", "Infinity", "-Infinity", "-0.1"])
def test_portfolio_hash_rejects_nonfinite_or_negative(weight: str) -> None:
    with pytest.raises(ValueError):
        portfolio_hash({1: Decimal(weight)})


@pytest.mark.parametrize("weights", [{}, {1: Decimal("0.99")}, {1: Decimal("1.01")}])
def test_portfolio_hash_does_not_renormalize(weights: dict[int, Decimal]) -> None:
    with pytest.raises(ValueError):
        portfolio_hash(weights)


def test_universe_hash_is_order_independent_and_has_no_weight_semantics() -> None:
    from gr_data.diagnostic_publication import security_universe_hash

    assert security_universe_hash([22, 11]) == security_universe_hash([11, 22])
    assert security_universe_hash([11, 22]) != security_universe_hash([11])
    assert security_universe_hash([11, 22]) != portfolio_hash(
        {11: Decimal("0.4"), 22: Decimal("0.6")}
    )


@pytest.mark.parametrize("ids", [[], [1, 1], [0], [-1], [True], [1.5], ["1"]])
def test_universe_hash_rejects_invalid_security_lists(ids: list) -> None:
    from gr_data.diagnostic_publication import security_universe_hash

    with pytest.raises(ValueError):
        security_universe_hash(ids)
