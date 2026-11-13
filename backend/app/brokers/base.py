"""Normalized broker interface.

Every broker adapter implements BrokerAdapter and declares the Capability set it truly
supports. Anything not declared raises UnsupportedCapability: it is never simulated.
Business logic (strategies, charts, execution) only talks to this interface.
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, ClassVar, Optional


# ------------------------------------------------------------------ errors
class BrokerError(Exception):
    pass


class AuthError(BrokerError):
    """Session invalid/expired; re-authentication required."""


class RateLimitError(BrokerError):
    def __init__(self, msg="rate limited", retry_after: Optional[float] = None):
        super().__init__(msg)
        self.retry_after = retry_after


class OrderRejected(BrokerError):
    """Broker definitively rejected the order (safe to treat as not placed)."""


class OrderUncertain(BrokerError):
    """Outcome unknown (timeout / dropped connection). NEVER blindly resend: reconcile first."""


class UnsupportedCapability(BrokerError):
    pass


# ------------------------------------------------------------------ capabilities
class Capability(str, enum.Enum):
    INSTRUMENT_MASTER = "instrument_master"
    HISTORICAL_CANDLES = "historical_candles"
    HISTORICAL_EXPIRED_CONTRACTS = "historical_expired_contracts"
    LIVE_STREAM = "live_stream"
    MARKET_DEPTH = "market_depth"
    OPTION_CHAIN = "option_chain"
    OPTION_GREEKS = "option_greeks"
    PLACE_ORDER = "place_order"
    MODIFY_ORDER = "modify_order"
    CANCEL_ORDER = "cancel_order"
    ORDER_TAG = "order_tag"              # client order id / tag supported (idempotency aid)
    BASKET_ORDER = "basket_order"
    MARGIN_CALC = "margin_calc"
    POSITIONS = "positions"
    HOLDINGS = "holdings"
    FUNDS = "funds"
    TRADEBOOK = "tradebook"


# ------------------------------------------------------------------ models
@dataclass(frozen=True)
class InstrumentKey:
    """Canonical identity: never merge records of different contracts."""
    exchange: str          # NSE, BSE, NFO, BFO, MCX, CDS ...
    symbol: str            # trading symbol as the broker lists it
    segment: str = "EQ"    # EQ, FUT, OPT, IDX, COMM, CUR


@dataclass
class Instrument:
    key: InstrumentKey
    broker_token: str
    name: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    expiry: Optional[datetime] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None    # CE / PE
    underlying: Optional[str] = None


@dataclass
class Candle:
    ts: datetime                # exchange-local, tz-aware
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    oi: Optional[float] = None


@dataclass
class Tick:
    key: InstrumentKey
    ts: datetime
    ltp: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None      # CUMULATIVE day volume when the feed provides it
    oi: Optional[float] = None
    source: str = ""
    previous_close: Optional[float] = None


@dataclass
class OrderRequest:
    key: InstrumentKey
    side: str                   # BUY | SELL
    qty: int
    order_type: str = "MARKET"  # MARKET | LIMIT | SL | SL_M
    product: str = "MIS"        # MIS | CNC | NRML
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    validity: str = "DAY"
    client_order_id: str = ""   # our idempotency key (sent as broker tag where supported)


@dataclass
class Order:
    order_id: str
    request: OrderRequest
    status: str                 # OPEN | PARTIAL | COMPLETE | CANCELLED | REJECTED
    filled_qty: int = 0
    avg_price: float = 0.0
    tag: str = ""
    message: str = ""


@dataclass
class Position:
    key: InstrumentKey
    qty: int
    avg_price: float
    ltp: float = 0.0
    pnl: float = 0.0
    product: str = "MIS"


@dataclass
class Holding:
    key: InstrumentKey
    qty: int
    avg_price: float
    ltp: float = 0.0


@dataclass
class Funds:
    available: float
    used: float
    total: float
    currency: str = "INR"


@dataclass
class Profile:
    account_id: str
    name: str = ""
    email: str = ""


# ------------------------------------------------------------------ interface
class BrokerAdapter(ABC):
    broker_id: ClassVar[str] = ""
    capabilities: ClassVar[frozenset] = frozenset()
    #: Honest verification state. Adapters start 'unverified' until validated against
    #: the broker's current docs AND a live (or sandbox) account.
    verification: ClassVar[str] = "unverified"

    def __init__(self, account_id: str):
        self.account_id = account_id

    @classmethod
    def supports(cls, cap: Capability) -> bool:
        return cap in cls.capabilities

    def _require(self, cap: Capability):
        if cap not in self.capabilities:
            raise UnsupportedCapability(f"{self.broker_id} does not support {cap.value}")

    # lifecycle
    @abstractmethod
    async def authenticate(self, credentials: dict) -> Profile: ...

    @abstractmethod
    async def logout(self) -> None: ...

    async def is_session_valid(self) -> bool:
        return True

    async def verify_session(self) -> bool:
        """Recheck the broker session; real adapters override with a profile call."""
        return await self.is_session_valid()

    # reference + market data
    async def get_instruments(self) -> list:
        self._require(Capability.INSTRUMENT_MASTER)
        raise NotImplementedError

    async def get_historical_data(self, key: InstrumentKey, interval: str,
                                  start: datetime, end: datetime) -> list:
        self._require(Capability.HISTORICAL_CANDLES)
        raise NotImplementedError

    def subscribe_market_data(self, keys: list) -> AsyncIterator[Tick]:
        self._require(Capability.LIVE_STREAM)
        raise NotImplementedError

    async def get_option_chain(self, underlying: str, expiry) -> list:
        self._require(Capability.OPTION_CHAIN)
        raise NotImplementedError

    # trading
    async def place_order(self, req: OrderRequest) -> str:
        self._require(Capability.PLACE_ORDER)
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes) -> None:
        self._require(Capability.MODIFY_ORDER)
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> None:
        self._require(Capability.CANCEL_ORDER)
        raise NotImplementedError

    async def get_orders(self) -> list:
        self._require(Capability.PLACE_ORDER)
        raise NotImplementedError

    async def get_positions(self) -> list:
        self._require(Capability.POSITIONS)
        raise NotImplementedError

    async def get_holdings(self) -> list:
        self._require(Capability.HOLDINGS)
        raise NotImplementedError

    async def get_tradebook(self) -> list:
        self._require(Capability.TRADEBOOK)
        raise NotImplementedError

    async def get_funds(self) -> Funds:
        self._require(Capability.FUNDS)
        raise NotImplementedError


# ------------------------------------------------------------------ registry
_REGISTRY: dict = {}


def register_adapter(cls):
    if not cls.broker_id:
        raise ValueError("adapter must define broker_id")
    _REGISTRY[cls.broker_id] = cls
    return cls


def get_adapter_class(broker_id: str):
    return _REGISTRY[broker_id]


def capability_matrix() -> dict:
    """{broker_id: {capability: bool, 'verification': str}} for the UI/docs."""
    return {
        b: {**{c.value: (c in cls.capabilities) for c in Capability}, "verification": cls.verification}
        for b, cls in _REGISTRY.items()
    }
