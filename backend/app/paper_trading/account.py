"""Paper trading account driven by live (or replayed) broker ticks.

Fills are simulated only from observed prices: MARKET fills at the best available
price (ask for buys / bid for sells when present, else LTP) plus slippage; LIMIT fills when
the market trades through the limit, at the limit price (no price improvement is assumed);
SL_M triggers when LTP crosses the trigger, then fills as market. Orders are all-or-nothing
(no partial fills are simulated). Idempotent on client_order_id.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.backtesting.engine import ChargeModel


@dataclass
class PaperOrder:
    order_id: str
    symbol: str
    side: str
    qty: int
    order_type: str
    price: Optional[float]
    trigger: Optional[float]
    status: str = "OPEN"            # OPEN | COMPLETE | CANCELLED | REJECTED
    fill_price: float = 0.0
    client_order_id: str = ""
    message: str = ""
    triggered: bool = False


@dataclass
class PaperFill:
    ts: Optional[datetime]
    order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    charges: float
    realized_pnl: float


class PaperAccount:
    mode = "paper"

    def __init__(self, balance: float = 1_000_000.0, slippage_bps: float = 0.0,
                 charges: Optional[ChargeModel] = None, allow_short: bool = True):
        self.initial = balance
        self.cash = balance
        self.slippage_bps = slippage_bps
        self.charges = charges or ChargeModel()
        self.allow_short = allow_short
        self.orders: dict = {}
        self.fills: list = []
        self.positions: dict = {}      # symbol -> [qty, avg]
        self.last: dict = {}           # symbol -> (ltp, bid, ask)
        self.realized = 0.0
        self._ids = itertools.count(1)
        self._by_cid: dict = {}

    # ------------------------------------------------------------ orders
    def place_order(self, symbol, side, qty, order_type="MARKET", price=None, trigger=None,
                    client_order_id="", ts=None) -> PaperOrder:
        if client_order_id and client_order_id in self._by_cid:
            return self.orders[self._by_cid[client_order_id]]          # idempotent
        side, order_type = side.upper(), order_type.upper()
        oid = f"P{next(self._ids)}"
        o = PaperOrder(oid, symbol, side, int(qty), order_type, price, trigger, client_order_id=client_order_id)
        self.orders[oid] = o
        if client_order_id:
            self._by_cid[client_order_id] = oid
        err = None
        if side not in ('BUY','SELL'):
            err = 'side must be BUY or SELL'
        elif qty <= 0:
            err = "quantity must be positive"
        elif order_type == "LIMIT" and price is None:
            err = "limit order requires price"
        elif order_type in ("SL_M",) and trigger is None:
            err = "SL_M requires trigger"
        elif order_type not in ("MARKET", "LIMIT", "SL_M"):
            err = f"unsupported order type {order_type}"
        elif side == "SELL" and not self.allow_short and self.qty(symbol) < qty:
            err = "short selling disabled"
        if err:
            o.status, o.message = "REJECTED", err
            return o
        if symbol in self.last:
            self._try_fill(o, ts)
        return o

    def cancel_order(self, order_id: str) -> bool:
        o = self.orders[order_id]
        if o.status != "OPEN":
            return False
        o.status = "CANCELLED"
        return True

    def modify_order(self, order_id: str, price=None, trigger=None, qty=None) -> bool:
        o = self.orders[order_id]
        if o.status != "OPEN":
            return False
        if price is not None:
            if price <= 0: return False
            o.price = price
        if trigger is not None:
            o.trigger = trigger
        if qty is not None:
            if qty <= 0: return False
            o.qty = int(qty)
        return True

    # ------------------------------------------------------------ market data
    def on_tick(self, symbol, ltp, bid=None, ask=None, ts=None):
        self.last[symbol] = (ltp, bid, ask)
        for o in list(self.orders.values()):
            if o.status == "OPEN" and o.symbol == symbol:
                self._try_fill(o, ts)

    def _market_px(self, o: PaperOrder):
        ltp, bid, ask = self.last[o.symbol]
        base = (ask if (o.side == "BUY" and ask) else bid if (o.side == "SELL" and bid) else ltp)
        f = self.slippage_bps / 10_000
        return base * (1 + f) if o.side == "BUY" else base * (1 - f)

    def _try_fill(self, o: PaperOrder, ts):
        ltp = self.last[o.symbol][0]
        if o.order_type == "MARKET":
            self._execute(o, self._market_px(o), ts)
        elif o.order_type == "LIMIT":
            if (o.side == "BUY" and ltp <= o.price) or (o.side == "SELL" and ltp >= o.price):
                self._execute(o, o.price, ts)
        elif o.order_type == "SL_M":
            if not o.triggered and ((o.side == "SELL" and ltp <= o.trigger) or (o.side == "BUY" and ltp >= o.trigger)):
                o.triggered = True
            if o.triggered:
                self._execute(o, self._market_px(o), ts)

    def _execute(self, o: PaperOrder, px: float, ts):
        chg = self.charges.charges(o.side, px, o.qty)
        signed = o.qty if o.side == "BUY" else -o.qty
        qty, avg = self.positions.get(o.symbol, [0, 0.0])
        realized = 0.0
        if qty != 0 and (qty > 0) != (signed > 0):
            closing = min(abs(signed), abs(qty))
            realized = closing * (px - avg) * (1 if qty > 0 else -1)
        new_qty = qty + signed
        if qty == 0 or (qty > 0) == (signed > 0):
            avg = (avg * abs(qty) + px * abs(signed)) / abs(new_qty)
        elif abs(signed) > abs(qty):          # flipped through zero: remainder opens at fill price
            avg = px
        if new_qty == 0:
            self.positions.pop(o.symbol, None)
        else:
            self.positions[o.symbol] = [new_qty, avg]
        self.cash += realized - chg
        self.realized += realized - chg
        o.status, o.fill_price = "COMPLETE", px
        self.fills.append(PaperFill(ts, o.order_id, o.symbol, o.side, o.qty, px, chg, realized - chg))

    # ------------------------------------------------------------ views
    def qty(self, symbol) -> int:
        return self.positions.get(symbol, [0, 0.0])[0]

    def unrealized(self) -> float:
        total = 0.0
        for s, (q, avg) in self.positions.items():
            ltp = self.last.get(s, (avg,))[0]
            total += q * (ltp - avg)
        return total

    def equity(self) -> float:
        return self.cash + self.unrealized()

    def snapshot(self) -> dict:
        return {"mode": "paper", "cash": self.cash, "equity": self.equity(), "realized": self.realized,
                "unrealized": self.unrealized(),
                "positions": {s: {"qty": q, "avg": a} for s, (q, a) in self.positions.items()}}
