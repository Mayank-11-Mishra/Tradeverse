"""Broker-aware historical candle fetching with conservative pagination.
Brokers impose different maximum lookback periods per request. We never synthesize missing bars.
"""
from __future__ import annotations
import asyncio
from datetime import datetime,timedelta
from app.brokers.base import UnsupportedCapability


def window_days(broker_id:str,interval:str)->int:
    if broker_id=='groww':
        return 28 if interval in ('1m','2m','3m','5m') else (85 if interval in ('10m','15m','30m') else 170)
    if broker_id=='upstox':
        if interval.endswith('m'):
            n=int(interval[:-1])
            return 28 if n<=15 else 85
        return 85 if interval.endswith('h') else 3650
    if broker_id=='zerodha':
        return 30 if interval.endswith('m') else 180
    if broker_id=='fyers':return 30 if interval.endswith('m') else 180
    return 7 if interval.endswith('m') else 45


async def fetch_history(adapter,key,interval,start:datetime,end:datetime,*,max_batches:int=100):
    if start>=end:raise ValueError('start must precede end')
    days=window_days(adapter.broker_id,interval)
    end_of_window=start+timedelta(days=days)
    out={}
    batches=0
    cursor=start
    while cursor<end:
        next_end=min(cursor+timedelta(days=days),end)
        batches+=1
        if batches>max_batches:
            raise UnsupportedCapability(f'History range requires more than {max_batches} broker requests. Select a shorter date range.')
        bars=await adapter.get_historical_data(key,interval,cursor,next_end)
        for b in bars:out[b.ts]=b
        cursor=next_end
        if cursor<end:await asyncio.sleep(.2) # conservative request pacing
    return sorted(out.values(),key=lambda b:b.ts)


def uncovered_ranges(start:datetime,end:datetime,covered:list[tuple[datetime,datetime]]):
    """Subtract previously fetched half-open ranges from a requested window."""
    gaps=[(start,end)]
    for a,b in sorted(covered):
        remaining=[]
        for left,right in gaps:
            if b<=left or a>=right:
                remaining.append((left,right))
            else:
                if left<a:remaining.append((left,min(a,right)))
                if b<right:remaining.append((max(b,left),right))
        gaps=remaining
    return [(a,b) for a,b in gaps if a<b]


async def sync_history(adapter,account,key,interval,start:datetime,end:datetime,store,*,force:bool=False,max_batches:int=240):
    """Persist each broker-sized page, resume interrupted downloads, skip covered history.

    Avoid loading years of intraday bars into server memory and do not re-download
    completed windows on every chart refresh. Today's bars are always eligible for refresh.
    """
    if start>=end:raise ValueError('start must precede end')
    gap_ranges=uncovered_ranges(start,end,[] if force else store.history_coverage(account,key,interval,start,end))
    step=timedelta(days=window_days(adapter.broker_id,interval))
    count=0
    today=datetime.now(end.tzinfo).date()
    for left,right in gap_ranges:
        cursor=left
        while cursor<right:
            batch_end=min(cursor+step,right)
            count+=1
            if count>max_batches:
                raise UnsupportedCapability(f'History request exceeds {max_batches} API pages; choose a shorter range or load older pages.')
            rows=await adapter.get_historical_data(key,interval,cursor,batch_end)
            store.save_candles(account,key,interval,rows)
            # Do not freeze mutable current-session history.
            if batch_end.date()<today:
                store.mark_history_coverage(account,key,interval,cursor,batch_end)
            cursor=batch_end
            if cursor<right:await asyncio.sleep(.2)
    return count
