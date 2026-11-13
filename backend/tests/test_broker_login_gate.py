"""Broker-first access checks. Test-only mock never submits real market orders."""
from fastapi.testclient import TestClient
from app.api.server import app


def test_history_and_backtest_are_locked_without_broker_login():
    with TestClient(app) as client:
        account='zerodha:NOT_CONNECTED_99'
        response=client.get('/api/history',params={'account':account,'exchange':'NSE','symbol':'RELIANCE'})
        assert response.status_code==409
        response=client.post('/api/backtest',json={'account':account,'exchange':'NSE','symbol':'RELIANCE','candles':[]})
        assert response.status_code==409
        response=client.post('/api/history/import',params={'account':account,'exchange':'NSE','symbol':'RELIANCE'},json=[])
        assert response.status_code==409
        response=client.get('/api/indicators',params={'account':account,'exchange':'NSE','symbol':'RELIANCE','name':'ema'})
        assert response.status_code==409
        response=client.post('/api/strategies',json={'name':'locked','account':account,'exchange':'NSE','symbol':'RELIANCE'})
        assert response.status_code==409


def test_bad_login_never_unlocks_and_successful_login_can_be_reverified():
    with TestClient(app) as client:
        account='mock:TEST_GATE_01'
        failed=client.post('/api/accounts/connect',json={'broker':'mock','account_id':'TEST_GATE_01','credentials':{'bad':True}})
        assert failed.status_code==401
        assert client.post('/api/accounts/verify',json={'account':account}).status_code==409
        connected=client.post('/api/accounts/connect',json={'broker':'mock','account_id':'TEST_GATE_01','credentials':{}})
        assert connected.status_code==200
        assert connected.json()['account']==account
        assert client.post('/api/accounts/verify',json={'account':account}).json()['verified'] is True
        assert any(a['connected'] for a in client.get('/api/accounts').json() if a['id']==account)
        assert client.delete('/api/accounts/'+account).status_code==200
        assert client.post('/api/accounts/verify',json={'account':account}).status_code==409
