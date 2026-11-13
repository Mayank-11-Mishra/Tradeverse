"""Tick -> candle aggregation and historical/live stitching.

* Candle buckets are aligned to the exchange session open (default NSE 09:15 IST), e.g. a
  15m bar covers 09:15-09:30. Daily bars use the exchange calendar date.
* Duplicate and out-of-order ticks are dropped and counted (never silently merged).
* Volume per candle is derived from CUMULATIVE day volume deltas when the feed provides it.
* A bucket with no ticks produces NO candle (gaps are never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

from app.brokers.base import Candle, Tick

INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "45m": 45,
                    "1h": 60, "2h": 120, "4h": 240}


def bucket_start(ts: datetime, minutes: int, session_open: time = time(9, 15)) -> datetime:
    anchor = ts.replace(hour=session_open.hour, minute=session_open.minute, second=0, microsecond=0)
    if ts < anchor:                      # pre-open tick: belongs to the first bucket of the session
        return anchor
    elapsed = int((ts - anchor).total_seconds() // 60)
    return anchor + timedelta(minutes=(elapsed // minutes) * minutes)


class CandleBuilder:
    def __init__(self, interval: str = "1m", session_open: time = time(9, 15)):
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"unsupported interval {interval}")
        self.minutes = INTERVAL_MINUTES[interval]
        self.session_open = session_open
        self.current: Optional[Candle] = None
        self._last_ts: Optional[datetime] = None
        self._last_cum_vol: Optional[float] = None
        self.dropped_duplicates = 0
        self.dropped_out_of_order = 0

    def on_tick(self, t: Tick) -> list:
        """Returns candles closed by this tick (0 or 1). Current partial candle is `self.current`."""
        if self._last_ts is not None:
            if t.ts < self._last_ts:
                self.dropped_out_of_order += 1
                return []
            if t.ts == self._last_ts and t.ltp == (self.current.close if self.current else None) \
                    and t.volume == self._last_cum_vol:
                self.dropped_duplicates += 1
                return []
        self._last_ts = t.ts
        start = bucket_start(t.ts, self.minutes, self.session_open)
        vol_delta = 0.0
        if t.volume is not None:
            if self._last_cum_vol is not None and t.volume >= self._last_cum_vol:
                vol_delta = t.volume - self._last_cum_vol
            elif self._last_cum_vol is not None and t.volume < self._last_cum_vol:
                vol_delta = t.volume                   # new session: counter reset
            self._last_cum_vol = t.volume
        closed = []
        if self.current is not None and start != self.current.ts:
            closed.append(self.current)
            self.current = None
        if self.current is None:
            self.current = Candle(start, t.ltp, t.ltp, t.ltp, t.ltp, vol_delta, t.oi)
        else:
            c = self.current
            c.high, c.low, c.close = max(c.high, t.ltp), min(c.low, t.ltp), t.ltp
            c.volume += vol_delta
            if t.oi is not None:
                c.oi = t.oi
        return closed


def stitch(historical: list, live_closed: list, live_current: Optional[Candle] = None) -> list:
    """Merge historical candles with live ones: de-duplicate by timestamp (live wins since it is
    newer), keep ascending order, never create gaps. The still-forming candle is appended last."""
    by_ts = {c.ts: c for c in historical}
    for c in live_closed:
        by_ts[c.ts] = c
    if live_current is not None:
        by_ts[live_current.ts] = live_current
    return [by_ts[k] for k in sorted(by_ts)]


def resample_candles(candles: list, minutes: int, session_open: time = time(9, 15)) -> list:
    """Derive a coarser interval from finer official candles (e.g. 1m -> 45m). Only aggregates
    buckets that actually contain source candles. Partial first/last buckets are kept as they are
    and flagged by the caller if completeness matters."""
    if not candles:
        return []
    out: dict = {}
    for c in sorted(candles, key=lambda x: x.ts):
        b = bucket_start(c.ts, minutes, session_open)
        if b not in out:
            out[b] = Candle(b, c.open, c.high, c.low, c.close, c.volume, c.oi)
        else:
            o = out[b]
            o.high, o.low, o.close = max(o.high, c.high), min(o.low, c.low), c.close
            o.volume += c.volume
            o.oi = c.oi if c.oi is not None else o.oi
    return [out[k] for k in sorted(out)]


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha_open = ha_close.copy()
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
    out = df.copy()
    out["open"], out["close"] = ha_open, ha_close
    out["high"] = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    out["low"] = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)
    return out


def find_gaps(timestamps: list, minutes: int, session_open: time = time(9, 15),
              session_close: time = time(15, 30)) -> list:
    """Expected-but-missing intraday bucket starts within each session day spanned by the data.
    Does not know exchange holidays: callers must filter holidays/half-days."""
    if not timestamps:
        return []
    have = set(timestamps)
    days = sorted({t.date() for t in timestamps})
    tz = timestamps[0].tzinfo
    missing = []
    for d in days:
        cur = datetime.combine(d, session_open, tzinfo=tz)
        end = datetime.combine(d, session_close, tzinfo=tz)
        while cur < end:
            if cur not in have:
                missing.append(cur)
            cur += timedelta(minutes=minutes)
    return missing
