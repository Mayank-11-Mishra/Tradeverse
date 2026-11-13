"""In-memory broker used by the test-suite and for dry-running the platform.
It is clearly NOT a real broker and is registered as 'mock'."""
from __future__ import annotations

import itertools
from typing import Optional

from app.brokers.base import (AuthError, BrokerAdapter, Capability, Funds, Order, OrderRejected,
                              OrderRequest, OrderUncertain, Position, Profile, register_adapter)


@register_adapter
class MockBroker(BrokerAdapter):
    broker_id = "mock"
    verification = "test-double"
    capabilities = frozenset({Capability.PLACE_ORDER, Capability.MODIFY_ORDER, Capability.CANCEL_ORDER,
                              Capability.ORDER_TAG, Capability.POSITIONS, Capability.FUNDS})

    def __init__(self, account_id: str):
        super().__init__(account_id)
        self.orders: dict = {}
        self.authenticated = False
        self._ids = itertools.count(1)
        # failure injection: None | 'reject' | 'timeout_after_accept' | 'timeout_lost' | 'auth'
        self.failure: Optional[str] = None
        self.place_calls = 0

    async def authenticate(self, credentials: dict) -> Profile:
        if credentials.get("bad"):
            raise AuthError("invalid credentials")
        self.authenticated = True
        return Profile(self.account_id, "Mock User")

    async def logout(self) -> None:
        self.authenticated = False

    async def is_session_valid(self) -> bool:
        return self.authenticated

    async def place_order(self, req: OrderRequest) -> str:
        self.place_calls += 1
        if self.failure == "auth" or not self.authenticated:
            raise AuthError("session expired")
        if self.failure == "reject":
            raise OrderRejected("RMS: insufficient margin")
        oid = f"M{next(self._ids)}"
        if self.failure == "timeout_lost":
            raise OrderUncertain("timeout")            # order never reached the broker
        self.orders[oid] = Order(oid, req, "OPEN", tag=req.client_order_id)
        if self.failure == "timeout_after_accept":
            raise OrderUncertain("timeout")            # broker has the order, we never saw the ack
        return oid

    async def get_orders(self) -> list:
        return list(self.orders.values())

    async def cancel_order(self, order_id: str) -> None:
        self.orders[order_id].status = "CANCELLED"

    async def modify_order(self, order_id: str, **changes) -> None:
        o = self.orders[order_id]
        if o.status != 'OPEN':
            raise OrderRejected('Only open orders can be modified')
        import dataclasses
        allowed = {k:v for k,v in changes.items() if k in ('qty','price','trigger_price','order_type','validity')}
        o.request = dataclasses.replace(o.request,**allowed)

    async def get_positions(self) -> list:
        return []

    async def get_funds(self) -> Funds:
        return Funds(100000.0, 0.0, 100000.0)
