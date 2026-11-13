"""Central pre-trade risk engine. Every order (paper or live) passes through check().

Principles:
  * Live trading is OFF by default.
  * Kill switches and risk limits block NEW exposure but never block reduce-only exits.
  * Uncertain order state / lost auth blocks ALL orders on that account until reconciled.
  * A strategy is bound to exactly one (broker, account); any other target is rejected.
  * check() has no side effects; call record_submitted() once an order has been sent.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional


@dataclass
class RiskLimits:
    live_trading_enabled: bool = False
    max_order_qty: Optional[int] = None
    max_order_notional: Optional[float] = None
    max_daily_loss: Optional[float] = None            # positive number, per account
    max_daily_trades: Optional[int] = None            # per strategy
    max_open_positions: Optional[int] = None          # per account (distinct symbols)
    max_capital_allocation: Optional[float] = None    # per account, total open notional
    max_orders_per_second: int = 5                    # keep well below the 10 OPS regulatory threshold
    duplicate_window_sec: float = 5.0
    feed_stale_sec: float = 10.0
    trading_windows: Optional[list] = field(default_factory=lambda: [(time(9, 15), time(15, 25))])


@dataclass
class OrderIntent:
    broker_id: str
    account_id: str
    strategy_id: str
    symbol: str
    side: str
    qty: int
    price: float
    mode: str = "paper"        # paper | live
    is_exit: bool = False      # reduce-only


@dataclass
class RiskDecision:
    allowed: bool
    reasons: list = field(default_factory=list)


class RiskEngine:
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.global_kill = False
        self.killed_strategies: set = set()
        self._bindings: dict = {}                       # strategy_id -> (broker_id, account_id)
        self._reconcile: dict = {}                      # account_id -> reason
        self._positions: dict = {}                      # (account, symbol) -> (qty, avg_price)
        self._pnl: dict = defaultdict(float)            # (account, date) -> realized pnl
        self._trades: dict = defaultdict(int)           # (strategy, date) -> entries count
        self._recent: deque = deque()                   # (ts, account, strategy, symbol, side, qty)

    # ---------------------------------------------------------------- configuration / state
    def bind_strategy(self, strategy_id: str, broker_id: str, account_id: str):
        self._bindings[strategy_id] = (broker_id, account_id)

    def kill_all(self):
        self.global_kill = True

    def release_all(self):
        self.global_kill = False

    def kill_strategy(self, sid: str):
        self.killed_strategies.add(sid)

    def release_strategy(self, sid: str):
        self.killed_strategies.discard(sid)

    def require_reconciliation(self, account_id: str, reason: str):
        self._reconcile[account_id] = reason

    def clear_reconciliation(self, account_id: str):
        self._reconcile.pop(account_id, None)

    def needs_reconciliation(self, account_id: str) -> Optional[str]:
        return self._reconcile.get(account_id)

    def set_position(self, account_id: str, symbol: str, qty: int, avg_price: float = 0.0):
        if qty == 0:
            self._positions.pop((account_id, symbol), None)
        else:
            self._positions[(account_id, symbol)] = (qty, avg_price)

    def record_pnl(self, account_id: str, day: date, pnl: float):
        self._pnl[(account_id, day)] += pnl

    def daily_pnl(self, account_id: str, day: date) -> float:
        return self._pnl[(account_id, day)]

    def record_submitted(self, intent: OrderIntent, now: datetime):
        self._recent.append((now, intent.account_id, intent.strategy_id, intent.symbol, intent.side, intent.qty))
        if not intent.is_exit:
            self._trades[(intent.strategy_id, now.date())] += 1

    # ---------------------------------------------------------------- the check
    def check(self, o: OrderIntent, now: datetime, feed_age_sec: Optional[float] = None) -> RiskDecision:
        L, why = self.limits, []
        # An exit is not a user-controlled bypass flag: prove it reduces an existing position.
        position_qty = self._positions.get((o.account_id,o.symbol),(0,0.0))[0]
        reducing = ((o.side == 'SELL' and position_qty > 0 and o.qty <= position_qty) or
                    (o.side == 'BUY' and position_qty < 0 and o.qty <= abs(position_qty)))
        if o.is_exit and not reducing:
            why.append('reduce-only exit not validated against current position')
        entry = not (o.is_exit and reducing)

        if o.mode == "live" and not L.live_trading_enabled:
            why.append("live trading is disabled in settings")
        if o.qty <= 0:
            why.append("quantity must be positive")
        if o.side not in ('BUY','SELL'):
            why.append('side must be BUY or SELL')
        if o.mode not in ('live','paper'):
            why.append('mode must be paper or live')
        if (L.max_order_notional is not None or L.max_capital_allocation is not None or o.mode=='live') and o.price <= 0:
            why.append('valid reference price required for exposure checks')

        bound = self._bindings.get(o.strategy_id)
        if o.strategy_id and bound is not None and bound != (o.broker_id, o.account_id):
            why.append(f"strategy bound to {bound}, order targets {(o.broker_id, o.account_id)}")

        rec = self._reconcile.get(o.account_id)
        if rec:
            why.append(f"account requires reconciliation: {rec}")

        if entry:
            if self.global_kill:
                why.append("global kill switch active")
            if o.strategy_id in self.killed_strategies:
                why.append("strategy kill switch active")

        notional = abs(o.price * o.qty)
        if L.max_order_qty is not None and o.qty > L.max_order_qty:
            why.append(f"qty {o.qty} exceeds max_order_qty {L.max_order_qty}")
        if L.max_order_notional is not None and notional > L.max_order_notional:
            why.append(f"notional {notional:.2f} exceeds max_order_notional {L.max_order_notional}")

        if entry:
            if o.mode == "live" and feed_age_sec is None:
                why.append("market feed freshness unknown")
            elif feed_age_sec is not None and feed_age_sec > L.feed_stale_sec:
                why.append(f"market feed stale ({feed_age_sec:.1f}s > {L.feed_stale_sec}s)")
            if L.trading_windows is not None:
                t = now.time()
                if not any(a <= t <= b for a, b in L.trading_windows):
                    why.append("outside permitted trading window")
            if L.max_daily_loss is not None and self.daily_pnl(o.account_id, now.date()) <= -abs(L.max_daily_loss):
                why.append("max daily loss reached")
            if L.max_daily_trades is not None and self._trades[(o.strategy_id, now.date())] >= L.max_daily_trades:
                why.append("max daily trades reached")
            acct_pos = {s: v for (a, s), v in self._positions.items() if a == o.account_id}
            if L.max_open_positions is not None and o.symbol not in acct_pos and len(acct_pos) >= L.max_open_positions:
                why.append("max open positions reached")
            if L.max_capital_allocation is not None:
                open_notional = sum(abs(q * p) for q, p in acct_pos.values())
                if open_notional + notional > L.max_capital_allocation:
                    why.append("max capital allocation exceeded")

        # duplicate + rate (always)
        while self._recent and (now - self._recent[0][0]).total_seconds() > max(L.duplicate_window_sec, 1.0):
            self._recent.popleft()
        sig = (o.account_id, o.strategy_id, o.symbol, o.side, o.qty)
        if any((now - r[0]).total_seconds() <= L.duplicate_window_sec and r[1:] == sig for r in self._recent):
            why.append("duplicate order within window")
        if sum(1 for r in self._recent if (now - r[0]).total_seconds() <= 1.0) >= L.max_orders_per_second:
            why.append("order rate limit")

        return RiskDecision(not why, why)
