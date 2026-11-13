"""Older history, API pagination, persistent coverage and upsert regression tests.
No real brokerage credentials or orders are used.
"""
from __future__ import annotations
import asyncio
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from sqlalchemy import delete
from app.database import store
from app.brokers.base import InstrumentKey,Candle
from app.market_data.history import sync_history,uncovered_ranges
from app.api import server

START=datetime(2025,1,1,tzinfo=timezone.utc)
KEY=InstrumentKey('NSE','HISTORY_TEST','IDX')

class FakeBroker:
    broker_id='upstox'
    def __init__(self):self.requests=[]
    async def get_historical_data(self,key,interval,start,end):
        self.requests.append((start,end))
        return [Candle(start,100,105,99,104,100),Candle(end,105,110,104,109,150)]


def test_uncovered_intervals_preserve_gaps_and_edges():
    a=START;b=a+timedelta(days=60)
    assert uncovered_ranges(a,b,[(a+timedelta(days=5),a+timedelta(days=25)),
                                 (a+timedelta(days=28),a+timedelta(days=50))])==[
        (a,a+timedelta(days=5)),
        (a+timedelta(days=25),a+timedelta(days=28)),
        (a+timedelta(days=50),b)]


def test_completed_historical_windows_are_cached_and_older_periods_remain_fetchable():
    store.init_db()
    account='upstox:deep-'+uuid4().hex[:10]
    broker=FakeBroker()
    end=START+timedelta(days=70)
    earlier=START-timedelta(days=90)
    try:
        n=asyncio.run(sync_history(broker,account,KEY,'15m',START,end,store))
        assert n==3
        assert len(broker.requests)==3
        assert len(store.load_candles(account,KEY,'15m',START,end,100))>0
        # Re-query completed range: no more requests; history is still accessible.
        assert asyncio.run(sync_history(broker,account,KEY,'15m',START,end,store))==0
        assert len(broker.requests)==3
        # Scroll back beyond the default viewport.
        n=asyncio.run(sync_history(broker,account,KEY,'15m',earlier,START,store))
        assert n==4
        assert len(store.load_candles(account,KEY,'15m',earlier,end,100))>=7
    finally:
        with store.Session.begin() as session:
            session.execute(delete(store.StoredCandle).where(store.StoredCandle.account==account))
            session.execute(delete(store.StoredHistoryCoverage).where(store.StoredHistoryCoverage.account==account))


def test_duplicate_bars_update_in_place_not_duplicate():
    store.init_db()
    account='upstox:merge-'+uuid4().hex[:10]
    try:
        a=Candle(START,100,105,99,102,100)
        b=Candle(START,100,110,98,108,200)
        store.save_candles(account,KEY,'1m',[a])
        store.save_candles(account,KEY,'1m',[b])
        bars=store.load_candles(account,KEY,'1m',START,START+timedelta(days=1))
        assert len(bars)==1
        assert bars[0].close==108 and bars[0].volume==200
    finally:
        with store.Session.begin() as session:
            session.execute(delete(store.StoredCandle).where(store.StoredCandle.account==account))
