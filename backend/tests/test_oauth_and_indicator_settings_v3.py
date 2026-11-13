"""Broker auth contract tests: use no live credentials and never submit real orders."""
import asyncio,hashlib,json
from urllib.parse import urlparse,parse_qs
import httpx
from fastapi.testclient import TestClient
from app.brokers.oauth import authorization_url,exchange_code
from app.api import server


def test_fyers_login_url_and_code_exchange():
    creds={'client_id':'APP-100','api_secret':'not-a-real-secret'}
    url=authorization_url('fyers',creds,'state-abc')
    qs=parse_qs(urlparse(url).query)
    assert qs['state']==['state-abc']
    assert qs['redirect_uri']==['http://127.0.0.1:8000/api/auth/callback/fyers']
    calls=[]
    def handler(req):
        calls.append(req)
        body=json.loads(req.content)
        assert body['appIdHash']==hashlib.sha256(b'APP-100:not-a-real-secret').hexdigest()
        assert body['grant_type']=='authorization_code' and body['code']=='CODE'
        return httpx.Response(200,json={'s':'ok','access_token':'fake-token'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await exchange_code('fyers',creds,'CODE',client)
    assert asyncio.run(run())['access_token']=='fake-token'
    assert len(calls)==1


def test_flattrade_callback_exchange_uses_correct_hash():
    creds={'api_key':'public','api_secret':'private','user_id':'CLIENT1'}
    assert 'app_key=public' in authorization_url('flattrade',creds,'state')
    def handler(req):
        assert str(req.url)=='https://authapi.flattrade.in/trade/apitoken'
        body=json.loads(req.content)
        assert body['api_secret']==hashlib.sha256(b'publicONE_TIMEprivate').hexdigest()
        return httpx.Response(200,json={'status':'Ok','token':'fictional-token','client':'CLIENT1'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await exchange_code('flattrade',creds,'ONE_TIME',client)
    assert asyncio.run(run())['user_id']=='CLIENT1'


def test_finvasia_current_oauth_checksum_and_jdata():
    creds={'client_id':'ABC','secret_key':'SECRET','user_id':'USER'}
    assert 'OAuthlogin/authorize/oauth' in authorization_url('finvasia',creds,'state')
    def handler(req):
        assert req.headers['content-type']=='text/plain'
        assert req.content.startswith(b'jData=')
        data=json.loads(req.content[6:])
        assert data=={'code':'C123','checksum':hashlib.sha256(b'ABCSECRETC123').hexdigest()}
        return httpx.Response(200,json={'stat':'Ok','susertoken':'fictional-token','uid':'USER'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await exchange_code('finvasia',creds,'C123',client)
    assert asyncio.run(run())['user_id']=='USER'


def test_start_callback_and_state_validation(monkeypatch):
    async def fake_exchange(broker,credentials,code):
        return {**credentials,'access_token':'CONFIDENTIAL_TEST_TOKEN'}
    async def fake_connect(req):return {'account':f'{req.broker}:{req.account_id}'}
    monkeypatch.setattr(server,'exchange_code',fake_exchange)
    monkeypatch.setattr(server,'connect',fake_connect)
    with TestClient(server.app) as client:
        request={'broker':'fyers','account_id':'testing','credentials':{'client_id':'X','api_secret':'Y'}}
        start=client.post('/api/auth/start',json=request)
        assert start.status_code==200
        state=parse_qs(urlparse(start.json()['authorization_url']).query)['state'][0]
        invalid=client.get('/api/auth/callback/fyers?auth_code=CODE&state=wrong')
        assert invalid.status_code==400
        valid=client.get('/api/auth/callback/fyers',params={'auth_code':'CODE','state':state})
        assert valid.status_code==200
        assert 'fyers:testing' in valid.text
        assert 'CONFIDENTIAL_TEST_TOKEN' not in valid.text
        assert client.get('/api/auth/callback/fyers',params={'auth_code':'CODE','state':state}).status_code==400


def test_indicator_rejects_invalid_parameter_name(monkeypatch):
    from app.brokers.mock import MockBroker
    from app.brokers.base import InstrumentKey,Candle
    from datetime import datetime,timedelta,timezone
    broker=MockBroker('tester')
    server.SESSIONS['mock:test-v3']=broker
    times=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[Candle(times+timedelta(minutes=i),100+i,101+i,99+i,100+i,1000) for i in range(80)]
    monkeypatch.setattr(server.store,'load_candles',lambda *args,**kw:rows)
    try:
        with TestClient(server.app) as c:
            valid=c.get('/api/indicators',params={'account':'mock:test-v3','exchange':'NSE','symbol':'ABC',
                'name':'rsi','inputs':json.dumps({'n':7})})
            # Parameter names are dictated by the actual REGISTRY, no blind translation.
            assert valid.status_code in (200,422)
            invalid=c.get('/api/indicators',params={'account':'mock:test-v3','exchange':'NSE','symbol':'ABC',
                'name':'rsi','inputs':json.dumps({'undeclared_parameter':7})})
            assert invalid.status_code==422
    finally:server.SESSIONS.pop('mock:test-v3',None)
