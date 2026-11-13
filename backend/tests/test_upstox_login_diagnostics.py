"""Upstox auth regression tests using mock transport; no live credentials."""
import asyncio
import httpx
import pytest
from app.brokers.upstox import UpstoxBroker
from app.brokers.base import AuthError


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('pasted', [
    'GOOD_TOKEN', '  GOOD_TOKEN  ', 'Bearer GOOD_TOKEN', 'bearer GOOD_TOKEN',
    '  "GOOD_TOKEN"  ', "'GOOD_TOKEN'",
])
def test_upstox_accepts_common_token_copy_formats(pasted):
    captured=[]
    def handler(req):
        captured.append(req)
        return httpx.Response(200,json={'status':'success','data':{
            'user_id':'TEST-USER','user_name':'Demo','email':'example.invalid'
        }})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=UpstoxBroker('test',client=client)
            profile=await adapter.authenticate({'access_token':pasted})
            assert profile.account_id=='TEST-USER'
            assert captured[0].url.path=='/v2/user/profile'
            assert captured[0].headers['authorization']=='Bearer GOOD_TOKEN'
            assert await adapter.verify_session()
    run(check())


@pytest.mark.parametrize('pasted', ['Bearer ', '{"access_token":"secret"}', 'AAA BBB'])
def test_upstox_rejects_malformed_paste_without_http_request(pasted):
    def handler(req):
        raise AssertionError('Should not call external API for malformed token')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=UpstoxBroker('test',client=client)
            with pytest.raises(AuthError):
                await adapter.authenticate({'access_token':pasted})
    run(check())


@pytest.mark.parametrize('status,code,hint', [
    (401,'UDAPI100050','Invalid or expired access token'),
    (403,'UDAPI100067','extended token'),
    (403,'UDAPI100058','No active trading segments'),
])
def test_upstox_preserves_broker_error_code_but_not_secrets(status,code,hint):
    token='SUPERSENSITIVE_TOKEN_XXXXXXXXXXXXXXXX'
    def handler(req):
        return httpx.Response(status,json={'status':'error','errors':[
            {'errorCode':code,'message':'Error: ' + token}
        ]})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=UpstoxBroker('test',client=client)
            with pytest.raises(AuthError) as ex:
                await adapter.authenticate({'access_token':token})
            msg=str(ex.value)
            assert code in msg and hint in msg and f'HTTP {status}' in msg
            assert token not in msg
            assert adapter.access_token==''
    run(check())


def test_upstox_http_401_without_json_still_shows_help():
    def handler(req):return httpx.Response(401,text='Unauthorized')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=UpstoxBroker('test',client=client)
            with pytest.raises(AuthError,match='Upstox HTTP 401'):
                await adapter.authenticate({'access_token':'TOKEN'})
    run(check())
