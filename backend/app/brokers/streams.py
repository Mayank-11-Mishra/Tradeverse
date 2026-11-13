"""Real broker feeds. SDKs remain optional and are imported only when connected.
No synthetic ticks: a missing price is ignored. Queue is bounded to avoid unbounded RAM.
"""
from __future__ import annotations
import asyncio,json,threading
from contextlib import suppress
from datetime import datetime,timezone
from .base import Tick,InstrumentKey,BrokerError
from .common import dt

def _keys(adapter,keys,allow_symbol=False):
    return {str(adapter.token_for(k,allow_symbol=allow_symbol)):k for k in keys}

def _tick(key,price,source,ts=None,bid=None,ask=None,volume=None,oi=None,previous_close=None):
    if price in (None,''):return None
    try:
        v=float(price)
        if v<=0:return None
        return Tick(key,dt(ts) if ts else datetime.now(timezone.utc),v,
            float(bid) if bid not in (None,'') else None,float(ask) if ask not in (None,'') else None,
            float(volume) if volume not in (None,'') else None,float(oi) if oi not in (None,'') else None,source,float(previous_close) if previous_close not in (None,'') else None)
    except (ValueError,TypeError):return None

async def noren_stream(adapter,keys):
    """Shoonya and Flattrade current 't:a' session handshake, touchline subscription."""
    try:import websockets
    except ImportError as exc:raise BrokerError('pip install websockets') from exc
    tokens=_keys(adapter,keys,allow_symbol=all(k.symbol.isdigit() for k in keys))
    subscribed='#'.join(f'{k.exchange}|{token}' for token,k in tokens.items())
    if not subscribed:return
    retry=1
    while adapter.access_token:
        try:
            async with websockets.connect(adapter.websocket_url,open_timeout=15,ping_interval=20,ping_timeout=20,max_size=2_000_000) as ws:
                await ws.send(json.dumps({'t':'a','uid':adapter.user_id,'actid':adapter.account_id,
                    'source':'API','accesstoken':adapter.access_token}))
                initial=json.loads(await asyncio.wait_for(ws.recv(),timeout=12))
                if initial.get('t')!='ak' or initial.get('s')!='Ok':
                    raise BrokerError('WebSocket login denied; check broker session')
                await ws.send(json.dumps({'t':'t','k':subscribed}))
                retry=1
                async def heart():
                    while True:
                        await asyncio.sleep(30)
                        await ws.send(json.dumps({'t':'h'}))
                heartbeat=asyncio.create_task(heart())
                try:
                    async for raw in ws:
                        try:msg=json.loads(raw)
                        except (ValueError,TypeError):continue
                        if not isinstance(msg,dict) or msg.get('t') not in ('tk','tf','dk','df'):continue
                        token=str(msg.get('tk',''))
                        key=tokens.get(token)
                        if not key:continue
                        tick=_tick(key,msg.get('lp'),adapter.broker_id,msg.get('ft'),
                            msg.get('bp1'),msg.get('sp1'),msg.get('v'),msg.get('oi'),msg.get('c'))
                        if tick:yield tick
                finally:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):await heartbeat
        except asyncio.CancelledError:raise
        except BrokerError:raise
        except Exception:
            await asyncio.sleep(retry)
            retry=min(retry*2,30)

async def _sdk_stream(start,stop):
    """Bridge SDK thread callbacks into asyncio safely with bounded event buffer."""
    loop=asyncio.get_running_loop()
    queue=asyncio.Queue(maxsize=4000)
    active=True
    def emit(tick):
        if not active or tick is None:return
        def put():
            if queue.full():
                with suppress(asyncio.QueueEmpty):queue.get_nowait()
            queue.put_nowait(tick)
        try:loop.call_soon_threadsafe(put)
        except RuntimeError:pass
    instance=start(emit)
    try:
        while True:
            try:
                item=await asyncio.wait_for(queue.get(),timeout=35)
            except asyncio.TimeoutError:
                # Quiet markets should not terminate an otherwise healthy stream.
                continue
            if isinstance(item,Exception):raise item
            yield item
    finally:
        active=False
        with suppress(Exception):stop(instance)

async def zerodha_stream(adapter,keys):
    try:from kiteconnect import KiteTicker
    except ImportError as exc:raise BrokerError('pip install kiteconnect for Zerodha live stream') from exc
    token_map={int(v):k for v,k in _keys(adapter,keys,allow_symbol=all(k.symbol.isdigit() for k in keys)).items()}
    def start(emit):
        kws=KiteTicker(adapter.api_key,adapter.access_token,reconnect=True)
        def connected(ws,response):
            ws.subscribe(list(token_map));ws.set_mode(ws.MODE_FULL,list(token_map))
        def ticks(ws,rows):
            for r in rows:
                key=token_map.get(int(r.get('instrument_token',0)))
                if not key:continue
                depth=r.get('depth') or {};buy=depth.get('buy') or [];sell=depth.get('sell') or []
                emit(_tick(key,r.get('last_price'),adapter.broker_id,
                    r.get('exchange_timestamp',r.get('last_trade_time')),
                    buy[0].get('price') if buy else None,sell[0].get('price') if sell else None,
                    r.get('volume_traded'),r.get('oi'),(r.get('ohlc') or {}).get('close')))
        kws.on_ticks=ticks;kws.on_connect=connected;kws.connect(threaded=True)
        return kws
    async for tick in _sdk_stream(start,lambda x:x.close()):yield tick

async def fyers_stream(adapter,keys):
    try:from fyers_apiv3.FyersWebsocket import data_ws
    except ImportError as exc:raise BrokerError('pip install fyers-apiv3 for FYERS live stream') from exc
    symbols={k.symbol:k for k in keys}
    def start(emit):
        def onmessage(m):
            if not isinstance(m,dict):return
            key=symbols.get(m.get('symbol'))
            if key:
                emit(_tick(key,m.get('ltp'),adapter.broker_id,m.get('last_traded_time'),
                    m.get('bid_price1'),m.get('ask_price1'),m.get('vol_traded_today'),m.get('oi'),m.get('prev_close_price')))
        sock=None
        def onopen():
            sock.subscribe(symbols=list(symbols),data_type='SymbolUpdate')
            sock.keep_running()
        sock=data_ws.FyersDataSocket(access_token=f'{adapter.client_id}:{adapter.access_token}',log_path='',
            litemode=False,write_to_file=False,reconnect=True,on_connect=onopen,
            on_message=onmessage,on_error=lambda *a:None,on_close=lambda *a:None)
        threading.Thread(target=sock.connect,daemon=True).start()
        return sock
    async for tick in _sdk_stream(start,lambda x:x.close_connection()):yield tick

def parse_upstox_message(msg,token_map):
    """SDK already decodes Protobuf to structured records; do not parse raw frames as JSON."""
    if not isinstance(msg,dict):return []
    result=[]
    for token,body in (msg.get('feeds') or {}).items():
        key=token_map.get(token)
        if not key or not isinstance(body,dict):continue
        # Official V3 SDK protobuf MessageToDict maps the feed oneof to `ff`.
        # Older payloads may use fullFeed; ltpc-only snapshots are also valid.
        feed=body.get('ff') or body.get('fullFeed') or body
        market=(feed.get('marketFF') or feed.get('indexFF') or feed) if isinstance(feed,dict) else {}
        price=(market.get('ltpc') or body.get('ltpc') or {}) if isinstance(market,dict) else {}
        if not isinstance(price,dict):continue
        depth=(market.get('marketLevel') or {}).get('bidAskQuote') or []
        first=depth[0] if depth else {}
        output=_tick(key,price.get('ltp'),'upstox',price.get('ltt') or msg.get('currentTs'),
            bid=first.get('bidP'),ask=first.get('askP'),volume=market.get('vtt'),
            oi=market.get('oi'),previous_close=price.get('cp'))
        if output:result.append(output)
    return result

async def upstox_stream(adapter,keys):
    try:import upstox_client
    except ImportError as exc:raise BrokerError('pip install upstox-python-sdk for V3 protobuf stream') from exc
    tokens=_keys(adapter,keys,allow_symbol=all('|' in k.symbol for k in keys))
    def start(emit):
        config=upstox_client.Configuration();config.access_token=adapter.access_token
        stream=upstox_client.MarketDataStreamerV3(upstox_client.ApiClient(config),list(tokens),'full')
        stream.on('message',lambda m:[emit(t) for t in parse_upstox_message(m,tokens)])
        stream.on('error',lambda error:emit(BrokerError('Upstox market-data WebSocket error (check token and subscription)')))
        stream.on('close',lambda *args:emit(BrokerError('Upstox market-data WebSocket closed')))
        stream.auto_reconnect(True,3,20)
        threading.Thread(target=stream.connect,daemon=True).start()
        return stream
    async for tick in _sdk_stream(start,lambda x:x.disconnect()):yield tick

async def groww_stream(adapter,keys):
    try:from growwapi import GrowwFeed,GrowwAPI
    except ImportError as exc:raise BrokerError('pip install growwapi for Groww streaming') from exc
    token_map=_keys(adapter,keys)
    instruments=[{'exchange':k.exchange,'segment':'CASH' if k.segment in ('EQ','IDX','INDEX') else 'FNO',
                  'exchange_token':v} for v,k in token_map.items()]
    def start(emit):
        feed=GrowwFeed(GrowwAPI(adapter.access_token))
        def callback(_):
            data=feed.get_ltp() or {}
            for exchange,segments in (data.get('ltp') or {}).items():
                for segment,values in segments.items():
                    for tok,quote in values.items():
                        k=token_map.get(str(tok))
                        if k:emit(_tick(k,quote.get('ltp'),'groww',quote.get('tsInMillis')))
        feed.subscribe_ltp(instruments,on_data_received=callback)
        threading.Thread(target=feed.consume,daemon=True).start()
        return feed
    def stop(feed):
        with suppress(Exception):feed.unsubscribe_ltp(instruments)
        with suppress(Exception):feed.disconnect()
    async for tick in _sdk_stream(start,stop):yield tick
