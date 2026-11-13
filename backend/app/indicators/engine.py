"""Shared indicator engine.

One implementation is used by charts, backtests and live strategies so signals match.
All indicators here are causal: value at bar i depends only on bars <= i
(verified by tests/test_indicators.py::test_causality).

Input: DataFrame with columns open, high, low, close, volume and a DatetimeIndex.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- primitives
def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    """EMA seeded with the SMA of the first n values (standard charting convention)."""
    x = s.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) == 0 or valid[0] + n > len(x):
        return pd.Series(out, index=s.index)
    first = valid[0]
    start = first + n - 1
    k = 2.0 / (n + 1)
    out[start] = x[first:first + n].mean()
    for i in range(start + 1, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return pd.Series(out, index=s.index)


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing seeded with the SMA of the first n valid values."""
    x = s.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) == 0 or valid[0] + n > len(x):
        return pd.Series(out, index=s.index)
    first = valid[0]
    start = first + n - 1
    out[start] = x[first:first + n].mean()
    for i in range(start + 1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return pd.Series(out, index=s.index)


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def vwma(df: pd.DataFrame, n: int) -> pd.Series:
    pv = (df["close"] * df["volume"]).rolling(n).sum()
    v = df["volume"].rolling(n).sum()
    return pv / v.replace(0, np.nan)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)


# ---------------------------------------------------------------- indicators
def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    ag = rma(d.clip(lower=0), n)
    al = rma((-d).clip(lower=0), n)
    out = 100 - 100 / (1 + ag / al)
    out = out.where(al != 0, np.where(ag == 0, 50.0, 100.0))
    return out.where(ag.notna() & al.notna())


def macd(close: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bbands(close: pd.Series, n=20, mult=2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + mult * sd, "lower": mid - mult * sd})


def stoch(df: pd.DataFrame, k=14, d=3, smooth=1) -> pd.DataFrame:
    ll = df["low"].rolling(k).min()
    hh = df["high"].rolling(k).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    kk = sma(raw, smooth) if smooth > 1 else raw
    return pd.DataFrame({"k": kk, "d": sma(kk, d)})


def stochrsi(close: pd.Series, rsi_n=14, stoch_n=14, k=3, d=3) -> pd.DataFrame:
    r = rsi(close, rsi_n)
    ll = r.rolling(stoch_n).min()
    hh = r.rolling(stoch_n).max()
    raw = 100 * (r - ll) / (hh - ll).replace(0, np.nan)
    kk = sma(raw, k)
    return pd.DataFrame({"k": kk, "d": sma(kk, d)})


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = true_range(df)
    for s in (pdm, mdm, tr):
        s.iloc[0] = np.nan
    str_ = rma(tr, n)
    pdi = 100 * rma(pdm, n) / str_
    mdi = 100 * rma(mdm, n) / str_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"plus_di": pdi, "minus_di": mdi, "adx": rma(dx, n)})


def supertrend(df: pd.DataFrame, period=10, mult=3.0) -> pd.DataFrame:
    """direction: +1 uptrend (line = lower band), -1 downtrend (line = upper band)."""
    a = atr(df, period).to_numpy()
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a
    n = len(df)
    fub = np.full(n, np.nan)
    flb = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    line = np.full(n, np.nan)
    valid = np.flatnonzero(~np.isnan(a))
    if len(valid):
        s = valid[0]
        fub[s], flb[s], direction[s] = ub[s], lb[s], 1.0
        line[s] = flb[s]
        for i in range(s + 1, n):
            fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
            flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
            if direction[i - 1] == -1:
                direction[i] = 1.0 if c[i] > fub[i] else -1.0
            else:
                direction[i] = -1.0 if c[i] < flb[i] else 1.0
            line[i] = flb[i] if direction[i] == 1 else fub[i]
    return pd.DataFrame({"supertrend": line, "direction": direction}, index=df.index)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def cci(df: pd.DataFrame, n=20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    m = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - m) / (0.015 * md.replace(0, np.nan))


def mfi(df: pd.DataFrame, n=14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    raw = tp * df["volume"]
    d = tp.diff()
    pos = raw.where(d > 0, 0.0).rolling(n).sum()
    neg = raw.where(d < 0, 0.0).rolling(n).sum()
    out = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    out = out.where(neg != 0, 100.0)
    return out.where(d.rolling(n).count() == n)


def psar(df: pd.DataFrame, step=0.02, max_step=0.2) -> pd.Series:
    h, l = df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float)
    n = len(df)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=df.index)
    bull, af, ep = True, step, h[0]
    out[0] = l[0]
    for i in range(1, n):
        s = out[i - 1] + af * (ep - out[i - 1])
        if bull:
            s = min(s, l[i - 1], l[i - 2] if i >= 2 else l[i - 1])
            if l[i] < s:
                bull, s, ep, af = False, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, max_step)
        else:
            s = max(s, h[i - 1], h[i - 2] if i >= 2 else h[i - 1])
            if h[i] > s:
                bull, s, ep, af = True, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, max_step)
        out[i] = s
    return pd.Series(out, index=df.index)


def donchian(df: pd.DataFrame, n=20) -> pd.DataFrame:
    up, lo = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return pd.DataFrame({"upper": up, "lower": lo, "mid": (up + lo) / 2})


def keltner(df: pd.DataFrame, n=20, atr_n=10, mult=2.0) -> pd.DataFrame:
    mid = ema(df["close"], n)
    a = atr(df, atr_n)
    return pd.DataFrame({"mid": mid, "upper": mid + mult * a, "lower": mid - mult * a})


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP, reset each calendar day. NaN where cumulative volume is 0 (e.g. indices)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    cum_pv = (tp * df["volume"]).groupby(day).cumsum()
    cum_v = df["volume"].groupby(day).cumsum()
    return cum_pv / cum_v.replace(0, np.nan)


def ichimoku(df: pd.DataFrame, tenkan=9, kijun=26, senkou_b=52, displacement=26) -> pd.DataFrame:
    """Cloud lines as plotted at bar i (already displaced forward, so causal).
    The lagging span (chikou) is excluded: it looks ahead and is for display only."""
    def mid(n):
        return (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2
    t, k = mid(tenkan), mid(kijun)
    return pd.DataFrame({
        "tenkan": t, "kijun": k,
        "senkou_a": ((t + k) / 2).shift(displacement),
        "senkou_b": mid(senkou_b).shift(displacement),
    })


def pivot_points(daily: pd.DataFrame) -> pd.DataFrame:
    """Classic pivots for each day computed from the PREVIOUS day's H/L/C."""
    h, l, c = daily["high"].shift(1), daily["low"].shift(1), daily["close"].shift(1)
    p = (h + l + c) / 3
    return pd.DataFrame({
        "pivot": p, "r1": 2 * p - l, "s1": 2 * p - h,
        "r2": p + (h - l), "s2": p - (h - l),
        "r3": h + 2 * (p - l), "s3": l - 2 * (h - p),
    })


# ---------------------------------------------------------------- registry
def _one(name, s):
    return pd.DataFrame({name: s})


REGISTRY = {
    "sma": (lambda df, length=20: _one("sma", sma(df["close"], length)), {"length": 20}),
    "ema": (lambda df, length=20: _one("ema", ema(df["close"], length)), {"length": 20}),
    "wma": (lambda df, length=20: _one("wma", wma(df["close"], length)), {"length": 20}),
    "vwma": (lambda df, length=20: _one("vwma", vwma(df, length)), {"length": 20}),
    "vwap": (lambda df: _one("vwap", vwap(df)), {}),
    "rsi": (lambda df, length=14: _one("rsi", rsi(df["close"], length)), {"length": 14}),
    "macd": (lambda df, fast=12, slow=26, signal=9: macd(df["close"], fast, slow, signal),
             {"fast": 12, "slow": 26, "signal": 9}),
    "bbands": (lambda df, length=20, mult=2.0: bbands(df["close"], length, mult),
               {"length": 20, "mult": 2.0}),
    "atr": (lambda df, length=14: _one("atr", atr(df, length)), {"length": 14}),
    "supertrend": (lambda df, period=10, mult=3.0: supertrend(df, period, mult),
                   {"period": 10, "mult": 3.0}),
    "adx": (lambda df, length=14: adx(df, length), {"length": 14}),
    "stoch": (lambda df, k=14, d=3, smooth=1: stoch(df, k, d, smooth), {"k": 14, "d": 3, "smooth": 1}),
    "stochrsi": (lambda df, rsi_n=14, stoch_n=14, k=3, d=3: stochrsi(df["close"], rsi_n, stoch_n, k, d),
                 {"rsi_n": 14, "stoch_n": 14, "k": 3, "d": 3}),
    "ichimoku": (lambda df, tenkan=9, kijun=26, senkou_b=52: ichimoku(df, tenkan, kijun, senkou_b),
                 {"tenkan": 9, "kijun": 26, "senkou_b": 52}),
    "obv": (lambda df: _one("obv", obv(df)), {}),
    "cci": (lambda df, length=20: _one("cci", cci(df, length)), {"length": 20}),
    "mfi": (lambda df, length=14: _one("mfi", mfi(df, length)), {"length": 14}),
    "psar": (lambda df, step=0.02, max_step=0.2: _one("psar", psar(df, step, max_step)),
             {"step": 0.02, "max_step": 0.2}),
    "donchian": (lambda df, length=20: donchian(df, length), {"length": 20}),
    "keltner": (lambda df, length=20, atr_n=10, mult=2.0: keltner(df, length, atr_n, mult),
                {"length": 20, "atr_n": 10, "mult": 2.0}),
    "ma_ribbon": (lambda df, start=10, step=5, count=8: pd.DataFrame(
        {f"ema{start + i * step}": ema(df["close"], start + i * step) for i in range(count)}),
        {"start": 10, "step": 5, "count": 8}),
}


from .extended import EXTENDED
REGISTRY.update(EXTENDED)

def compute_indicator(name: str, df: pd.DataFrame, **params) -> pd.DataFrame:
    if name not in REGISTRY:
        raise KeyError(f"Unknown indicator '{name}'. Available: {sorted(REGISTRY)}")
    fn, defaults = REGISTRY[name]
    unknown = set(params) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown params for {name}: {sorted(unknown)}")
    values={**defaults, **params}
    for param, value in values.items():
        if param in ('length','period','fast','slow','signal','k','d','smooth','short','medium','long','rsi_n','stoch_n','tenkan','kijun','senkou_b','atr_n','start','count') and (not isinstance(value,int) or value < 1):
            raise ValueError(f'{param} must be a positive integer')
    return fn(df, **values)


def crossed_above(a: pd.Series, b) -> pd.Series:
    b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossed_below(a: pd.Series, b) -> pd.Series:
    b = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))
