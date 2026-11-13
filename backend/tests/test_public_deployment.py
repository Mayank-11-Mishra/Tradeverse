"""Production authentication, preflight and WebSocket ticket regression tests.

Never use broker credentials or submit real orders in tests.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime,timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api import owner_security as sec
from app.api import server


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('TRADEVERSE_SESSION_SECRET',secrets.token_urlsafe(48))
    monkeypatch.setenv('TRADEVERSE_OWNER_PASSWORD_HASH',sec.password_hash('safe-owner-password-123!'))
    monkeypatch.setenv('PUBLIC_API_URL','https://example.up.railway.app')
    monkeypatch.setenv('FRONTEND_ORIGIN','https://example.github.io')
    monkeypatch.setenv('DATABASE_URL','postgresql+psycopg://user:pass@host:5432/db')
    monkeypatch.setenv('ALLOW_MOCK_BROKER','no')
    monkeypatch.setenv('SAVE_BROKER_TOKENS','no')
    sec.ATTEMPTS.clear(); sec.WS_TICKETS.clear()
    yield
    sec.ATTEMPTS.clear(); sec.WS_TICKETS.clear()


def test_password_hash_and_production_startup(production,monkeypatch):
    assert sec.verify_password('safe-owner-password-123!',__import__('os').environ['TRADEVERSE_OWNER_PASSWORD_HASH'])
    assert not sec.verify_password('wrong',__import__('os').environ['TRADEVERSE_OWNER_PASSWORD_HASH'])
    sec.validate_production_config()
    monkeypatch.delenv('TRADEVERSE_SESSION_SECRET')
    with pytest.raises(RuntimeError,match='SESSION_SECRET'):sec.validate_production_config()


def test_websocket_single_use_ticket_and_no_url_token(production):
    session,_=sec.issue_owner_token()
    claims=sec.verify_owner_token(session)
    ticket=sec.issue_ws_ticket(claims)
    headers={'sec-websocket-protocol':'tradeverse, ticket.'+ticket}
    assert sec.validate_ws_credentials(headers,{})[0]
    assert not sec.validate_ws_credentials(headers,{})[0], 'WebSocket ticket must be one-use'
    another=sec.issue_ws_ticket(claims)
    assert not sec.validate_ws_credentials({'sec-websocket-protocol':'tradeverse, ticket.'+another},{'token':'leak'})[0]
    assert not sec.validate_ws_credentials({'sec-websocket-protocol':'tradeverse, auth.'+session},{})[0]


def test_expired_or_bad_owner_token_denied(production):
    with pytest.raises(HTTPException) as error:sec.verify_owner_token('not-a-token')
    assert error.value.status_code == 401


def test_prod_api_guard_and_owner_login(production):
    async def check():
        transport=httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport,base_url='http://testserver') as client:
            assert (await client.get('/api/accounts')).status_code==401
            assert (await client.get('/api/status')).status_code==401
            assert (await client.get('/api/health')).status_code==200
            bad=await client.post('/api/owner/login',json={'password':'wrong'})
            assert bad.status_code==401
            ok=await client.post('/api/owner/login',json={'password':'safe-owner-password-123!'})
            assert ok.status_code==200
            auth={'Authorization':'Bearer '+ok.json()['access_token']}
            result=await client.get('/api/owner/session',headers=auth)
            assert result.status_code==200 and result.json()['authenticated']
            assert (await client.get('/api/status',headers=auth)).status_code==200
            assert (await client.get('/api/status',headers={'Authorization':'Bearer invalid'})).status_code==401
            # Cross-origin preflight carries no Authorization token; must not return 401.
            preflight=await client.options('/api/accounts',headers={
                'Origin':'http://127.0.0.1:5173',
                'Access-Control-Request-Method':'GET',
                'Access-Control-Request-Headers':'authorization'})
            assert preflight.status_code!=401
    asyncio.run(check())


def test_railway_does_not_fall_back_to_unprotected_local_mode(monkeypatch):
    monkeypatch.delenv('APP_ENV',raising=False)
    monkeypatch.setenv('RAILWAY_SERVICE_ID','railway-test-service')
    assert sec.production()
    with pytest.raises(RuntimeError,match='APP_ENV=production'):
        sec.validate_production_config()
