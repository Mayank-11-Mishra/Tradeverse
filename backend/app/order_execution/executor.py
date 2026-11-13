"""Order executor: risk check -> place -> reconcile on uncertainty.

Rule: after a timeout / uncertain response the order is NEVER blindly resent. The broker
orderbook is queried and matched on our client_order_id (broker tag). If it cannot be
resolved, the account stays blocked (RiskEngine.require_reconciliation) until a human or
a later reconcile() call resolves it.
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.brokers.base import (AuthError, BrokerAdapter, BrokerError, Capability, Order, OrderRejected,
                              OrderRequest, OrderUncertain, RateLimitError)
from app.risk_management.engine import OrderIntent, RiskEngine


@dataclass
class ExecResult:
    status: str                      # PLACED | BLOCKED_BY_RISK | REJECTED | AUTH_ERROR | RATE_LIMITED |
    #                                  RECONCILED_FOUND | UNRESOLVED
    client_order_id: str = ""
    order_id: Optional[str] = None
    reasons: list = field(default_factory=list)


class OrderExecutor:
    def __init__(self, risk: RiskEngine):
        self.risk = risk
        self.log: list = []          # structured audit trail (redacted: no credentials ever pass through here)

    def _audit(self, event: str, **kw):
        self.log.append({"event": event, **kw})

    async def submit(self, adapter: BrokerAdapter, req: OrderRequest, strategy_id: str, now: datetime,
                     mode: str = "live", is_exit: bool = False,
                     feed_age_sec: Optional[float] = None,
                     reference_price: Optional[float] = None,
                     account_scope: Optional[str] = None) -> ExecResult:
        if not req.client_order_id:
            req = dataclasses.replace(req, client_order_id=uuid.uuid4().hex[:20])
        cid = req.client_order_id
        ref_price = reference_price if reference_price is not None else (req.price if req.price is not None else (req.trigger_price or 0.0))
        account_key = account_scope or adapter.account_id
        intent = OrderIntent(adapter.broker_id, account_key, strategy_id, req.key.symbol, req.side,
                             req.qty, ref_price, mode, is_exit)
        decision = self.risk.check(intent, now, feed_age_sec)
        if not decision.allowed:
            self._audit("risk_blocked", cid=cid, reasons=decision.reasons, strategy=strategy_id)
            return ExecResult("BLOCKED_BY_RISK", cid, None, decision.reasons)

        try:
            oid = await adapter.place_order(req)
        except OrderRejected as e:
            self._audit("rejected", cid=cid, msg=str(e))
            return ExecResult("REJECTED", cid, None, [str(e)])
        except AuthError as e:
            self.risk.require_reconciliation(account_key, "authentication lost; re-login required")
            self._audit("auth_error", cid=cid)
            return ExecResult("AUTH_ERROR", cid, None, [str(e)])
        except RateLimitError as e:
            self._audit("rate_limited", cid=cid, retry_after=e.retry_after)
            return ExecResult("RATE_LIMITED", cid, None, [str(e)])
        except (OrderUncertain, BrokerError, TimeoutError, ConnectionError) as e:
            self.risk.record_submitted(intent, now)           # count it: it may be live
            self.risk.require_reconciliation(account_key, f"uncertain order {cid}: {type(e).__name__}")
            self._audit("uncertain", cid=cid, err=type(e).__name__)
            return await self.reconcile(adapter, cid, account_scope=account_scope)

        self.risk.record_submitted(intent, now)
        self._audit("placed", cid=cid, order_id=oid)
        return ExecResult("PLACED", cid, oid)

    async def reconcile(self, adapter: BrokerAdapter, client_order_id: str, account_scope: Optional[str] = None) -> ExecResult:
        """Look the order up in the broker orderbook. Safe to call repeatedly."""
        account_key = account_scope or adapter.account_id
        if not adapter.supports(Capability.ORDER_TAG):
            reason = "broker has no order tag support; manual reconciliation required"
            self.risk.require_reconciliation(account_key, reason)
            return ExecResult("UNRESOLVED", client_order_id, None, [reason])
        try:
            orders = await adapter.get_orders()
        except Exception as e:  # network/auth: stay blocked
            reason = f"orderbook unavailable ({type(e).__name__}); account stays blocked"
            self._audit("reconcile_failed", cid=client_order_id)
            return ExecResult("UNRESOLVED", client_order_id, None, [reason])
        found = [o for o in orders if o.tag == client_order_id]
        if found:
            self.risk.clear_reconciliation(account_key)
            self._audit("reconciled_found", cid=client_order_id, order_id=found[0].order_id)
            return ExecResult("RECONCILED_FOUND", client_order_id, found[0].order_id)
        reason = (f"order {client_order_id} not in orderbook; may be delayed or lost. "
                  "Account stays blocked until confirm_not_placed() or a later reconcile finds it")
        self._audit("reconcile_not_found", cid=client_order_id)
        return ExecResult("UNRESOLVED", client_order_id, None, [reason])

    def confirm_not_placed(self, adapter: BrokerAdapter, client_order_id: str, account_scope: Optional[str] = None):
        """Explicit human/ops confirmation that the uncertain order never reached the broker."""
        self.risk.clear_reconciliation(account_scope or adapter.account_id)
        self._audit("confirmed_not_placed", cid=client_order_id)
