"""Regression tests for local workspace persistence, shared broker feed, and secure credential vault."""
from __future__ import annotations
import asyncio
from datetime import datetime,timezone
from fastapi.testclient import TestClient
from app.api.server import app
from app.brokers.base import InstrumentKey,Tick
from app.market_data.hub import MarketHub
from app.database import store
from app import core_vault

def test_workspace_preferences_and_theme_persist():
    with TestClient(app) as c:
        response=c.put('/api/preferences/workspace',json={'version':2,'root':{'kind':'pane','id':'test','type':'chart','config':{}},'floating':[]})
        assert response.status_code==200
        assert c.get('/api/preferences/workspace').json()['data']['version']==2
        assert c.put('/api/preferences/theme',json={'theme':'light'}).status_code==200
        assert c.get('/api/preferences/theme').json()['data']['theme']=='light'
        assert c.put('/api/preferences/workspace',json={'large':'a'*100001}).status_code==413
        assert c.get('/api/preferences/unknown').status_code==404

def test_shared_feed_distributes_two_keys(monkeypatch):
    monkeypatch.setattr(store,'strategies',lambda:[])
    monkeypatch.setattr(store,'log_event',lambda *args,**kwargs:None)
    class FakeAdapter:
        def __init__(self):self.calls=[]
        async def subscribe_market_data(self,keys):
            self.calls.append(tuple(k.symbol for k in keys))
            for k in keys:
                yield Tick(k,datetime.now(timezone.utc),101,previous_close=99)
            await asyncio.sleep(60)
    async def scenario():
        adapter=FakeAdapter();account='test:local';hub=MarketHub({account:adapter})
        a=InstrumentKey('NSE','NIFTY','IDX');b=InstrumentKey('NSE','BANKNIFTY','IDX')
        aq=await hub.listen(account,a);bq=await hub.listen(account,b)
        try:
            first=await asyncio.wait_for(aq.get(),timeout=1)
            second=await asyncio.wait_for(bq.get(),timeout=1)
            assert first['event']=='tick' and first['data']['previous_close']==99
            assert second['event']=='tick'
            assert any(set(call)=={'NIFTY','BANKNIFTY'} for call in adapter.calls)
            assert hub.status()[account]['state']=='connected'
        finally:
            await hub.close()
    asyncio.run(scenario())

def test_fernet_vault_encrypted_on_disk(monkeypatch,tmp_path):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(core_vault,'FILE',tmp_path/'broker_sessions.vault')
    monkeypatch.setattr(core_vault.sys,'platform','linux')
    monkeypatch.setenv('SAVE_BROKER_TOKENS','yes')
    monkeypatch.setenv('TRADING_VAULT_KEY',Fernet.generate_key().decode())
    core_vault.save_session('upstox:main','upstox','main',{'access_token':'VERY_PRIVATE_TEST_TOKEN'})
    assert b'VERY_PRIVATE_TEST_TOKEN' not in core_vault.FILE.read_bytes()
    assert core_vault.read_all()['upstox:main']['credentials']['access_token']=='VERY_PRIVATE_TEST_TOKEN'
    core_vault.forget_session('upstox:main')
    assert not core_vault.read_all()

def test_quotes_socket_dynamic_subscription(monkeypatch):
    """One browser socket subscribes two symbols and receives account-scoped ticks."""
    from app.api import server
    monkeypatch.setattr(store,'strategies',lambda:[])
    monkeypatch.setattr(store,'log_event',lambda *args,**kwargs:None)
    class Feed:
        broker_id='mock'
        async def subscribe_market_data(self,keys):
            for key in keys:
                yield Tick(key,datetime.now(timezone.utc),100,previous_close=98)
            await asyncio.sleep(60)
        async def close(self):pass
    server.SESSIONS['mock:two']=Feed()
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/ws/quotes/mock:two') as ws:
                assert ws.receive_json()['event']=='status'
                ws.send_json({'action':'subscribe','instruments':[
                    {'exchange':'NSE','symbol':'NIFTY','segment':'IDX'},
                    {'exchange':'NSE','symbol':'BANKNIFTY','segment':'IDX'}]})
                received=[]
                for _ in range(10):
                    msg=ws.receive_json()
                    received.append(msg)
                    if len({m.get('key',{}).get('symbol') for m in received if m.get('event')=='tick'})==2:
                        break
                symbols={m.get('key',{}).get('symbol') for m in received if m.get('event')=='tick'}
                assert symbols=={'NIFTY','BANKNIFTY'}
    finally:
        server.SESSIONS.pop('mock:two',None)
