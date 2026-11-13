"""Broker OAuth authorization-code exchange (local-only callback, secrets stay server-side).

These are current documented flows, not the legacy Shoonya password/TOTP API.
No tokens or secrets are written to URLs, browser logs, or error messages.
"""
from __future__ import annotations
import hashlib
import json
import re
import logging
from urllib.parse import urlencode
import httpx
from .base import AuthError

CALLBACK_ROOT='http://127.0.0.1:8000/api/auth/callback'
LOG=logging.getLogger('tradeverse.oauth')

def authorization_url(broker:str,credentials:dict,state:str)->str:
    if broker=='fyers':
        return 'https://api-t1.fyers.in/api/v3/generate-authcode?'+urlencode({
            'client_id':credentials['client_id'],'redirect_uri':f'{CALLBACK_ROOT}/fyers',
            'response_type':'code','state':state})
    if broker=='finvasia':
        return 'https://api.shoonya.com/OAuthlogin/authorize/oauth?'+urlencode({'client_id':credentials['client_id']})
    if broker=='flattrade':
        return 'https://auth.flattrade.in/?'+urlencode({'app_key':credentials['api_key']})
    raise ValueError('Unsupported OAuth broker')

def safe_error(payload:dict)->str:
    raw=str(payload.get('emsg') or payload.get('message') or payload.get('error') or '').strip()[:190]
    # Never echo raw access tokens, JWTs, passwords, secrets or request codes.
    if re.search(r'(?i)(bearer\s|access.?token\s*[=:]|secret\s*[=:]|password\s*[=:]|[A-Za-z0-9_-]{50,})',raw):
        return 'Broker rejected authorization (sensitive detail redacted)'
    return re.sub(r'[<>\x00-\x1f]', '', raw)

async def exchange_code(broker:str,credentials:dict,code:str,client:httpx.AsyncClient|None=None)->dict:
    if not code or len(code)>8192:raise AuthError('Broker authorization code is missing or invalid')
    owned=client is None
    http=client or httpx.AsyncClient(timeout=18,follow_redirects=False)
    try:
        if broker=='fyers':
            hashed=hashlib.sha256((credentials['client_id']+':'+credentials['api_secret']).encode()).hexdigest()
            response=await http.post('https://api-t1.fyers.in/api/v3/validate-authcode',json={
                'grant_type':'authorization_code','appIdHash':hashed,'code':code})
        elif broker=='flattrade':
            hashed=hashlib.sha256((credentials['api_key']+code+credentials['api_secret']).encode()).hexdigest()
            response=await http.post('https://authapi.flattrade.in/trade/apitoken',json={
                'api_key':credentials['api_key'],'request_code':code,'api_secret':hashed})
        elif broker=='finvasia':
            hashed=hashlib.sha256((credentials['client_id']+credentials['secret_key']+code).encode()).hexdigest()
            body='jData='+json.dumps({'code':code,'checksum':hashed},separators=(',',':'))
            response=await http.post('https://api.shoonya.com/NorenWClientAPI/GenAcsTok',
                                     content=body,headers={'Content-Type':'text/plain'})
        else:raise ValueError('Unsupported OAuth broker')
        LOG.info('OAuth exchange response broker=%s HTTP=%d',broker,response.status_code)
        if response.status_code>=400:
            detail=''
            try:
                d=response.json()
                if isinstance(d,dict):detail=safe_error(d)
            except (ValueError,TypeError):pass
            raise AuthError(f'{broker} token exchange HTTP {response.status_code}: {detail or "check redirect URI, API entitlement and static IP"}')
        try:data=response.json()
        except ValueError:raise AuthError(f'{broker} token exchange returned an invalid response')
        if not isinstance(data,dict):raise AuthError(f'{broker} token exchange returned unexpected data')
        if data.get('stat')=='Not_Ok' or data.get('s')=='error' or data.get('status') in ('Not_Ok','error'):
            code_id=str(data.get('code',data.get('error_code','unknown')))[:30]
            message=safe_error(data)
            raise AuthError(f'{broker} rejected authentication ({code_id}): {message or "check API dashboard and registered redirect URI"}')
        token=data.get('access_token') if broker=='fyers' else data.get('token') if broker=='flattrade' else data.get('susertoken')
        if not isinstance(token,str) or not token:raise AuthError(f'{broker} did not issue an access token')
        result=dict(credentials)
        result.pop('api_secret',None);result.pop('secret_key',None)
        result['access_token']=token
        if broker in ('flattrade','finvasia'):
            result['user_id']=str(data.get('client') or data.get('uid') or credentials.get('user_id') or '')
            result['account_id']=str(data.get('actid') or result['user_id'])
        return result
    except httpx.RequestError as error:
        raise AuthError(f'{broker} authorization server unavailable ({type(error).__name__})') from error
    finally:
        if owned:await http.aclose()
