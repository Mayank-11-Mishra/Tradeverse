"""Connection-scoped live feeds and one-minute candle persistence.
Feeds are shared among live dashboard subscribers and active rule strategies.
"""
from __future__ import annotations
import asyncio,time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from app.brokers.base import InstrumentKey,Tick
from app.live_data.candles import CandleBuilder
from app.database import store
from app.paper_trading.account import PaperAccount

IST=ZoneInfo('Asia/Kolkata')

class MarketHub:
    def __init__(self,accounts):
        self.accounts=accounts     # account identifier -> active adapter
        self.tasks={}
        self.listeners=defaultdict(set)
        self.last={}
        self.builders={}
        self.papers={}
        self.on_candle=None
        self.errors={}
        self.group_tasks={}
        self.group_changed={}
        self.group_state={}
        self.debug=False
    def paper(self,account):
        if account not in self.papers:self.papers[account]=PaperAccount()
        return self.papers[account]
    @staticmethod
    def identity(account,key):return (account,key.exchange,key.symbol,key.segment)
    async def listen(self,account,key):
        identity=self.identity(account,key)
        queue=asyncio.Queue(maxsize=1000)
        self.listeners[identity].add(queue)
        self._ensure_group(account)
        return queue
    async def unlisten(self,account,key,queue):
        identity=self.identity(account,key)
        self.listeners[identity].discard(queue)
        if not self.listeners[identity]:
            self.listeners.pop(identity,None)
            # Stop unused stream unless active strategies still depend on it.
            if not self._has_active_strategy(account,key):
                self.group_changed.setdefault(account,asyncio.Event()).set()
    def _has_active_strategy(self,account,key):
        return any(x['active'] and x['account']==account and x['exchange']==key.exchange and x['symbol']==key.symbol
                   for x in store.strategies())
    async def ensure_strategy_feed(self,account,key):
        identity=self.identity(account,key)
        self._ensure_group(account)
    async def stop_account(self,account):
        group=self.group_tasks.pop(account,None)
        if group:
            group.cancel()
            await asyncio.gather(group,return_exceptions=True)
        self.group_state.pop(account,None)
        for ident,task in list(self.tasks.items()):
            if ident[0]==account:task.cancel();self.tasks.pop(ident,None)
        for ident in list(self.listeners):
            if ident[0]==account:
                for q in self.listeners.pop(ident):
                    with __import__('contextlib').suppress(Exception):q.put_nowait({'event':'disconnected'})
    def status(self):
        now=time.monotonic()
        output={}
        for account,state in self.group_state.items():
            last=state.get('last_tick')
            output[account]={**state,'age_seconds':round(now-last,1) if last else None}
        return output

    def _active_keys(self,account):
        keys={}
        for ident in self.listeners:
            if ident[0]==account:
                key=InstrumentKey(*ident[1:])
                keys[ident]=key
        for st in store.strategies():
            if st['active'] and st['account']==account:
                key=InstrumentKey(st['exchange'],st['symbol'],st['segment'])
                keys[self.identity(account,key)]=key
        return list(keys.values())

    def _ensure_group(self,account):
        self.group_changed.setdefault(account,asyncio.Event()).set()
        if account not in self.group_tasks or self.group_tasks[account].done():
            self.group_tasks[account]=asyncio.create_task(self._run_group(account))

    async def _dispatch_tick(self,account,raw):
        if not isinstance(raw,Tick):return
        key=raw.key
        ident=self.identity(account,key)
        tick=Tick(key,raw.ts.astimezone(IST),raw.ltp,raw.bid,raw.ask,raw.volume,raw.oi,raw.source,raw.previous_close)
        self.last[ident]=(tick,time.monotonic())
        self.group_state[account]={'state':'connected','last_tick':time.monotonic(),
                                   'subscribed':len(self._active_keys(account))}
        self.paper(account).on_tick(f'{key.exchange}:{key.symbol}',tick.ltp,tick.bid,tick.ask,tick.ts)
        builder=self.builders.setdefault(ident,CandleBuilder('1m'))
        closed=builder.on_tick(tick)
        await self._broadcast(ident,{'event':'tick','key':asdict(key),'data':asdict(tick)})
        if builder.current:
            await self._broadcast(ident,{'event':'candle','key':asdict(key),'partial':True,'interval':'1m','data':asdict(builder.current)})
        for c in closed:
            store.save_candles(account,key,'1m',[c])
            await self._broadcast(ident,{'event':'candle','key':asdict(key),'partial':False,'interval':'1m','data':asdict(c)})
            if self.on_candle:
                try:await self.on_candle(account,key,c,tick)
                except Exception as ex:store.log_event('strategy_error',account,{'error':type(ex).__name__})

    async def _stop_feed_strategies(self,account,reason):
        for item in store.strategies():
            if item['active'] and item['account']==account:
                store.change_strategy(item['id'],False)
                store.log_event('strategy_stopped',account,{'id':item['id'],'reason':reason})

    async def _run_group(self,account):
        """One upstream broker stream per account; change of subscriptions restarts and resubscribes.
        Strategies stop on a lost stream rather than trading against stale quotes.
        """
        delay=1
        try:
            while account in self.accounts:
                change=self.group_changed.setdefault(account,asyncio.Event())
                change.clear()
                keys=self._active_keys(account)
                if not keys:break
                adapter=self.accounts[account]
                valid=[]
                for key in keys:
                    # Never let one unmapped instrument break all subscriptions.
                    # Upstox needs instrument_key (not the display ticker).
                    try:
                        if getattr(adapter,'broker_id','')=='upstox':
                            try:
                                adapter.token_for(key)
                            except Exception:
                                matches=await adapter.get_instruments(query=key.symbol,exchange=key.exchange)
                                store.save_instruments(account,matches)
                                adapter.token_for(key)
                        valid.append(key)
                    except Exception as exc:
                        ident=self.identity(account,key)
                        reason=f'{key.exchange}:{key.symbol} subscription rejected: {type(exc).__name__}: {str(exc)[:140]}'
                        self.errors[ident]=reason
                        await self._broadcast(ident,{'event':'error','key':asdict(key),'message':reason})
                if not valid:
                    self.group_state[account]={'state':'disconnected','subscribed':0,
                                               'error':'No valid broker instrument subscriptions','last_tick':None}
                    try:await asyncio.wait_for(change.wait(),timeout=15)
                    except asyncio.TimeoutError:pass
                    continue
                self.group_state[account]={'state':'connecting','subscribed':len(valid),'last_tick':None}
                async def consume():
                    async for tick in adapter.subscribe_market_data(valid):
                        await self._dispatch_tick(account,tick)
                pump=asyncio.create_task(consume())
                changed=asyncio.create_task(change.wait())
                try:
                    done,_=await asyncio.wait((pump,changed),return_when=asyncio.FIRST_COMPLETED)
                    if changed in done:
                        pump.cancel();await asyncio.gather(pump,return_exceptions=True)
                        delay=1
                        continue
                    try:
                        await pump
                        reason='Broker market stream ended'
                    except Exception as ex:
                        reason=f'Broker stream stopped ({type(ex).__name__}): {str(ex)[:150]}'
                    self.group_state[account]={'state':'reconnecting','error':reason,'subscribed':len(keys),'last_tick':None}
                    for key in keys:
                        ident=self.identity(account,key)
                        self.errors[ident]=reason
                        await self._broadcast(ident,{'event':'error','message':reason})
                    await self._stop_feed_strategies(account,reason)
                    store.log_event('feed_error',account,{'reason':reason,'instruments':len(keys)})
                    try:await asyncio.wait_for(change.wait(),timeout=delay)
                    except asyncio.TimeoutError:pass
                    delay=min(delay*2,30)
                finally:
                    changed.cancel()
                    if not pump.done():pump.cancel()
                    await asyncio.gather(changed,pump,return_exceptions=True)
        except asyncio.CancelledError:
            raise
        finally:
            self.group_state[account]={'state':'disconnected','subscribed':0,'last_tick':None}

    def age(self,account,key):
        tick_info=self.last.get(self.identity(account,key))
        if not tick_info:return None
        tick,received=tick_info
        return max(time.monotonic()-received,max(0,(datetime.now(timezone.utc)-tick.ts.astimezone(timezone.utc)).total_seconds()))
    def latest_price(self,account,key):
        x=self.last.get(self.identity(account,key))
        return x[0].ltp if x else None
    async def _broadcast(self,ident,msg):
        for q in tuple(self.listeners.get(ident,())):
            if q.full():
                try:q.get_nowait()
                except asyncio.QueueEmpty:pass
            q.put_nowait(msg)
    async def _run(self,account,key):
        ident=self.identity(account,key)
        adapter=self.accounts.get(account)
        if adapter is None:return
        builder=self.builders.setdefault(ident,CandleBuilder('1m'))
        try:
            async for raw in adapter.subscribe_market_data([key]):
                if not isinstance(raw,Tick):continue
                tick=Tick(raw.key,raw.ts.astimezone(IST),raw.ltp,raw.bid,raw.ask,raw.volume,raw.oi,raw.source,raw.previous_close)
                self.last[ident]=(tick,time.monotonic())
                self.paper(account).on_tick(f'{key.exchange}:{key.symbol}',tick.ltp,tick.bid,tick.ask,tick.ts)
                closed=builder.on_tick(tick)
                await self._broadcast(ident,{'event':'tick','data':asdict(tick)})
                if builder.current:
                    await self._broadcast(ident,{'event':'candle','partial':True,'interval':'1m','data':asdict(builder.current)})
                for c in closed:
                    store.save_candles(account,key,'1m',[c])
                    await self._broadcast(ident,{'event':'candle','partial':False,'interval':'1m','data':asdict(c)})
                    if self.on_candle:
                        try:await self.on_candle(account,key,c,tick)
                        except Exception as e:store.log_event('strategy_error',account,{'error':type(e).__name__})
            # A stream that ends cleanly is still no longer usable for trading.
            # Do not leave active strategies attached to an exhausted generator.
            self.errors[ident]='feed_ended'
            store.log_event('feed_ended',account,{'symbol':key.symbol})
            for item in store.strategies():
                if item['active'] and item['account']==account and item['exchange']==key.exchange and item['symbol']==key.symbol:
                    store.change_strategy(item['id'],False)
                    store.log_event('strategy_stopped',account,{'id':item['id'],'reason':'broker market stream ended'})
            await self._broadcast(ident,{'event':'disconnected','message':'Broker data feed ended; dependent strategies stopped'})
        except asyncio.CancelledError:raise
        except Exception as ex:
            self.errors[ident]=type(ex).__name__
            store.log_event('feed_error',account,{'symbol':key.symbol,'type':type(ex).__name__})
            for item in store.strategies():
                if item['active'] and item['account']==account and item['exchange']==key.exchange and item['symbol']==key.symbol:
                    store.change_strategy(item['id'],False)
                    store.log_event('strategy_stopped',account,{'id':item['id'],'reason':'market feed stopped'})
            await self._broadcast(ident,{'event':'error','message':f'{type(ex).__name__}: market stream disconnected; affected strategies stopped'})
    async def close(self):
        for t in self.group_tasks.values():t.cancel()
        if self.group_tasks:await asyncio.gather(*self.group_tasks.values(),return_exceptions=True)
        self.group_tasks.clear()
        for t in self.tasks.values():t.cancel()
        if self.tasks:await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.tasks.clear()
