"""Groww credentials contract: no live accounts or order calls required."""
import hashlib
import json
import httpx
import pytest

from app.brokers.groww import GrowwBroker
from app.brokers.base import AuthError

PROFILE = {'status': 'SUCCESS', 'payload': {'vendor_user_id': 'uuid1', 'ucc': 'ACC123'}}


def make_client(calls):
    def respond(req):
        calls.append(req)
        if req.url.path == '/v1/token/api/access':
            return httpx.Response(200, json={'token': 'EXCHANGED-TOKEN'})
        if req.url.path == '/v1/user/detail':
            assert req.headers['authorization'] == 'Bearer EXCHANGED-TOKEN'
            return httpx.Response(200, json=PROFILE)
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


@pytest.mark.asyncio
async def test_selected_approval_mode_ignores_stale_access_token():
    calls = []
    async with make_client(calls) as client:
        broker = GrowwBroker('test', client=client)
        p = await broker.authenticate({'auth_method': 'api_key', 'access_token': 'EXPIRED',
                                       'api_key': 'Bearer API-KEY', 'api_secret': 'SECRET'})
        assert p.account_id == 'ACC123'
        exchange = calls[0]
        assert exchange.headers['authorization'] == 'Bearer API-KEY'
        data = json.loads(exchange.content)
        assert data['key_type'] == 'approval'
        assert data['checksum'] == hashlib.sha256(('SECRET' + data['timestamp']).encode()).hexdigest()
        assert exchange.headers['x-api-version'] == '1.0'
        assert broker.access_token == 'EXCHANGED-TOKEN'


@pytest.mark.asyncio
async def test_selected_token_mode_ignores_stale_api_keys():
    requests = []
    def respond(req):
        requests.append(req)
        return httpx.Response(200, json=PROFILE)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = GrowwBroker('test', client=client)
        await broker.authenticate({'auth_method': 'token', 'access_token': 'Bearer ACCESS',
                                   'api_key': 'BAD', 'api_secret': 'BAD'})
        assert requests[0].headers['authorization'] == 'Bearer ACCESS'
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_ambiguous_methods_require_explicit_selection():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        broker = GrowwBroker('test', client=client)
        with pytest.raises(AuthError, match='choose one'):
            await broker.authenticate({'access_token': 'OLD', 'api_key': 'NEW', 'api_secret': 'NEW'})


def test_totp_standard_known_vector():
    # RFC 6238 SHA1 at t=59 yields 94287082 (8-digit); last six digits 287082.
    assert GrowwBroker._totp_from_secret('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 59) == '287082'


@pytest.mark.asyncio
async def test_totp_manual_code_token_exchange():
    calls = []
    async with make_client(calls) as client:
        broker = GrowwBroker('test', client=client)
        await broker.authenticate({'auth_method': 'totp', 'totp_key': 'Bearer TOTP-KEY', 'totp_code': '123456'})
        assert calls[0].headers['authorization'] == 'Bearer TOTP-KEY'
        assert json.loads(calls[0].content) == {'key_type': 'totp', 'totp': '123456'}


@pytest.mark.asyncio
async def test_totp_rejects_bad_code_and_secret():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        broker = GrowwBroker('test', client=client)
        with pytest.raises(AuthError, match='exactly six digits'):
            await broker.authenticate({'auth_method': 'totp', 'totp_key': 'TOTP', 'totp_code': '12'})
        with pytest.raises(AuthError, match='Base32'):
            await broker.authenticate({'auth_method': 'totp', 'totp_key': 'TOTP', 'totp_secret': 'bad###'})


@pytest.mark.asyncio
async def test_rejected_approval_extracts_safe_nested_broker_error():
    def respond(req):
        return httpx.Response(403, json={'status': 'FAILURE', 'error': {'code': 'GA005', 'message': 'Approval is pending'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = GrowwBroker('test', client=client)
        with pytest.raises(AuthError, match='GA005: Approval is pending'):
            await broker.authenticate({'auth_method': 'api_key', 'api_key': 'KEY', 'api_secret': 'SECRET'})


@pytest.mark.asyncio
async def test_broker_failure_http_200_is_not_auth_success():
    def respond(req):
        return httpx.Response(200, json={'status': 'FAILURE', 'error': {'code': 'GA005', 'message': 'Key not approved'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = GrowwBroker('test', client=client)
        with pytest.raises(AuthError, match='GA005: Key not approved'):
            await broker.authenticate({'auth_method': 'api_key', 'api_key': 'KEY', 'api_secret': 'SECRET'})


@pytest.mark.asyncio
async def test_sensitive_error_text_suppressed():
    def respond(req):
        return httpx.Response(401, json={'error': {'code': 'GA005', 'message': 'Bearer abcdefghijklmnopqrstuvwxyz012345678901234567890abcd'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        broker = GrowwBroker('test', client=client)
        with pytest.raises(AuthError) as caught:
            await broker.authenticate({'auth_method': 'token', 'access_token': 'EXPIRED'})
        assert 'abcdefghijklmnopqrstuvwxyz' not in str(caught.value)
