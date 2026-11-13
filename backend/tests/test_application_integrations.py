"""Integration/regression tests. HTTP transports use sanitized fixtures, never real orders."""
from __future__ import annotations
import httpx
from datetime import datetime,timezone,timedelta
from fastapi.testclient import TestClient
from app.api.server import app,RISK
from app.brokers.base import InstrumentKey,OrderRequest,Capability,capability_matrix
from app.brokers.groww import GrowwBroker
from app.brokers.zerodha import ZerodhaBroker
from app.brokers.upstox import UpstoxBroker
from app.brokers.fyers import FyersBroker
from app.brokers.flattrade import FlattradeBroker
from app.brokers.finvasia import FinvasiaBroker
from app.brokers.common import candles
from app.risk_management.engine import RiskEngine,RiskLimits,OrderIntent


def test_six_broker_registry_reports_real_state():
    matrix=capability_matrix()
    assert {'zerodha','upstox','groww','fyers','flattrade','finvasia'} <= matrix.keys()
    assert all(matrix[x]['verification'].endswith('live-untested') for x in ('groww','zerodha','upstox','fyers','flattrade','finvasia'))
    assert not matrix['groww']['funds'] # not implemented; do not claim capability


def test_candle_parsing_rejects_bad_ohlc_and_deduplicates():
    bars=candles([['2026-01-01T09:15:00+05:30',100,105,99,103,900],
                 ['2026-01-01T09:15:00+05:30',100,105,99,103,900],
                 ['2026-01-01T09:16:00+05:30',100,98,99,103,900]])
    assert len(bars)==1 and bars[0].close==103


def test_exit_flag_cannot_bypass_risk_rules_without_reducing_position():
    r=RiskEngine(RiskLimits(max_daily_loss=1000))
    o=OrderIntent('zerodha','X','manual','NIFTY','BUY',10,200,'paper',True)
    assert not r.check(o,datetime(2026,1,2,10,tzinfo=timezone(timedelta(hours=5,minutes=30)))).allowed
    r.set_position('X','NIFTY',10,200)
    o.side='SELL'
    assert r.check(o,datetime(2026,1,2,10,tzinfo=timezone(timedelta(hours=5,minutes=30)))).allowed
    o.qty=20
    assert not r.check(o,datetime(2026,1,2,10,tzinfo=timezone(timedelta(hours=5,minutes=30)))).allowed


def test_market_order_missing_reference_price_is_blocked():
    r=RiskEngine(RiskLimits(live_trading_enabled=True,max_order_notional=50000))
    o=OrderIntent('zerodha','X','manual','NIFTY','BUY',10,0,'live',False)
    d=r.check(o,datetime(2026,1,2,10,tzinfo=timezone(timedelta(hours=5,minutes=30))),feed_age_sec=1)
    assert not d.allowed and any('reference price' in x for x in d.reasons)


def test_zerodha_rest_wire_format():
    requests=[]
    def handler(r):
        requests.append(r)
        if r.url.path=='/user/profile':return httpx.Response(200,json={'status':'success','data':{'user_id':'Z1','user_name':'Test'}})
        if r.url.path=='/orders/regular':return httpx.Response(200,json={'status':'success','data':{'order_id':'O123'}})
        return httpx.Response(200,json={'status':'success','data':{'candles':[]}})
    import asyncio
    async def check():
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        b=ZerodhaBroker('Z1',client=client)
        await b.authenticate({'api_key':'KEY','access_token':'TOKEN'})
        oid=await b.place_order(OrderRequest(InstrumentKey('NSE','RELIANCE'),'BUY',1,'LIMIT','MIS',price=125.0))
        assert oid=='O123'
        assert requests[0].headers['authorization']=='token KEY:TOKEN'
        assert 'tradingsymbol=RELIANCE' in requests[-1].content.decode()
        await client.aclose()
    asyncio.run(check())


def test_upstox_v3_historical_path_uses_instrument_key():
    paths=[]
    def handler(r):
        paths.append(str(r.url))
        return httpx.Response(200,json={'status':'success','data':{'candles':[['2026-01-01T09:15:00+05:30',100,110,99,105,30,0]]}})
    import asyncio
    async def check():
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        b=UpstoxBroker('U1',client=client);b.access_token='TOKEN'
        bars=await b.get_historical_data(InstrumentKey('NSE','NSE_EQ|INE000A00001'),'1m',
            datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,1,2,tzinfo=timezone.utc))
        assert len(bars)==1 and bars[0].close==105
        assert '/v3/historical-candle/NSE_EQ%7CINE000A00001/minutes/1/' in paths[0]
        await client.aclose()
    asyncio.run(check())


def test_api_connect_import_history_and_backtest():
    with TestClient(app) as c:
        label='TEST_APP_INTEGRATION_008'
        response=c.post('/api/accounts/connect',json={'broker':'mock','account_id':label,'credentials':{}})
        assert response.status_code==200,response.text
        account=response.json()['account']
        candles_data=[]
        first=datetime(2026,9,1,9,15,tzinfo=timezone(timedelta(hours=5,minutes=30)))
        for i in range(75):
            price=100+i*0.2+((i%11)-5)*0.7
            candles_data.append({'date':(first+timedelta(minutes=i)).isoformat(),'open':price,'high':price+1,'low':price-1,'close':price+.1,'volume':1000})
        imp=c.post('/api/history/import',params={'account':account,'exchange':'NSE','symbol':'TESTSYM','interval':'1m'},json=candles_data)
        assert imp.status_code==200,imp.text
        bars=c.get('/api/history',params={'account':account,'exchange':'NSE','symbol':'TESTSYM','interval':'1m',
                                           'start':'2026-09-01T00:00:00+05:30','end':'2026-09-02T00:00:00+05:30'})
        assert len(bars.json())==75,bars.text
        bt=c.post('/api/backtest',json={'account':account,'exchange':'NSE','symbol':'TESTSYM','interval':'1m'})
        assert bt.status_code==200,bt.text
        assert 'metrics' in bt.json() and 'trades' in bt.json()
        s=c.post('/api/strategies',json={'name':'Test rules','account':account,'exchange':'NSE','symbol':'TESTSYM'})
        assert s.status_code==200,s.text
        started=c.post(f"/api/strategies/{s.json()['id']}/start",json={})
        assert started.status_code==422 # mock has no genuine market feed
        o=c.post('/api/orders',json={'account':account,'exchange':'NSE','symbol':'TESTSYM','side':'BUY','qty':1,'price':100,'order_type':'LIMIT','mode':'paper'})
        # Trading session constraint can make this fail outside hours; never bypass risk just to pass.
        assert o.status_code in (200,403)
        d=c.delete('/api/accounts/'+account)
        assert d.status_code==200,d.text
