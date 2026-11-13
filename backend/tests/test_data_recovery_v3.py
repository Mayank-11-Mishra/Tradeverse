"""Regression coverage for the November 2026 history and Upstox feed fixes.
No broker credentials or real orders are used by these tests.
"""
import asyncio
from datetime import datetime,timezone,timedelta
import httpx
from app.brokers.base import InstrumentKey,Capability,BrokerError
from app.brokers.streams import parse_upstox_message
from app.brokers.upstox import UpstoxBroker
from app.api import server


def test_upstox_v3_full_market_feed_decodes_equity_and_index():
    k1=InstrumentKey('NSE','NIFTY','IDX')
    k2=InstrumentKey('NSE','RELIANCE','EQ')
    msg={'type':'live_feed','currentTs':'1794551110000','feeds':{
       'NSE_INDEX|Nifty 50':{'ff':{'indexFF':{'ltpc':{'ltp':25510.4,'ltt':'1794551110000','cp':25420.5}}}},
       'NSE_EQ|INE002A01018':{'ff':{'marketFF':{
          'ltpc':{'ltp':1402.75,'ltt':'1794551110000','cp':1400.2},
          'vtt':'34000','oi':1000,'marketLevel':{'bidAskQuote':[{'bidP':1402.2,'askP':1402.8}]}
       }}}
    }}
    result=parse_upstox_message(msg,{'NSE_INDEX|Nifty 50':k1,'NSE_EQ|INE002A01018':k2})
    assert len(result)==2
    assert result[0].key==k1 and result[0].ltp==25510.4
    assert result[1].key==k2 and result[1].ltp==1402.75
    assert result[1].bid==1402.2 and result[1].ask==1402.8
    assert result[1].volume==34000 and result[1].previous_close==1400.2
    assert len(parse_upstox_message({'feeds':{'NSE_INDEX|Nifty 50':{'ltpc':{'ltp':25500}}}}, {'NSE_INDEX|Nifty 50':k1}))==1


def test_upstox_default_index_resolves_to_official_key():
    b=UpstoxBroker('local')
    assert b.token_for(InstrumentKey('NSE','NIFTY','IDX'))=='NSE_INDEX|Nifty 50'
    assert b.token_for(InstrumentKey('NSE','BANKNIFTY','INDEX'))=='NSE_INDEX|Nifty Bank'


def test_history_refresh_defaults_to_one_year(monkeypatch):
    captured=[]
    class Adapter:
        broker_id='upstox'
        def supports(self,cap):return cap==Capability.HISTORICAL_CANDLES
    async def sync(adapter,account,key,interval,start,end,store):
        captured.append((interval,start,end));return 0
    monkeypatch.setattr(server,'sync_history',sync)
    monkeypatch.setattr(server.store,'load_candles',lambda *a:[])
    server.SESSIONS['upstox:date-test']=Adapter()
    try:
        asyncio.run(server.history('upstox:date-test','NSE','NIFTY','IDX','15m',refresh=True))
        assert 364 <= (captured[0][2]-captured[0][1]).days <= 366
    finally:server.SESSIONS.pop('upstox:date-test',None)


def test_upstox_rest_ltp_snapshot_is_genuine_broker_response():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'status':'success','data':{
            'NSE_INDEX:NIFTY':{'last_price':25920.55,'instrument_token':'NSE_INDEX|Nifty 50','cp':25800.75}
        }})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            b=UpstoxBroker('test',client=http);b.access_token='FAKE_TOKEN'
            result=await b.get_ltp_quotes([InstrumentKey('NSE','NIFTY','IDX')])
            assert len(result)==1 and result[0]['ltp']==25920.55
            assert result[0]['source']=='snapshot' and result[0]['previous_close']==25800.75
            assert requests[0].url.path=='/v3/market-quote/ltp'
            assert requests[0].url.params['instrument_key']=='NSE_INDEX|Nifty 50'
    asyncio.run(go())


def test_upstox_index_search_result_normalizes_index_segment():
    def handler(request):
        return httpx.Response(200,json={'status':'success','data':[
         {'trading_symbol':'NIFTY','name':'Nifty 50','exchange':'NSE','segment':'NSE_INDEX',
          'instrument_key':'NSE_INDEX|Nifty 50','instrument_type':'INDEX'}]})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            b=UpstoxBroker('test',client=http);b.access_token='DUMMY'
            rows=await b.get_instruments('NIFTY','NSE')
            assert rows[0].key.segment=='IDX'
            assert b.token_for(rows[0].key)=='NSE_INDEX|Nifty 50'
    asyncio.run(go())
