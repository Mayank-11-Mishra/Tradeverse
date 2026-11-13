"""Tests for actual full-history backfill, independent of a real broker account."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.brokers.base import Candle, Capability, InstrumentKey
from app.market_data import backfill
from app.api import server

KEY = InstrumentKey('NSE', 'HISTORY_AUTOFETCH', 'EQ')

class FakeStore:
    def __init__(self):
        self.candles = {}
        self.covered = set()
    def oldest_candle(self, account, key, interval):
        if not self.candles:return None
        return min(self.candles).isoformat()
    def save_candles(self, account, key, interval, bars):
        for bar in bars:self.candles[bar.ts] = bar
    def history_coverage(self, account, key, interval, start, end):
        return [(a,b) for a,b in self.covered if a<end and b>start]
    def mark_history_coverage(self, account, key, interval, start, end):
        self.covered.add((start,end))

class FakeBroker:
    broker_id = 'upstox'
    def __init__(self):self.calls=[]
    async def get_historical_data(self, key, interval, start, end):
        self.calls.append((start,end))
        return [Candle(start,100,101,99,100,100)]
    def supports(self, capability):return capability==Capability.HISTORICAL_CANDLES


def test_oldest_policy_no_longer_six_months(monkeypatch):
    date=datetime(2026,11,13,tzinfo=timezone.utc)
    assert backfill.earliest_api_date('upstox','1m',date).year == 2022
    assert backfill.earliest_api_date('upstox','1d',date).year == 2000
    assert backfill.earliest_api_date('groww','1m',date).year == 2020
    monkeypatch.setenv('HISTORY_EARLIEST_UPSTOX_INTRADAY','2021-01-01')
    assert backfill.earliest_api_date('upstox','1m',date).year == 2021


def test_resumable_full_history_runs_without_blocking_chart(monkeypatch):
    async def go():
        data=FakeStore();broker=FakeBroker();session={'upstox:fake':broker}
        manager=backfill.BackfillManager(session,data)
        monkeypatch.setattr(backfill, 'earliest_api_date', lambda broker,interval:datetime.now(backfill.IST).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=55))
        state=manager.start('upstox:fake',KEY,'1m')
        assert state['status']=='queued'
        await manager.jobs[manager.key('upstox:fake',KEY,'1m')]._task
        status=manager.status('upstox:fake',KEY,'1m')
        assert status['status']=='complete'
        assert status['pages_scanned']==2
        assert len(data.candles)==2
        assert status['oldest_cached'] is not None
        n=len(broker.calls)
        # Second run must use recorded coverage and not refetch the old pages.
        manager.start('upstox:fake',KEY,'1m')
        await manager.jobs[manager.key('upstox:fake',KEY,'1m')]._task
        assert len(broker.calls)<=n+1  # current boundary may be mutable
    asyncio.run(go())


def test_before_cursor_selects_older_cached_candles(monkeypatch):
    # Avoid external account validation and verify correct before/limit forwarding.
    seen=[]
    class Adapter:pass
    server.SESSIONS['history:cursor']=Adapter()
    monkeypatch.setattr(server.store,'load_candles',lambda account,key,interval,start,end,limit: seen.append((start,end,limit)) or [])
    try:
        date='2023-05-09T09:15:00+05:30'
        assert asyncio.run(server.history('history:cursor','NSE','ABC','EQ','15m',before=date,limit=200))==[]
        assert seen[0][0] is None and seen[0][1] < datetime.fromisoformat(date)
        assert seen[0][2]==200
    finally:server.SESSIONS.pop('history:cursor',None)
