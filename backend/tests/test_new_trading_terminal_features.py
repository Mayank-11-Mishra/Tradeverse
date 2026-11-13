"""Regression tests for studies, option chains, token scopes, and API safety.
No test makes an external broker request or places a real order.
"""
import asyncio
import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app.api.server import app, SESSIONS, HUB
from unittest.mock import AsyncMock, patch
from app.brokers.base import Capability
from app.brokers.upstox import UpstoxBroker
from app.brokers.fyers import FyersBroker
from app.indicators.engine import REGISTRY, compute_indicator
from app.indicators.catalog import inventory, implemented
from app.option_chain.normalize import normalize_chain


def run(coro):
    return asyncio.run(coro)


def test_user_studies_inventory_is_complete_and_status_is_explicit():
    entries=inventory()
    assert len(entries)==469
    assert len({x['category'] for x in entries})==26
    assert len(REGISTRY)>=50
    assert len(implemented())==len(REGISTRY)
    assert all('implemented' in item and 'indicator_id' in item for item in entries)
    custom=next(x for x in entries if x['name']=='Custom Signal')
    assert not custom['implemented']
    assert next(x for x in entries if x['name']=='Average - Hull')['indicator_id']=='hull'


def sample_candles(n=100):
    # Fixed, reproducible OHLCV; no actual market data or look-ahead inputs.
    close=pd.Series(np.linspace(100,125,n)+np.sin(np.arange(n)/3))
    return pd.DataFrame({'open':close-.5,'high':close+1.25,'low':close-1.15,
                         'close':close,'volume':pd.Series(1000+np.arange(n)*7,dtype=float)})


@pytest.mark.parametrize('id', ['hull','dema','tema','zlema','trima','roc','willr','aroon',
                                  'cmf','ad_line','nvi_pvi','linreg','cmo','tsi','awesome',
                                  'force','choppiness','ultimate','fisher','volume_oscillator','dpo','bbwidth'])
def test_added_standard_indicators_return_aligned_values(id):
    candles=sample_candles()
    result=compute_indicator(id,candles)
    assert isinstance(result,pd.DataFrame)
    assert len(result)==len(candles)
    assert result.shape[1]>=1
    assert any(np.isfinite(result[c]).any() for c in result.columns)
    assert not np.isinf(result.to_numpy(dtype=float)).any()


@pytest.mark.parametrize('name', ['hull','dema','tema','roc','cmo','nvi_pvi','fisher'])
def test_extended_indicators_do_not_look_ahead(name):
    candles=sample_candles(120)
    old=compute_indicator(name,candles.iloc[:80])
    new=candles.copy()
    new.loc[80:,'close']+=500
    longer=compute_indicator(name,new)
    np.testing.assert_allclose(old.to_numpy(dtype=float),longer.iloc[:80].to_numpy(dtype=float),equal_nan=True)


def test_upstox_analytics_token_uses_quote_not_profile_and_disables_private_apis():
    paths=[]
    def handler(req):
        paths.append(req.url.path)
        assert req.url.path=='/v3/market-quote/ltp'
        assert req.headers['Authorization']=='Bearer DEMO_ANALYTICS_TOKEN'
        assert req.url.params['instrument_key']=='NSE_INDEX|Nifty 50'
        return httpx.Response(200,json={'status':'success','data':{'NSE_INDEX:Nifty 50':{'last_price':26200}}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            b=UpstoxBroker('local',client=client)
            p=await b.authenticate({'access_token':'Bearer DEMO_ANALYTICS_TOKEN','token_type':'analytics'})
            assert p.name.endswith('(data only)')
            assert b.read_only
            assert b.supports(Capability.HISTORICAL_CANDLES)
            assert b.supports(Capability.OPTION_CHAIN)
            assert not b.supports(Capability.PLACE_ORDER)
            assert not b.supports(Capability.POSITIONS)
            assert not b.supports(Capability.TRADEBOOK)
            assert await b.verify_session() is True
    run(scenario())
    assert paths==['/v3/market-quote/ltp']*2


def test_upstox_option_chain_fetch_uses_instrument_key_and_expiry():
    requests=[]
    def handler(req):
        requests.append((req.url.path,dict(req.url.params)))
        assert req.headers['Authorization']=='Bearer UPSTOX_TEST_TOKEN'
        if req.url.path=='/v2/option/contract':
            return httpx.Response(200,json={'status':'success','data':[
                {'expiry':'2026-11-26','trading_symbol':'NIFTY26NOV2626000CE'},
                {'expiry':'2026-11-19','trading_symbol':'NIFTY19NOV2626000CE'},
                {'expiry':'2026-11-26','trading_symbol':'NIFTY26NOV2626000PE'}]})
        assert req.url.path=='/v2/option/chain'
        return httpx.Response(200,json={'status':'success','data':[
            {'strike_price':26000,'call_options':{'instrument_key':'NFO|11','market_data':{
               'ltp':222,'oi':100,'bid_price':221,'ask_price':223},'option_greeks':{'delta':0.55,'iv':14}},
             'put_options':{'market_data':{'ltp':199,'oi':150},'option_greeks':{'delta':-0.45}}}]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            b=UpstoxBroker('local',client=client)
            b.access_token='UPSTOX_TEST_TOKEN'
            assert await b.get_option_expiries('NIFTY')==['2026-11-19','2026-11-26']
            raw=await b.get_option_chain('NIFTY','2026-11-19')
            chain=normalize_chain('upstox',raw,'NIFTY','2026-11-19')
            assert chain['count']==1
            assert chain['rows'][0]['call']['oi']==100
            assert chain['rows'][0]['put']['delta']==-0.45
    run(scenario())
    assert requests[0][1]['instrument_key']=='NSE_INDEX|Nifty 50'
    assert requests[1][1]['instrument_key']=='NSE_INDEX|Nifty 50'
    assert requests[1][1]['expiry_date']=='2026-11-19'


def test_fyers_option_chain_normalization_calls_and_puts():
    data={'optionsChain':[
        {'strike_price':26000,'option_type':'CE','symbol':'NSE:NIFTY26NOV26000CE','ltp':145,'oi':1500,'bid':144},
        {'strike_price':26000,'option_type':'PE','symbol':'NSE:NIFTY26NOV26000PE','ltp':130,'oi':2400,'ask':131},
        {'strike_price':26050,'option_type':'CE','ltp':99,'oi':1800}]}
    result=normalize_chain('fyers',data,'NIFTY','2026-11-26')
    assert result['count']==2
    assert result['rows'][0]['call']['ltp']==145
    assert result['rows'][0]['put']['oi']==2400
    assert result['rows'][1]['put'] is None
    assert FyersBroker._option_symbol('NIFTY')=='NSE:NIFTY50-INDEX'


def test_studies_and_orderbook_require_a_logged_in_broker():
    with TestClient(app) as client:
        assert client.get('/api/studies/catalog').status_code==409
        assert client.get('/api/options/expiries',params={'account':'upstox:NOT_CONNECTED_900','underlying':'NIFTY'}).status_code==409
        assert client.get('/api/tradebook/upstox:NOT_CONNECTED_900').status_code==409
        assert client.post('/api/orders/cancel',json={'account':'upstox:NOT_CONNECTED_900','order_id':'FAKE'}).status_code==409


def test_mock_strategy_paper_deployment_roundtrip_and_live_blocked():
    with TestClient(app) as client:
        account='mock:STUDIES_TEST_489'
        connected=client.post('/api/accounts/connect',json={'broker':'mock','account_id':'STUDIES_TEST_489','credentials':{}})
        assert connected.status_code==200,connected.text
        try:
            assert len(client.get('/api/studies/catalog').json()['inventory'])==469
            body={'name':'Demo rules','account':account,'exchange':'NSE','symbol':'RELIANCE',
                  'interval':'1m','mode':'paper'}
            create=client.post('/api/strategies',json=body)
            assert create.status_code==200,create.text
            strategy_id=create.json()['id']
            assert not create.json()['active']
            # Simulate a healthy broker stream; mock adapter intentionally has no feed.
            with patch.object(SESSIONS[account],'supports',side_effect=lambda cap:cap == Capability.LIVE_STREAM), \
                 patch.object(HUB,'ensure_strategy_feed',new_callable=AsyncMock) as feed:
                start=client.post(f'/api/strategies/{strategy_id}/start')
                assert start.status_code==200,start.text
                assert start.json()['active']
                feed.assert_awaited_once()
            health=client.get('/api/strategies/health')
            assert health.status_code==200
            assert any(item['id']==strategy_id for item in health.json())
            stop=client.post(f'/api/strategies/{strategy_id}/stop')
            assert stop.status_code==200
            assert stop.json()['active'] is False
            # Saving a live strategy is allowed; deploying it is not.
            live=client.post('/api/strategies',json={**body,'name':'Live test','mode':'live'})
            assert live.status_code==200
            assert client.post(f"/api/strategies/{live.json()['id']}/start").status_code==403
        finally:
            client.delete('/api/accounts/'+account)


def test_finished_broker_feed_stops_active_strategy(monkeypatch):
    """A stream ending normally must NOT leave a live deployment marked active."""
    from app.market_data.hub import MarketHub
    from app.brokers.base import InstrumentKey
    from app.database import store
    class EmptyStream:
        def subscribe_market_data(self, keys):
            async def feed():
                if False:
                    yield None
            return feed()
    stopped=[];events=[]
    strategy={'id':'stream_should_stop','active':True,'account':'mock:FEED_END',
              'exchange':'NSE','symbol':'RELIANCE','segment':'EQ','interval':'1m'}
    monkeypatch.setattr(store,'strategies',lambda:[strategy])
    monkeypatch.setattr(store,'change_strategy',lambda id,active:stopped.append((id,active)) or True)
    monkeypatch.setattr(store,'log_event',lambda kind,account,details=None:events.append(kind))
    async def scenario():
        hub=MarketHub({'mock:FEED_END':EmptyStream()})
        key=InstrumentKey('NSE','RELIANCE','EQ')
        await hub._run('mock:FEED_END',key)
        assert hub.errors[('mock:FEED_END','NSE','RELIANCE','EQ')]=='feed_ended'
    run(scenario())
    assert ('stream_should_stop',False) in stopped
    assert 'strategy_stopped' in events
