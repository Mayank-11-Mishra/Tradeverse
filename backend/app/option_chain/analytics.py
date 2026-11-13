"""Option analytics: Black-Scholes(-Merton) pricing, Greeks, implied volatility,
chain statistics (PCR, max pain, OI buildup) and multi-leg payoff analysis.

Greeks computed here are CALCULATED ESTIMATES (European-style BSM). Indian index options
are European; single-stock options are now physically settled European as well, but any
model value is still an estimate: label it as such in the UI, and prefer broker-supplied
Greeks when the broker provides them.

Units: theta per calendar day, vega per 1 vol point (1%), rho per 1% rate move.
Rates/vol are decimals (0.07 = 7%).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from math import erf, exp, log, pi, sqrt
from typing import Callable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _npdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def time_to_expiry(now: datetime, expiry: date, expiry_time: time = time(15, 30)) -> float:
    """Years (365-day basis) from `now` (timezone-aware) to expiry at 15:30 IST. Floors at 0."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    exp_dt = datetime.combine(expiry, expiry_time, tzinfo=IST)
    return max((exp_dt - now).total_seconds(), 0.0) / (365.0 * 86400.0)


def _d1d2(S, K, T, r, sigma, q):
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    return d1, d1 - sigma * sqrt(T)


def bs_price(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    kind = kind.upper()
    if kind not in ("CE", "PE"):
        raise ValueError("kind must be CE or PE")
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if kind == "CE" else max(K - S, 0.0)
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    if kind == "CE":
        return S * exp(-q * T) * _ncdf(d1) - K * exp(-r * T) * _ncdf(d2)
    return K * exp(-r * T) * _ncdf(-d2) - S * exp(-q * T) * _ncdf(-d1)


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float   # per day
    vega: float    # per 1 vol point
    rho: float     # per 1% rate


def greeks(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> Greeks:
    kind = kind.upper()
    if T <= 0 or sigma <= 0:
        itm = (S > K) if kind == "CE" else (S < K)
        d = (1.0 if kind == "CE" else -1.0) if itm else 0.0
        return Greeks(d, 0.0, 0.0, 0.0, 0.0)
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    sq = sqrt(T)
    pdf = _npdf(d1)
    gamma = exp(-q * T) * pdf / (S * sigma * sq)
    vega = S * exp(-q * T) * pdf * sq / 100.0
    first = -(S * exp(-q * T) * pdf * sigma) / (2 * sq)
    if kind == "CE":
        delta = exp(-q * T) * _ncdf(d1)
        theta = first - r * K * exp(-r * T) * _ncdf(d2) + q * S * exp(-q * T) * _ncdf(d1)
        rho = K * T * exp(-r * T) * _ncdf(d2) / 100.0
    else:
        delta = -exp(-q * T) * _ncdf(-d1)
        theta = first + r * K * exp(-r * T) * _ncdf(-d2) - q * S * exp(-q * T) * _ncdf(-d1)
        rho = -K * T * exp(-r * T) * _ncdf(-d2) / 100.0
    return Greeks(delta, gamma, theta / 365.0, vega, rho)


def implied_vol(kind: str, price: float, S: float, K: float, T: float, r: float, q: float = 0.0,
                lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-8) -> Optional[float]:
    """Bisection IV. Returns None when no valid IV exists (price outside no-arbitrage bounds, T<=0)."""
    kind = kind.upper()
    if T <= 0 or price <= 0 or S <= 0 or K <= 0:
        return None
    if kind == "CE":
        intrinsic = max(S * exp(-q * T) - K * exp(-r * T), 0.0)
        upper = S * exp(-q * T)
    else:
        intrinsic = max(K * exp(-r * T) - S * exp(-q * T), 0.0)
        upper = K * exp(-r * T)
    if price < intrinsic - 1e-9 or price > upper:
        return None
    f_lo, f_hi = bs_price(kind, S, K, T, r, lo, q) - price, bs_price(kind, S, K, T, r, hi, q) - price
    if f_lo > 0 or f_hi < 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = bs_price(kind, S, K, T, r, mid, q) - price
        if abs(f) < tol or (hi - lo) < 1e-10:
            return mid
        if f > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ------------------------------------------------------------------ chain statistics
def pcr(put_oi: dict, call_oi: dict) -> Optional[float]:
    """Put/Call ratio by open interest across strikes. None if call OI is zero."""
    c, p = sum(call_oi.values()), sum(put_oi.values())
    return None if c == 0 else p / c


def max_pain(call_oi: dict, put_oi: dict) -> Optional[float]:
    """Strike minimising total intrinsic value payable to option buyers at expiry."""
    strikes = sorted(set(call_oi) | set(put_oi))
    if not strikes:
        return None
    best_k, best = None, None
    for k in strikes:
        pain = sum(oi * max(0.0, k - s) for s, oi in call_oi.items()) + \
               sum(oi * max(0.0, s - k) for s, oi in put_oi.items())
        if best is None or pain < best:
            best_k, best = k, pain
    return best_k


def oi_buildup(price_change: float, oi_change: float) -> str:
    if oi_change == 0 or price_change == 0:
        return "neutral"
    if oi_change > 0:
        return "long_buildup" if price_change > 0 else "short_buildup"
    return "short_covering" if price_change > 0 else "long_unwinding"


def moneyness(kind: str, strike: float, spot: float) -> str:
    if strike == spot:
        return "ATM"
    itm = strike < spot if kind.upper() == "CE" else strike > spot
    return "ITM" if itm else "OTM"


def atm_strike(spot: float, strikes: list) -> float:
    return min(strikes, key=lambda k: (abs(k - spot), k))


# ------------------------------------------------------------------ payoff analysis
@dataclass
class Leg:
    kind: str          # CE | PE | FUT
    strike: float      # for FUT: entry price
    premium: float     # for FUT: 0
    qty: float         # signed units (lots*lot_size); + long, - short

    def payoff(self, S: float) -> float:
        if self.kind == "CE":
            v = max(S - self.strike, 0.0) - self.premium
        elif self.kind == "PE":
            v = max(self.strike - S, 0.0) - self.premium
        elif self.kind == "FUT":
            v = S - self.strike
        else:
            raise ValueError(self.kind)
        return v * self.qty


def payoff_at(legs: list, S: float) -> float:
    return sum(l.payoff(S) for l in legs)


@dataclass
class PayoffSummary:
    breakevens: list
    max_profit: Optional[float]   # None => unlimited
    max_loss: Optional[float]     # None => unlimited (value is negative when finite)
    net_premium: float            # >0 debit paid, <0 credit received (per unit sum)
    upside_slope: float


def analyze_payoff(legs: list) -> PayoffSummary:
    """Exact analysis of piecewise-linear expiry payoff (no sampling error)."""
    if not legs:
        raise ValueError("no legs")
    ref = max([l.strike for l in legs])
    far = ref * 2 + 1
    pts = sorted({0.0, far, *[l.strike for l in legs]})
    vals = [payoff_at(legs, s) for s in pts]
    slope = sum(l.qty for l in legs if l.kind in ("CE", "FUT"))
    bes = []
    for (s0, v0), (s1, v1) in zip(zip(pts, vals), zip(pts[1:], vals[1:])):
        if v0 == 0:
            bes.append(s0)
        elif v0 * v1 < 0:
            bes.append(s0 + (0 - v0) * (s1 - s0) / (v1 - v0))
    if vals[-1] == 0 and slope == 0:
        bes.append(pts[-1])
    elif vals[-1] != 0 and slope != 0 and vals[-1] * slope < 0:
        bes.append(far - vals[-1] / slope)
    bes = sorted({round(b, 6) for b in bes})
    max_profit = None if slope > 0 else max(vals)
    max_loss = None if slope < 0 else min(vals)
    net = sum(l.premium * l.qty for l in legs)
    return PayoffSummary(bes, max_profit, max_loss, net, slope)


def payoff_curve(legs: list, lo: float, hi: float, points: int = 200) -> list:
    step = (hi - lo) / (points - 1)
    return [(lo + i * step, payoff_at(legs, lo + i * step)) for i in range(points)]


# ------------------------------------------------------------------ strategy templates
def build_template(name: str, atm: float, step: float, price: Callable[[str, float], float],
                   lot_size: int, lots: int = 1, width: int = 1) -> list:
    """price(kind, strike) -> premium. width = number of strike steps for wings/strangle."""
    q = lot_size * lots
    k = lambda n: atm + n * step
    L = lambda kind, strike, sign: Leg(kind, strike, price(kind, strike), sign * q)
    t = {
        "long_call": lambda: [L("CE", atm, +1)],
        "long_put": lambda: [L("PE", atm, +1)],
        "short_call": lambda: [L("CE", atm, -1)],
        "short_put": lambda: [L("PE", atm, -1)],
        "bull_call_spread": lambda: [L("CE", atm, +1), L("CE", k(width), -1)],
        "bear_put_spread": lambda: [L("PE", atm, +1), L("PE", k(-width), -1)],
        "long_straddle": lambda: [L("CE", atm, +1), L("PE", atm, +1)],
        "short_straddle": lambda: [L("CE", atm, -1), L("PE", atm, -1)],
        "long_strangle": lambda: [L("CE", k(width), +1), L("PE", k(-width), +1)],
        "short_strangle": lambda: [L("CE", k(width), -1), L("PE", k(-width), -1)],
        "iron_condor": lambda: [L("PE", k(-2 * width), +1), L("PE", k(-width), -1),
                                L("CE", k(width), -1), L("CE", k(2 * width), +1)],
        "long_butterfly": lambda: [L("CE", k(-width), +1), L("CE", atm, -2), L("CE", k(width), +1)],
    }
    if name not in t:
        raise KeyError(f"unknown template {name}; available: {sorted(t)}")
    return t[name]()
