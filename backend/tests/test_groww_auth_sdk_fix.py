"""Groww auth regression checks using mocked HTTP responses; no live credentials or orders."""
import hashlib
import httpx
import pytest
from app.brokers.groww import GrowwBroker
from app.brokers.base import AuthError

@pytest.mark.asyncio
async def test_groww_api_key_without_optional_sdk_uses_official_token_exchange(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == '/v1/token/api/access':
            data = __import__('json').loads(request.content)
            assert data['key_type'] == 'approval'
            assert data['checksum'] == hashlib.sha256(('supersecret' + data['timestamp']).encode()).hexdigest()
            assert request.headers['authorization'] == 'Bearer TEST-KEY'
            return httpx.Response(200, json={'status':'SUCCESS','token':'MOCK-TOKEN'})
        if request.url.path == '/v1/user/detail':
            assert request.headers['authorization'] == 'Bearer MOCK-TOKEN'
            return httpx.Response(200, json={'status':'SUCCESS','payload':{'vendor_user_id':'vendor-123','ucc':'C123','active_segments':['CASH']}})
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = GrowwBroker('testgroww', client=client)
        profile = await broker.authenticate({'api_key':'TEST-KEY','api_secret':'supersecret'})
        assert profile.account_id == 'C123'
        assert await broker.verify_session() is True
    assert len(calls) == 3

@pytest.mark.asyncio
async def test_groww_token_works_without_installed_sdk():
    def respond(request):
        assert request.url.path == '/v1/user/detail'
        assert request.headers['authorization'] == 'Bearer ABC'
        return httpx.Response(200, json={'status':'SUCCESS','payload':{'vendor_user_id':'vendor-123'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        b = GrowwBroker('groww1', client=client)
        p = await b.authenticate({'access_token':'Bearer ABC'})
        assert p.account_id == 'vendor-123'

@pytest.mark.asyncio
async def test_groww_token_must_validate_profile():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401,json={'message':'Denied'}))) as client:
        b = GrowwBroker('groww1', client=client)
        with pytest.raises(AuthError):
            await b.authenticate({'access_token':'ABC'})
        assert not b.access_token

@pytest.mark.asyncio
async def test_groww_api_key_missing_approval_token():
    def respond(request):
        return httpx.Response(200,json={'status':'SUCCESS','payload':{}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        b = GrowwBroker('groww1', client=client)
        with pytest.raises(AuthError, match='did not return'):
            await b.authenticate({'api_key':'KEY','api_secret':'SECRET'})
