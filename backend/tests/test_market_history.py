from datetime import datetime,timedelta,timezone
import asyncio
import pytest
from app.market_data.history import window_days,fetch_history
from app.brokers.base import Candle,InstrumentKey,UnsupportedCapability

class Fake:
    broker_id='groww'
    def __init__(self):self.requests=[]
    async def get_historical_data(self,key,interval,start,end):
        self.requests.append((start,end))
        return [Candle(start,100,101,99,100,100),Candle(end,100,101,99,100,200)]

def test_broker_history_windows():
    assert window_days('groww','1m')<=30
    assert window_days('upstox','1m')<=31
    assert window_days('upstox','30m')<=93

def test_history_pagination_deduplication():
    async def check():
        b=Fake();start=datetime(2026,1,1,tzinfo=timezone.utc)
        rows=await fetch_history(b,InstrumentKey('NSE','ABC'),'1m',start,start+timedelta(days=45))
        assert len(b.requests)==2
        assert len(rows)==3 # shared window boundary de-duplicated
    asyncio.run(check())

def test_history_prevents_excessive_requests():
    async def check():
        b=Fake();start=datetime(2026,1,1,tzinfo=timezone.utc)
        with pytest.raises(UnsupportedCapability):
            await fetch_history(b,InstrumentKey('NSE','ABC'),'1m',start,start+timedelta(days=90),max_batches=2)
    asyncio.run(check())
