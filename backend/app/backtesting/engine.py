"""Event-driven bar backtester.

Execution assumptions (all explicit, none hidden):
  * A signal generated on bar i (after its close) is filled at the OPEN of bar i+1.
  * Slippage is applied adversely in basis points on market/stop fills.
  * Stop-loss / take-profit are checked against bar high/low. If both could trigger in
    the same bar the STOP is assumed to hit first (conservative).
  * A gap through a stop fills at the open (worse than the stop); a gap through a
    target fills at the open (better than the target).
  * Trailing stop levels update from a bar's extreme only for FOLLOWING bars.
  * Orders whose notional exceeds equity * max_leverage are rejected and recorded.
  * Only the data provided is used. No ticks, depth or option history is invented.

Charge defaults are ILLUSTRATIVE (typical NSE equity-intraday style). Exchange, STT and
stamp-duty rates change; set them from the current schedule for your segment before
trusting net P&L.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from app.indicators.engine import compute_indicator


@dataclass
class ChargeModel:
    brokerage_flat: float = 20.0          # cap per order
    brokerage_pct: float = 0.0003         # fraction of turnover; brokerage = min(flat, pct*turnover)
    stt_sell_pct: float = 0.00025
    stt_buy_pct: float = 0.0
    exch_txn_pct: float = 0.0000297
    sebi_pct: float = 0.000001
    stamp_buy_pct: float = 0.00003
    gst_pct: float = 0.18                 # on brokerage + exchange txn + sebi

    def charges(self, side: str, price: float, qty: float) -> float:
        t = abs(price * qty)
        brokerage = min(self.brokerage_flat, self.brokerage_pct * t) if self.brokerage_pct > 0 else self.brokerage_flat
        stt = t * (self.stt_sell_pct if side == "SELL" else self.stt_buy_pct)
        exch = t * self.exch_txn_pct
        sebi = t * self.sebi_pct
        stamp = t * self.stamp_buy_pct if side == "BUY" else 0.0
        gst = (brokerage + exch + sebi) * self.gst_pct
        return brokerage + stt + exch + sebi + stamp + gst

    @classmethod
    def zero(cls) -> "ChargeModel":
        return cls(0, 0, 0, 0, 0, 0, 0, 0)


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    slippage_bps: float = 1.0
    max_leverage: float = 5.0
    allow_short: bool = True
    squareoff_time: Optional[dtime] = None   # e.g. time(15, 15): flatten & block entries after
    charges: ChargeModel = field(default_factory=ChargeModel)


@dataclass
class Trade:
    entry_time: Any
    exit_time: Any
    side: str
    qty: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    charges: float
    net_pnl: float
    exit_reason: str


@dataclass
class _Pending:
    side: str
    qty: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    sl_pct: Optional[float] = None
    tp_pct: Optional[float] = None
    trail_pct: Optional[float] = None


class Strategy:
    """Subclass and implement on_bar(ctx). Optionally declare indicators in init(ctx)."""
    name = "strategy"

    def __init__(self, **params):
        self.params = params

    def init(self, ctx: "Context") -> None:
        pass

    def on_bar(self, ctx: "Context") -> None:
        raise NotImplementedError


class Context:
    def __init__(self, data: pd.DataFrame):
        self._data = data
        self.i = -1
        self.position = 0.0
        self.avg_price = 0.0
        self.equity = 0.0
        self._pending: list[_Pending] = []
        self._cache: dict = {}
        self.entries_blocked = False

    # --- data access (never exposes bars after the current one)
    @property
    def time(self):
        return self._data.index[self.i]

    @property
    def bar(self) -> pd.Series:
        return self._data.iloc[self.i]

    def history(self, n: Optional[int] = None) -> pd.DataFrame:
        d = self._data.iloc[: self.i + 1]
        return d if n is None else d.iloc[-n:]

    def ind(self, name: str, col: Optional[str] = None, shift: int = 0, **params) -> float:
        """Value of an indicator at the current bar (shift=1 -> previous bar).
        Indicators are precomputed once; they are causal so this has no look-ahead."""
        key = (name, tuple(sorted(params.items())))
        if key not in self._cache:
            self._cache[key] = compute_indicator(name, self._data, **params)
        frame = self._cache[key]
        col = col or frame.columns[0]
        j = self.i - shift
        return float(frame[col].iloc[j]) if j >= 0 else float("nan")

    # --- order intents (filled next bar open)
    def buy(self, qty: float, **kw):
        self._submit("BUY", qty, **kw)

    def sell(self, qty: float, **kw):
        self._submit("SELL", qty, **kw)

    def close(self):
        if self.position > 0:
            self._submit("SELL", self.position)
        elif self.position < 0:
            self._submit("BUY", -self.position)

    def _submit(self, side, qty, **kw):
        if qty <= 0:
            raise ValueError("qty must be positive")
        if self.entries_blocked and not self._reduces(side, qty):
            return
        self._pending.append(_Pending(side, float(qty), **kw))

    def _reduces(self, side, qty) -> bool:
        return (side == "SELL" and self.position > 0 and qty <= self.position) or \
               (side == "BUY" and self.position < 0 and qty <= -self.position)


@dataclass
class BacktestResult:
    trades: list
    equity: pd.Series
    metrics: dict
    rejected_orders: list
    config: BacktestConfig

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


class _Engine:
    def __init__(self, data: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig):
        self.d, self.s, self.cfg = data, strategy, cfg
        self.ctx = Context(data)
        self.cash = cfg.initial_capital
        self.pos = 0.0
        self.avg = 0.0
        self.entry_time = None
        self.entry_charges = 0.0       # charges paid on currently open qty
        self.sl = self.tp = None
        self.trail_pct = None
        self.trail_ref = None
        self.trades: list[Trade] = []
        self.rejected: list[dict] = []

    # ------------------------------------------------------------ fills
    def _slip(self, side, price):
        f = self.cfg.slippage_bps / 10_000
        return price * (1 + f) if side == "BUY" else price * (1 - f)

    def _equity(self, mark):
        return self.cash + self.pos * (mark - self.avg) if self.pos else self.cash

    def _fill(self, side, qty, price, t, reason, pend: Optional[_Pending] = None):
        cfg = self.cfg
        signed = qty if side == "BUY" else -qty
        # reduce / close portion
        if self.pos != 0 and (self.pos > 0) != (signed > 0):
            close_qty = min(abs(signed), abs(self.pos))
            frac = close_qty / abs(self.pos)
            exit_chg = cfg.charges.charges(side, price, close_qty)
            entry_alloc = self.entry_charges * frac
            gross = close_qty * (price - self.avg) * (1 if self.pos > 0 else -1)
            self.cash += gross - exit_chg
            self.trades.append(Trade(self.entry_time, t, "LONG" if self.pos > 0 else "SHORT", close_qty,
                                     self.avg, price, gross, entry_alloc + exit_chg,
                                     gross - entry_alloc - exit_chg, reason))
            self.entry_charges -= entry_alloc
            self.pos += close_qty if self.pos < 0 else -close_qty
            signed += close_qty if signed < 0 else -close_qty
            if abs(self.pos) < 1e-12:
                self._flat()
        # open / add remainder
        if abs(signed) > 1e-12:
            chg = cfg.charges.charges(side, price, abs(signed))
            self.cash -= chg
            if self.pos == 0:
                self.entry_time = t
                self.avg = price
                self.entry_charges = chg
            else:
                self.avg = (self.avg * abs(self.pos) + price * abs(signed)) / (abs(self.pos) + abs(signed))
                self.entry_charges += chg
            self.pos += signed
            if pend is not None:
                self._arm(pend, price)

    def _flat(self):
        self.pos, self.avg, self.entry_charges = 0.0, 0.0, 0.0
        self.sl = self.tp = self.trail_pct = self.trail_ref = None

    def _arm(self, p: _Pending, price):
        long = self.pos > 0
        sgn = 1 if long else -1
        if p.stop_loss is not None:
            self.sl = p.stop_loss
        elif p.sl_pct is not None:
            self.sl = price * (1 - sgn * p.sl_pct)
        if p.take_profit is not None:
            self.tp = p.take_profit
        elif p.tp_pct is not None:
            self.tp = price * (1 + sgn * p.tp_pct)
        if p.trail_pct is not None:
            self.trail_pct = p.trail_pct
            self.trail_ref = price
            trail_sl = price * (1 - sgn * p.trail_pct)
            self.sl = trail_sl if self.sl is None else (max(self.sl, trail_sl) if long else min(self.sl, trail_sl))

    # ------------------------------------------------------------ per-bar
    def _check_exits(self, o, h, l, t):
        if self.pos == 0:
            return
        long = self.pos > 0
        side = "SELL" if long else "BUY"
        qty = abs(self.pos)
        if self.sl is not None:
            hit = l <= self.sl if long else h >= self.sl
            if hit:
                px = min(self.sl, o) if long else max(self.sl, o)
                self._fill(side, qty, self._slip(side, px), t, "stop_loss")
                return
        if self.tp is not None:
            hit = h >= self.tp if long else l <= self.tp
            if hit:
                px = max(self.tp, o) if long else min(self.tp, o)
                self._fill(side, qty, px, t, "take_profit")
                return

    def _update_trail(self, h, l):
        if self.pos == 0 or self.trail_pct is None:
            return
        if self.pos > 0:
            self.trail_ref = max(self.trail_ref, h)
            self.sl = max(self.sl if self.sl is not None else -math.inf, self.trail_ref * (1 - self.trail_pct))
        else:
            self.trail_ref = min(self.trail_ref, l)
            self.sl = min(self.sl if self.sl is not None else math.inf, self.trail_ref * (1 + self.trail_pct))

    def run(self) -> BacktestResult:
        d, cfg, ctx = self.d, self.cfg, self.ctx
        O, H, L, C = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        times = d.index
        equity = np.empty(len(d))
        self.s.init(ctx)
        cur_day = None
        for i in range(len(d)):
            t = times[i]
            day = t.date() if hasattr(t, "date") else None
            if day != cur_day:
                cur_day, ctx.entries_blocked = day, False
            # 1. fill orders generated on the previous bar at this bar's open
            pending, ctx._pending = ctx._pending, []
            for p in pending:
                self._execute_pending(p, O[i], t)
            # 2. square-off
            if cfg.squareoff_time and hasattr(t, "time") and t.time() >= cfg.squareoff_time:
                if self.pos != 0:
                    side = "SELL" if self.pos > 0 else "BUY"
                    self._fill(side, abs(self.pos), self._slip(side, O[i]), t, "squareoff")
                ctx.entries_blocked = True
            # 3. intrabar stop / target
            self._check_exits(O[i], H[i], L[i], t)
            # 4. mark to market, then let the strategy see the closed bar
            equity[i] = self._equity(C[i])
            ctx.i, ctx.position, ctx.avg_price, ctx.equity = i, self.pos, self.avg, equity[i]
            if i < len(d) - 1:
                self.s.on_bar(ctx)
            self._update_trail(H[i], L[i])
        if self.pos != 0:
            side = "SELL" if self.pos > 0 else "BUY"
            self._fill(side, abs(self.pos), C[-1], times[-1], "end_of_data")
            equity[-1] = self._equity(C[-1])
        eq = pd.Series(equity, index=times, name="equity")
        return BacktestResult(self.trades, eq, compute_metrics(self.trades, eq, cfg.initial_capital),
                              self.rejected, cfg)

    def _execute_pending(self, p: _Pending, open_px, t):
        cfg = self.cfg
        if not cfg.allow_short and p.side == "SELL" and self.pos - p.qty < 0 and self.pos <= 0:
            self.rejected.append({"time": t, "reason": "short selling disabled", "order": p})
            return
        px = self._slip(p.side, open_px)
        signed = p.qty if p.side == "BUY" else -p.qty
        new_pos = self.pos + signed
        if abs(new_pos) > abs(self.pos):  # increases exposure -> leverage check
            equity = self._equity(open_px)
            if abs(new_pos) * px > max(equity, 0) * cfg.max_leverage:
                self.rejected.append({"time": t, "reason": "exceeds max_leverage", "order": p})
                return
        self._fill(p.side, p.qty, px, t, "signal", pend=p)


def run_backtest(data: pd.DataFrame, strategy: Strategy, config: Optional[BacktestConfig] = None) -> BacktestResult:
    for col in ("open", "high", "low", "close"):
        if col not in data.columns:
            raise ValueError(f"data missing column '{col}'")
    if not data.index.is_monotonic_increasing or data.index.has_duplicates:
        raise ValueError("data index must be strictly increasing with no duplicates")
    if "volume" not in data.columns:
        data = data.assign(volume=0.0)
    return _Engine(data, strategy, config or BacktestConfig()).run()


# ---------------------------------------------------------------- metrics
def _max_streak(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def compute_metrics(trades: list, equity: pd.Series, capital: float) -> dict:
    n = len(trades)
    pnls = np.array([t.net_pnl for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    net = float(equity.iloc[-1] - capital) if len(equity) else 0.0
    peak = equity.cummax()
    dd = equity - peak
    max_dd = float(dd.min()) if len(dd) else 0.0
    max_dd_pct = float((dd / peak).min() * 100) if len(dd) else 0.0
    daily = equity.resample("D").last().dropna() if isinstance(equity.index, pd.DatetimeIndex) else equity
    rets = daily.pct_change().dropna()
    sharpe = sortino = None
    if len(rets) > 1 and rets.std(ddof=1) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
        downside = rets[rets < 0]
        if len(downside) > 1 and downside.std(ddof=1) > 0:
            sortino = float(rets.mean() / math.sqrt((downside ** 2).mean()) * math.sqrt(252))
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    monthly = {}
    for t in trades:
        k = pd.Timestamp(t.exit_time).strftime("%Y-%m")
        monthly[k] = monthly.get(k, 0.0) + t.net_pnl
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    return {
        "net_profit": net,
        "return_pct": net / capital * 100,
        "total_trades": n,
        "winning_trades": int(len(wins)),
        "losing_trades": int(len(losses)),
        "win_rate_pct": (len(wins) / n * 100) if n else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "risk_reward": (avg_win / abs(avg_loss)) if avg_loss else None,
        "expectancy": float(pnls.mean()) if n else 0.0,
        "avg_trade_pnl": float(pnls.mean()) if n else 0.0,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_consecutive_wins": _max_streak(pnls > 0),
        "max_consecutive_losses": _max_streak(pnls < 0),
        "total_charges": float(sum(t.charges for t in trades)),
        "monthly_pnl": monthly,
    }


# ---------------------------------------------------------------- optimisation
def optimize(data: pd.DataFrame, strategy_cls, grid: dict, metric: str = "net_profit",
             config: Optional[BacktestConfig] = None, fixed: Optional[dict] = None) -> list:
    """Exhaustive grid search. Returns [(params, metrics)] sorted best-first.
    NOTE: in-sample optimisation overfits; validate on out-of-sample data."""
    keys = list(grid)
    out = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = {**(fixed or {}), **dict(zip(keys, combo))}
        res = run_backtest(data, strategy_cls(**params), config)
        v = res.metrics.get(metric)
        out.append((params, res.metrics, -math.inf if v is None else v))
    out.sort(key=lambda r: r[2], reverse=True)
    return [(p, m) for p, m, _ in out]
