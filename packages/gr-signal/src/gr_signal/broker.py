"""Real broker integration stubs (CTP / XTP).

This module is intentionally self-contained: it defines the
``BrokerAdapter`` contract, idempotency rules, and executable
integration boundary for future broker SDK adapters.

Why this module exists
----------------------
The live-signal pipeline (``LiveSignalRunner``) emits
:class:`OrderIntent` records but does not — by design —
actually place orders with a broker. Doing so requires a
licensed vendor SDK (CTP for futures/options, XTP for stocks,
恒生UFT, etc.), market data entitlements, and a sandbox or
production account with the broker.

The point of THIS module is to make the *integration shape*
explicit so a future PR can swap in a real SDK without
touching the rest of the live pipeline. Specifically:

1. :class:`BrokerAdapter` is a Protocol that captures the
   minimal order-lifecycle surface a broker integration must
   provide. ``LiveSignalRunner`` (or a thin orchestrator
   layered on top) will depend on this Protocol, NOT on a
   concrete broker class.

2. :class:`CtpAdapter` and :class:`XtpAdapter` are **stubs**
   — they model the SDK's public surface as far as the
   documentation describes it, but they are NOT usable
   against a real broker. They raise :class:`NotImplementedError`
   for the network call paths and return a synthetic
   :class:`OrderAck` for the bookkeeping paths so unit tests
   can drive them.

3. :class:`InMemoryAdapter` is the test/dev counterpart: a
   fully working adapter that keeps orders in a Python dict
   and emits fills synchronously. CI uses this; the live
   signal smoke test uses this; new contributors can exercise
   the full live-signal → broker loop on a laptop without a
   broker account.

What this module is NOT
-----------------------
- A real CTP/XTP wrapper. The vendor SDKs (CTP-API, XTP-API)
  are C++/Cython with platform-specific .so/.dll files; we
  do not bundle them. A future PR should add an optional
  ``ctp`` extra (or similar) that pulls the official wheel.
- A trade-routing layer. The adapter accepts a single
  :class:`OrderIntent` and returns a single :class:`OrderAck`.
  Splitting a parent order into child orders, smart-routing
  across brokers, and TWAP/VWAP schedulers are out of scope.
- Order-management (cancel/modify) — kept on the Protocol
  but stubbed in this round; full OMS lives elsewhere.

Layout
------
::

    broker.py
      ├── BrokerAdapter        (Protocol — the contract)
      ├── OrderSide / Tif      (enums, mirror industry terms)
      ├── OrderIntent / OrderAck dataclasses
      ├── CtpAdapter           (futures / options stub)
      ├── XtpAdapter           (stocks stub)
      └── InMemoryAdapter      (test / dev, fully working)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    """Buy or sell. CTP/XTP both use ``BUY`` / ``SELL`` as
    ASCII strings, not Unicode arrows."""

    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(str, Enum):
    """Order time-in-force.

    We expose the 4 most common values; CTP also has
    ``GFD`` (Good-For-Day, default) and ``GTC`` (Good-Till-Cancel)
    while XTP uses ``DAY`` / ``IOC`` / ``FOK``. The Protocol
    only requires a value be passed; the concrete adapter
    is responsible for mapping to its native vocabulary.
    """

    DAY = "DAY"  # Resting at end of day, auto-cancel
    GTC = "GTC"  # Good-Till-Cancel
    IOC = "IOC"  # Immediate-Or-Cancel
    FOK = "FOK"  # Fill-Or-Kill


class OrderStatus(str, Enum):
    """Lifecycle states. The set here is the union of what
    CTP and XTP expose. A given adapter maps its native
    states onto this enum."""

    PENDING = "PENDING"  # Accepted, not yet at exchange
    ACCEPTED = "ACCEPTED"  # At the exchange, awaiting match
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"  # DAY orders that didn't fill


class BrokerKind(str, Enum):
    """Which vendor SDK this adapter wraps. Recorded on each
    :class:`OrderAck` so an SRE looking at the DB can tell
    whether an order went out via CTP, XTP, or the in-memory
    test adapter."""

    IN_MEMORY = "in_memory"  # dev / test only
    CTP = "ctp"  # futures / options
    XTP = "xtp"  # A-share stocks
    UFT = "uft"  # 恒生 (placeholder for future)
    # NB: not exhaustive — extend as new vendors are wired.


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderIntent:
    """The order the live-signal pipeline wants to place.

    Mirrors the shape of :class:`gr_backtest.execution.OrderIntent`
    but is a separate dataclass because the live side has
    additional fields (account_id, sub_account_id, strategy_id)
    that the backtest side doesn't need. The two are
    intentionally NOT type-aliased so the boundaries stay
    explicit.
    """

    symbol: str  # e.g. "rb2410" (futures) or "600519.SH" (stock)
    side: OrderSide
    quantity: Decimal  # lots for futures, shares for stocks
    price: Decimal | None = None  # None for market orders
    tif: TimeInForce = TimeInForce.DAY
    strategy_id: str = ""  # for routing / audit
    sub_account_id: str = ""  # which sub-account pays
    client_order_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class OrderAck:
    """What the broker returns after a ``submit_order`` call.

    The ``broker_order_id`` is the vendor's ID for the order
    (CTP's ``OrderRef``/``OrderSysID``, XTP's ``order_xtp_id``).
    The ``client_order_id`` is echoed back so the caller can
    correlate. ``status`` is one of :class:`OrderStatus`.

    The ``raw`` field is for the vendor's native response
    object (or a dict stub) — useful for debugging without
    having to know which broker you wired.
    """

    client_order_id: str
    broker_order_id: str  # vendor's order id
    status: OrderStatus
    broker: BrokerKind
    accepted_at_ms: int  # epoch ms when broker accepted
    filled_quantity: Decimal = Decimal(0)
    filled_price: Decimal | None = None  # avg fill price if any
    message: str = ""  # human-readable; "" on success
    raw: object = None  # vendor native; opaque


@dataclass
class BrokerError(Exception):
    """Raised when an adapter fails to place / cancel an order.

    Wraps the vendor's native error code + message so the
    SRE can grep the runbook for the right remediation. The
    ``retryable`` flag distinguishes "transient network blip"
    from "broker says your account is in a bad state".
    """

    broker: BrokerKind
    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.broker.value}] {self.code}: {self.message}"


# ---------------------------------------------------------------------------
# Protocol — the integration contract
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapter(Protocol):
    """The minimal surface a broker integration must expose.

    The :class:`LiveSignalRunner` (or its future orchestrator)
    will depend on this Protocol, NOT on a concrete adapter.
    That way the rest of the live pipeline is testable with
    :class:`InMemoryAdapter` in CI and only the production
    deployment swaps in a real ``CtpAdapter`` / ``XtpAdapter``.

    Implementations must be:

    - **Async**: real brokers take 10-100 ms to ack. We
      don't want to block the live loop on a single round-trip.
    - **Idempotent on client_order_id**: if the same
      ``client_order_id`` is submitted twice (network blip),
      the second call returns the first ack. This is what
      CTP's ``OrderRef`` is for, and what XTP's
      ``order_xtp_id`` lookup pattern is for.
    - **Cancel-before-fill-safe**: calling ``cancel`` on an
      order that's already filled returns the existing
      :class:`OrderAck` with ``status == FILLED`` rather
      than raising.
    """

    kind: BrokerKind  # class-level attribute

    async def connect(self) -> None:
        """Open the broker session (login, query front
        address, etc.). Idempotent — calling twice is a
        no-op.
        """
        ...

    async def disconnect(self) -> None:
        """Tear down the session. Safe to call when already
        disconnected.
        """
        ...

    async def submit_order(self, intent: OrderIntent) -> OrderAck:
        """Place a single order. Must be idempotent on
        ``intent.client_order_id``: a duplicate submit
        returns the original ack.
        """
        ...

    async def cancel_order(self, client_order_id: str) -> OrderAck:
        """Cancel by client_order_id. If the order has
        already filled, return the existing ack with
        ``status == FILLED`` (don't raise).
        """
        ...

    async def query_order(self, client_order_id: str) -> OrderAck:
        """Look up the latest known state of an order.
        Used by the live-signal runner's reconciliation
        loop."""
        ...


# ---------------------------------------------------------------------------
# CTP stub — futures / options
# ---------------------------------------------------------------------------


class CtpAdapter:
    """Stub for the CTP (Comprehensive Transaction Platform) SDK.

    CTP is the dominant A-share futures / options trading
    front-end, published by 上海期货信息技术有限公司
    (Shanghai Futures Information Technology). The official
    SDK is C++ with a Python binding (``ctpapi`` package on
    pip, but the wheel is platform-specific and we don't
    bundle it).

    This stub mirrors the SDK's public surface as far as
    the documentation describes it:

    - ``connect()`` opens a session via ``TdApi.Create()`
      + ``ReqUserLogin()``.
    - ``submit_order()`` calls ``ReqOrderInsert()`` with
      an ``InputOrder`` (the SDK's pre-send struct).
    - ``cancel_order()`` calls ``ReqOrderAction()``.

    Network paths raise :class:`NotImplementedError` with
    a clear "wire the real SDK here" comment; bookkeeping
    paths (idempotency dedup) work so unit tests can drive
    the local state machine.

    The class is intentionally NOT marked ``final`` so a
    future PR can subclass it and override the network
    methods with the real SDK calls.
    """

    kind: BrokerKind = BrokerKind.CTP

    def __init__(
        self, broker_id: str = "", user_id: str = "", password: str = "", front_address: str = ""
    ) -> None:
        # These are the 4 fields a CTP login requires. We
        # store them as plain attributes (no validation) —
        # a subclass with the real SDK will pass them to
        # ``TD.Create`` + ``ReqUserLogin``.
        self._broker_id = broker_id
        self._user_id = user_id
        self._password = password
        self._front_address = front_address
        # Idempotency dedup table: client_order_id -> OrderAck.
        # Populated by submit_order; consulted on every submit
        # so a network blip doesn't place a duplicate.
        self._acks: dict[str, OrderAck] = {}
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            # ---- real SDK call (Round #1163 stub) ----
            # The CTP Python binding has this shape:
            #     self._api = ctpapi.TdApi_Create()
            #     self._api.RegisterFront(self._front_address.encode())
            #     self._api.Init()
            #     self._api.ReqUserLogin({
            #         "BrokerID": self._broker_id,
            #         "UserID": self._user_id,
            #         "Password": self._password,
            #     })
            #     # The response comes back via OnRspUserLogin,
            #     # which is a callback the SDK invokes from
            #     # its own thread; the async wrapper awaits
            #     # a future that the callback completes.
            # For now we just mark connected and log.
            logger.info(
                "CtpAdapter.connect STUB: would dial front=%s broker=%s user=%s",
                self._front_address,
                self._broker_id,
                self._user_id,
            )
            self._connected = True

    async def disconnect(self) -> None:
        async with self._lock:
            if not self._connected:
                return
            # ---- real SDK call (Round #1163 stub) ----
            #     self._api.RegisterSpi(None)
            #     self._api.Release()
            self._connected = False

    async def submit_order(self, intent: OrderIntent) -> OrderAck:
        async with self._lock:
            if not self._connected:
                raise BrokerError(
                    broker=self.kind,
                    code="NOT_CONNECTED",
                    message="submit_order called before connect()",
                    retryable=False,
                )
            # Idempotency: if we've seen this client_order_id
            # before, return the original ack.
            existing = self._acks.get(intent.client_order_id)
            if existing is not None:
                return existing
            # ---- real SDK call (Round #1163 stub) ----
            #     input_order = {
            #         "BrokerID": self._broker_id,
            #         "InvestorID": self._user_id,
            #         "InstrumentID": intent.symbol,
            #         "OrderRef": intent.client_order_id,
            #         "Direction": "0" if intent.side == OrderSide.BUY else "1",
            #         "CombOffsetFlag": "0",  # open
            #         "CombHedgeFlag": "1",  # speculation
            #         "LimitPrice": float(intent.price or 0),
            #         "VolumeTotalOriginal": int(intent.quantity),
            #         "TimeCondition": "3" if intent.tif == TimeInForce.IOC else "0",
            #         "VolumeCondition": "1" if intent.tif == TimeInForce.FOK else "0",
            #     }
            #     self._api.ReqOrderInsert(input_order)
            #     # Ack comes via OnRtnOrder callback.
            ack = OrderAck(
                client_order_id=intent.client_order_id,
                broker_order_id=f"CTP-{uuid.uuid4().hex[:8]}",
                status=OrderStatus.ACCEPTED,
                broker=self.kind,
                accepted_at_ms=int(time.time() * 1000),
                message="STUB: real SDK not wired (Round #1163)",
            )
            self._acks[intent.client_order_id] = ack
            return ack

    async def cancel_order(self, client_order_id: str) -> OrderAck:
        existing = self._acks.get(client_order_id)
        if existing is None:
            raise BrokerError(
                broker=self.kind,
                code="UNKNOWN_ORDER",
                message=f"no order with client_order_id={client_order_id!r}",
                retryable=False,
            )
        # If already filled, the SDK returns the existing
        # status; do not raise.
        if existing.status == OrderStatus.FILLED:
            return existing
        # ---- real SDK call (Round #1163 stub) ----
        #     self._api.ReqOrderAction({
        #         "BrokerID": self._broker_id,
        #         "InvestorID": self._user_id,
        #         "OrderRef": client_order_id,
        #         ...
        #     })
        cancelled = OrderAck(
            client_order_id=client_order_id,
            broker_order_id=existing.broker_order_id,
            status=OrderStatus.CANCELLED,
            broker=self.kind,
            accepted_at_ms=int(time.time() * 1000),
            message="STUB: cancel not wired to real SDK",
        )
        self._acks[client_order_id] = cancelled
        return cancelled

    async def query_order(self, client_order_id: str) -> OrderAck:
        existing = self._acks.get(client_order_id)
        if existing is None:
            raise BrokerError(
                broker=self.kind,
                code="UNKNOWN_ORDER",
                message=f"no order with client_order_id={client_order_id!r}",
                retryable=False,
            )
        return existing


# ---------------------------------------------------------------------------
# XTP stub — A-share stocks
# ---------------------------------------------------------------------------


class XtpAdapter:
    """Stub for the XTP (X-Trade Platform) SDK.

    XTP is 中信证券's trading front-end, widely used in the
    A-share equity market. The official Python binding is
    in the ``xtp`` package (also platform-specific).

    Differences from CTP that we model in the stub:

    - XTP uses ``order_xtp_id`` (an int) as the broker-side
      order id, not CTP's ``OrderSysID`` (a str).
    - XTP has a single ``OrderAction`` enum that covers
      both insert and cancel; CTP has separate APIs.
    - XTP requires the client to choose an account type
      (CREDIT / NORMAL / DERIVATIVES) at login; we model
      that as the optional ``account_type`` arg.

    Like :class:`CtpAdapter`, this is a stub. Network paths
    raise :class:`NotImplementedError`; the dedup / cancel
    / query paths work.
    """

    kind: BrokerKind = BrokerKind.XTP

    def __init__(
        self,
        client_key: str = "",
        account: str = "",
        password: str = "",
        account_type: str = "NORMAL",
    ) -> None:
        self._client_key = client_key
        self._account = account
        self._password = password
        self._account_type = account_type
        # XTP uses an int (not a str) as the broker-side
        # order id; we hand out 1, 2, 3, ... in a monotonic
        # counter so tests can predict them.
        self._next_id: int = 1
        self._acks: dict[str, OrderAck] = {}
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            # ---- real SDK call (Round #1163 stub) ----
            #     self._api = xtp.quote_api.TDCreate()
            #     self._api.SetSoftwareKey(self._client_key)
            #     self._api.SetSoftwareVersion("1.0.0")
            #     self._api.SetAccount(self._account, self._password, self._account_type)
            #     self._api.Init()
            logger.info(
                "XtpAdapter.connect STUB: would dial account=%s type=%s",
                self._account,
                self._account_type,
            )
            self._connected = True

    async def disconnect(self) -> None:
        async with self._lock:
            if not self._connected:
                return
            self._connected = False

    async def submit_order(self, intent: OrderIntent) -> OrderAck:
        async with self._lock:
            if not self._connected:
                raise BrokerError(
                    broker=self.kind,
                    code="NOT_CONNECTED",
                    message="submit_order called before connect()",
                    retryable=False,
                )
            existing = self._acks.get(intent.client_order_id)
            if existing is not None:
                return existing
            # ---- real SDK call (Round #1163 stub) ----
            #     order_id = self._api.InsertOrder(
            #         stock_code=intent.symbol.split(".")[0],  # 600519
            #         market=xtp.MARKET_SHA if ".SH" in intent.symbol else xtp.MARKET_SZA,
            #         price=float(intent.price or 0),
            #         quantity=int(intent.quantity),
            #         price_type=xtp.PRICE_LIMIT if intent.price else xtp.PRICE_Market,
            #         side=xtp.SIDE_BUY if intent.side == OrderSide.BUY else xtp.SIDE_SELL,
            #         position_effect=xtp.POSITION_EFFECT_OPEN,
            #     )
            broker_id_int = self._next_id
            self._next_id += 1
            ack = OrderAck(
                client_order_id=intent.client_order_id,
                broker_order_id=str(broker_id_int),
                status=OrderStatus.ACCEPTED,
                broker=self.kind,
                accepted_at_ms=int(time.time() * 1000),
                message="STUB: real SDK not wired (Round #1163)",
            )
            self._acks[intent.client_order_id] = ack
            return ack

    async def cancel_order(self, client_order_id: str) -> OrderAck:
        existing = self._acks.get(client_order_id)
        if existing is None:
            raise BrokerError(
                broker=self.kind,
                code="UNKNOWN_ORDER",
                message=f"no order with client_order_id={client_order_id!r}",
                retryable=False,
            )
        if existing.status == OrderStatus.FILLED:
            return existing
        # ---- real SDK call (Round #1163 stub) ----
        #     self._api.CancelOrder(int(existing.broker_order_id))
        cancelled = OrderAck(
            client_order_id=client_order_id,
            broker_order_id=existing.broker_order_id,
            status=OrderStatus.CANCELLED,
            broker=self.kind,
            accepted_at_ms=int(time.time() * 1000),
            message="STUB: cancel not wired to real SDK",
        )
        self._acks[client_order_id] = cancelled
        return cancelled

    async def query_order(self, client_order_id: str) -> OrderAck:
        existing = self._acks.get(client_order_id)
        if existing is None:
            raise BrokerError(
                broker=self.kind,
                code="UNKNOWN_ORDER",
                message=f"no order with client_order_id={client_order_id!r}",
                retryable=False,
            )
        return existing


# ---------------------------------------------------------------------------
# InMemoryAdapter — for tests + dev
# ---------------------------------------------------------------------------


class InMemoryAdapter:
    """Test / dev adapter: orders stay in a Python dict and
    fills happen synchronously.

    This is the adapter the live-signal smoke test (and CI
    in general) uses. It implements the full Protocol
    surface, including the **autofill-on-submit** behavior
    so the downstream reconciliation loop has something to
    reconcile against.

    Autofill is opt-in via the constructor: passing
    ``autofill=False`` keeps the order in PENDING state,
    which is the right default for the "reconcile against
    a real broker" code path. For pure smoke tests, leave
    ``autofill=True`` (the default).
    """

    kind: BrokerKind = BrokerKind.IN_MEMORY

    def __init__(self, autofill: bool = True) -> None:
        self._acks: dict[str, OrderAck] = {}
        self._autofill = autofill
        self._connected = False
        self._lock = asyncio.Lock()
        # Monotonic int so tests can assert ordering.
        self._seq: int = 0

    async def connect(self) -> None:
        async with self._lock:
            self._connected = True

    async def disconnect(self) -> None:
        async with self._lock:
            self._connected = False

    async def submit_order(self, intent: OrderIntent) -> OrderAck:
        async with self._lock:
            if not self._connected:
                raise BrokerError(
                    broker=self.kind,
                    code="NOT_CONNECTED",
                    message="submit_order called before connect()",
                    retryable=False,
                )
            existing = self._acks.get(intent.client_order_id)
            if existing is not None:
                return existing
            self._seq += 1
            # Autofill: model an instant fill at the limit
            # price (or a stub price if it's a market order).
            # This is what the downstream reconciliation
            # loop expects to see.
            if self._autofill:
                fill_price = intent.price if intent.price is not None else Decimal(0)
                ack = OrderAck(
                    client_order_id=intent.client_order_id,
                    broker_order_id=f"MOCK-{self._seq}",
                    status=OrderStatus.FILLED,
                    broker=self.kind,
                    accepted_at_ms=int(time.time() * 1000),
                    filled_quantity=intent.quantity,
                    filled_price=fill_price,
                )
            else:
                ack = OrderAck(
                    client_order_id=intent.client_order_id,
                    broker_order_id=f"MOCK-{self._seq}",
                    status=OrderStatus.ACCEPTED,
                    broker=self.kind,
                    accepted_at_ms=int(time.time() * 1000),
                )
            self._acks[intent.client_order_id] = ack
            return ack

    async def cancel_order(self, client_order_id: str) -> OrderAck:
        async with self._lock:
            existing = self._acks.get(client_order_id)
            if existing is None:
                raise BrokerError(
                    broker=self.kind,
                    code="UNKNOWN_ORDER",
                    message=f"no order with client_order_id={client_order_id!r}",
                    retryable=False,
                )
            if existing.status == OrderStatus.FILLED:
                return existing
            cancelled = OrderAck(
                client_order_id=client_order_id,
                broker_order_id=existing.broker_order_id,
                status=OrderStatus.CANCELLED,
                broker=self.kind,
                accepted_at_ms=int(time.time() * 1000),
            )
            self._acks[client_order_id] = cancelled
            return cancelled

    async def query_order(self, client_order_id: str) -> OrderAck:
        async with self._lock:
            existing = self._acks.get(client_order_id)
            if existing is None:
                raise BrokerError(
                    broker=self.kind,
                    code="UNKNOWN_ORDER",
                    message=f"no order with client_order_id={client_order_id!r}",
                    retryable=False,
                )
            return existing

    # ---- test helpers (not part of the Protocol) ----

    def all_orders(self) -> list[OrderAck]:
        """Snapshot of every order the adapter has seen. For
        tests / reconciliation audits.
        """
        return list(self._acks.values())
