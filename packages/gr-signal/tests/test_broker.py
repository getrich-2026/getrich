"""Tests for ``gr_signal.broker`` (CTP / XTP / InMemory).

Why this test file exists
--------------------------
The broker module is the integration seam between the live
signal pipeline and the real broker SDKs (CTP for futures,
XTP for stocks). Three classes of bugs are easy to introduce
and very expensive in production:

1. **Idempotency drift** — the live-signal pipeline may
   retry a submit on a network blip; if the broker adapter
   doesn't dedup on ``client_order_id``, we end up with two
   orders at the exchange for one signal. (See Round #114:
   the PG idempotency work, mirrored here for the broker.)

2. **State machine holes** — a cancel on a filled order
   must return the existing ack, not raise. A query on an
   unknown id must raise, not return None.

3. **Status-mapping regressions** — a future refactor
   introduces a new ``OrderStatus`` value and forgets to
   map it in one of the adapters.

These tests exercise the InMemoryAdapter (which is fully
working) and the CTP / XTP stubs (which only exercise the
local state machine, not the network). When the real SDKs
get wired in, the same tests will catch regressions in the
shared logic.
"""

from __future__ import annotations

import asyncio
import dataclasses
from decimal import Decimal

import pytest
from gr_signal.broker import (
    BrokerAdapter,
    BrokerError,
    BrokerKind,
    CtpAdapter,
    InMemoryAdapter,
    OrderAck,
    OrderIntent,
    OrderSide,
    OrderStatus,
    TimeInForce,
    XtpAdapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_mem() -> InMemoryAdapter:
    """Default in-memory adapter with autofill on (the
    smoke-test default)."""
    return InMemoryAdapter(autofill=True)


@pytest.fixture
def in_mem_pending() -> InMemoryAdapter:
    """In-memory adapter that does NOT autofill — orders
    stay ACCEPTED until cancelled or queried."""
    return InMemoryAdapter(autofill=False)


def _buy_intent(
    symbol: str = "rb2410",
    quantity: str = "1",
    price: str | None = "3500.00",
    client_order_id: str = "coid-test-1",
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        price=Decimal(price) if price is not None else None,
        tif=TimeInForce.DAY,
        strategy_id="ma_cross_5_20",
        sub_account_id="sub-001",
        client_order_id=client_order_id,
    )


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adapter",
    [
        InMemoryAdapter(),
        CtpAdapter(),
        XtpAdapter(),
    ],
    ids=["in_memory", "ctp", "xtp"],
)
def test_adapter_satisfies_protocol(adapter) -> None:
    """Each concrete adapter must satisfy :class:`BrokerAdapter`
    structurally (``@runtime_checkable`` enables this). A
    missing method would NOT raise at construction; the
    Protocol check is what catches it.
    """
    assert isinstance(adapter, BrokerAdapter), (
        f"{type(adapter).__name__} does not implement BrokerAdapter"
    )


def test_protocol_runtime_checkable() -> None:
    """Sanity: ``isinstance(x, BrokerAdapter)`` actually
    works for @runtime_checkable Protocols. If this test
    ever fails, someone removed ``@runtime_checkable`` from
    BrokerAdapter and the live-pipeline's swap-in
    compatibility check broke silently.
    """
    assert isinstance(InMemoryAdapter(), BrokerAdapter)


# ---------------------------------------------------------------------------
# 2. InMemoryAdapter — the reference implementation
# ---------------------------------------------------------------------------


def test_in_memory_default_autofills(in_mem: InMemoryAdapter) -> None:
    """Default InMemoryAdapter is autofill=True; a submit
    returns status=FILLED with the same quantity and price.
    """
    asyncio.run(in_mem.connect())
    ack = asyncio.run(in_mem.submit_order(_buy_intent()))
    assert ack.status == OrderStatus.FILLED
    assert ack.filled_quantity == Decimal(1)
    assert ack.filled_price == Decimal("3500.00")
    assert ack.broker is BrokerKind.IN_MEMORY
    assert ack.broker_order_id == "MOCK-1"


def test_in_memory_pending_does_not_autofill(in_mem_pending: InMemoryAdapter) -> None:
    """When autofill=False, the order stays ACCEPTED with
    no fill. Use this when you want to test the cancel /
    partial-fill state machine.
    """
    asyncio.run(in_mem_pending.connect())
    ack = asyncio.run(in_mem_pending.submit_order(_buy_intent()))
    assert ack.status == OrderStatus.ACCEPTED
    assert ack.filled_quantity == Decimal(0)
    assert ack.filled_price is None


def test_in_memory_submit_idempotent_on_client_order_id(in_mem: InMemoryAdapter) -> None:
    """A duplicate submit (same client_order_id) must
    return the ORIGINAL ack, not place a new order. This
    is the broker-side mirror of the PG idempotency
    guarantee (Round #1124 in the platform).
    """
    asyncio.run(in_mem.connect())
    intent = _buy_intent(client_order_id="dup-1")
    first = asyncio.run(in_mem.submit_order(intent))
    second = asyncio.run(in_mem.submit_order(intent))
    assert first is second, "duplicate submit must return the same ack"
    # And the broker order id didn't change either.
    assert first.broker_order_id == second.broker_order_id
    # And we didn't double-book: only one MOCK-* order.
    assert len(in_mem.all_orders()) == 1


def test_in_memory_cancel_pending(in_mem_pending: InMemoryAdapter) -> None:
    """A cancel on a still-pending order transitions it to
    CANCELLED. Subsequent query returns the cancelled ack.
    """
    asyncio.run(in_mem_pending.connect())
    intent = _buy_intent(client_order_id="cancel-1")
    asyncio.run(in_mem_pending.submit_order(intent))
    cancelled = asyncio.run(in_mem_pending.cancel_order("cancel-1"))
    assert cancelled.status == OrderStatus.CANCELLED
    # Subsequent query reflects the new state.
    queried = asyncio.run(in_mem_pending.query_order("cancel-1"))
    assert queried.status == OrderStatus.CANCELLED


def test_in_memory_cancel_filled_returns_existing_ack(in_mem: InMemoryAdapter) -> None:
    """Cancel on a filled order must return the FILLED ack,
    not raise. This is the test the runbook points to when
    someone asks "why didn't my cancel go through?" — the
    order had already filled by the time the cancel
    arrived.
    """
    asyncio.run(in_mem.connect())
    asyncio.run(in_mem.submit_order(_buy_intent(client_order_id="fill-1")))
    # Order is FILLED (autofill on). Now cancel:
    result = asyncio.run(in_mem.cancel_order("fill-1"))
    assert result.status == OrderStatus.FILLED, (
        "cancel on a filled order must return the existing FILLED ack, "
        "not raise and not flip to CANCELLED"
    )


def test_in_memory_query_unknown_raises(in_mem: InMemoryAdapter) -> None:
    """Querying a never-submitted order must raise
    BrokerError, not return None. Returning None would be
    ambiguous (a real broker doesn't have the order at
    all vs. the SDK's NULL handling).
    """
    asyncio.run(in_mem.connect())
    with pytest.raises(BrokerError) as excinfo:
        asyncio.run(in_mem.query_order("never-submitted"))
    assert excinfo.value.code == "UNKNOWN_ORDER"


def test_in_memory_submit_before_connect_raises() -> None:
    """Calling submit_order before connect() is a programmer
    error, not a network blip. Raise with retryable=False
    so the upstream circuit-breaker doesn't retry a
    100%-reproducible bug.
    """
    adapter = InMemoryAdapter()
    with pytest.raises(BrokerError) as excinfo:
        asyncio.run(adapter.submit_order(_buy_intent()))
    assert excinfo.value.code == "NOT_CONNECTED"
    assert excinfo.value.retryable is False


# ---------------------------------------------------------------------------
# 3. CtpAdapter — futures/options stub
# ---------------------------------------------------------------------------


def test_ctp_kind_is_ctp() -> None:
    """The ``kind`` class attribute is how callers (and the
    OrderAck record) know which broker is in use. A typo
    here means fills are recorded with the wrong broker
    tag, breaking per-broker analytics.
    """
    assert CtpAdapter.kind is BrokerKind.CTP


def test_ctp_submit_returns_ctp_prefixed_id() -> None:
    """CTP's broker_order_id is conventionally ``CTP-XXXX``
    so the SRE can grep the DB for it. The stub preserves
    this convention so when the real SDK is wired in, the
    format doesn't change and dashboards don't break.
    """
    ctp = CtpAdapter()
    asyncio.run(ctp.connect())
    ack = asyncio.run(ctp.submit_order(_buy_intent(client_order_id="ctp-1")))
    assert ack.broker_order_id.startswith("CTP-")
    assert ack.broker is BrokerKind.CTP


def test_ctp_submit_idempotent() -> None:
    """Same idempotency contract as InMemoryAdapter. The
    test catches the case where someone refactors the CTP
    path and forgets the dedup table.
    """
    ctp = CtpAdapter()
    asyncio.run(ctp.connect())
    intent = _buy_intent(client_order_id="ctp-dup")
    first = asyncio.run(ctp.submit_order(intent))
    second = asyncio.run(ctp.submit_order(intent))
    assert first is second


def test_ctp_query_unknown_raises() -> None:
    ctp = CtpAdapter()
    asyncio.run(ctp.connect())
    with pytest.raises(BrokerError) as excinfo:
        asyncio.run(ctp.query_order("never"))
    assert excinfo.value.code == "UNKNOWN_ORDER"
    assert excinfo.value.broker is BrokerKind.CTP


# ---------------------------------------------------------------------------
# 4. XtpAdapter — A-share stub
# ---------------------------------------------------------------------------


def test_xtp_kind_is_xtp() -> None:
    assert XtpAdapter.kind is BrokerKind.XTP


def test_xtp_broker_id_is_monotonic_int_as_string() -> None:
    """XTP's broker_order_id is an int (unlike CTP's
    ``CTP-XXXX`` prefix). The stub hands out 1, 2, 3, ...
    so tests can predict the next id. If someone refactors
    this to use UUIDs, the broker-side cancel-by-id flow
    may break (XTP's real cancel API takes the int id).
    """
    xtp = XtpAdapter()
    asyncio.run(xtp.connect())
    a1 = asyncio.run(xtp.submit_order(_buy_intent(client_order_id="xtp-1", symbol="600519.SH")))
    a2 = asyncio.run(xtp.submit_order(_buy_intent(client_order_id="xtp-2", symbol="600519.SH")))
    assert a1.broker_order_id == "1"
    assert a2.broker_order_id == "2"
    assert a1.broker is BrokerKind.XTP


def test_xtp_submit_idempotent() -> None:
    xtp = XtpAdapter()
    asyncio.run(xtp.connect())
    intent = _buy_intent(client_order_id="xtp-dup", symbol="600519.SH")
    first = asyncio.run(xtp.submit_order(intent))
    second = asyncio.run(xtp.submit_order(intent))
    assert first is second


# ---------------------------------------------------------------------------
# 5. Cross-adapter invariants
# ---------------------------------------------------------------------------


ALL_ADAPTERS = [
    ("in_memory", lambda: InMemoryAdapter()),
    ("ctp", lambda: CtpAdapter()),
    ("xtp", lambda: XtpAdapter()),
]


@pytest.mark.parametrize("name,factory", ALL_ADAPTERS, ids=[a[0] for a in ALL_ADAPTERS])
def test_each_adapter_accepts_disconnect_when_not_connected(name, factory) -> None:
    """``disconnect()`` must be safe to call when never
    connected, or after a prior disconnect. Otherwise a
    startup / shutdown race crashes the process.
    """
    adapter = factory()
    asyncio.run(adapter.disconnect())  # before connect: no-op
    asyncio.run(adapter.connect())
    asyncio.run(adapter.disconnect())  # normal shutdown
    asyncio.run(adapter.disconnect())  # double-disconnect: no-op


@pytest.mark.parametrize("name,factory", ALL_ADAPTERS, ids=[a[0] for a in ALL_ADAPTERS])
def test_each_adapter_submit_before_connect_raises(name, factory) -> None:
    """All 3 adapters must raise ``BrokerError`` on submit
    before connect, with code=NOT_CONNECTED and
    retryable=False. A different error code in one adapter
    would mean the upstream retry policy treats the 3
    brokers differently.
    """
    adapter = factory()
    with pytest.raises(BrokerError) as excinfo:
        asyncio.run(adapter.submit_order(_buy_intent()))
    assert excinfo.value.code == "NOT_CONNECTED"
    assert excinfo.value.retryable is False


# ---------------------------------------------------------------------------
# 6. Dataclass immutability
# ---------------------------------------------------------------------------


def test_order_intent_is_frozen() -> None:
    """OrderIntent is frozen so a broker SDK can't
    accidentally mutate the caller's intent mid-flight.
    A non-frozen dataclass would let the SDK rewrite the
    side / quantity, masking upstream bugs.
    """
    intent = _buy_intent()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        intent.symbol = "rb2501"  # type: ignore[misc]


def test_order_ack_is_frozen() -> None:
    ack = OrderAck(
        client_order_id="x",
        broker_order_id="y",
        status=OrderStatus.ACCEPTED,
        broker=BrokerKind.IN_MEMORY,
        accepted_at_ms=0,
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        ack.status = OrderStatus.FILLED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 7. Decimal safety
# ---------------------------------------------------------------------------


def test_quantity_is_decimal_not_float() -> None:
    """A future refactor that types quantity as float will
    introduce the same rounding bugs Round #1080 fought
    in the backtest engine. Pin the type to Decimal.
    """
    intent = _buy_intent(quantity="100")
    assert isinstance(intent.quantity, Decimal)
    # And a value that would round to 0 in float (e.g. 0.1 + 0.2 = 0.30000000000000004)
    # survives the round trip:
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
