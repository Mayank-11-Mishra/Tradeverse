"""Broker HTTP and normalization primitives. No credentials or responses are logged.

Every REST response is checked; an HTTP acknowledgement is not an exchange fill.
"""
from __future__ import annotations
import asyncio
import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
import httpx
from .base import (BrokerAdapter, BrokerError, AuthError, RateLimitError, OrderRejected,
                   OrderUncertain, Instrument, InstrumentKey, Candle, Order, OrderRequest, Position,
                   Holding, Funds, UnsupportedCapability)

IST = ZoneInfo('Asia/Kolkata')

def dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or (isinstance(value,str) and re.fullmatch(r'\d{10,13}',value)):
        n = float(value)
        result = datetime.fromtimestamp(n/(1000 if n>1e11 else 1), tz=timezone.utc)
    elif isinstance(value,str):
        try:
            result = datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            result = None
            for fmt in ('%d-%m-%Y %H:%M:%S','%d/%m/%Y %H:%M:%S','%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    result = datetime.strptime(value,fmt)
                    break
                except ValueError: continue
            if result is None: raise ValueError('Unsupported broker timestamp')
    else: raise ValueError('Unsupported timestamp')
    return result if result.tzinfo else result.replace(tzinfo=IST)

def candles(rows: list, shape: str='list') -> list[Candle]:
    output={}
    for x in rows or []:
        if shape=='noren':
            if x.get('stat','Ok') != 'Ok': continue
            t, o,h,l,c,v,oi = x.get('time'), x.get('into'),x.get('inth'),x.get('intl'),x.get('intc'),x.get('intv',0),x.get('oi')
        elif isinstance(x,dict):
            t=x.get('date',x.get('time',x.get('timestamp')))
            o=x.get('open', x.get('o'));h=x.get('high',x.get('h'));l=x.get('low',x.get('l'));c=x.get('close',x.get('c'));v=x.get('volume',x.get('v',0));oi=x.get('oi')
        else:
            if len(x)<5: continue
            t,o,h,l,c=x[:5];v=x[5] if len(x)>5 else 0;oi=x[6] if len(x)>6 else None
        if any(z is None for z in (t,o,h,l,c)):continue
        bar=Candle(dt(t),float(o),float(h),float(l),float(c),float(v or 0),float(oi) if oi not in (None,'') else None)
        if min(bar.open,bar.high,bar.low,bar.close)<0 or bar.high<max(bar.open,bar.close,bar.low) or bar.low>min(bar.open,bar.close):
            continue
        output[bar.ts]=bar
    return sorted(output.values(), key=lambda v:v.ts)

def normalize_order(x:dict, key_fields=('exchange','tradingsymbol','trading_symbol'), order_id_field='order_id', tag_field='tag') -> Order:
    key=InstrumentKey(x.get('exchange',x.get('exch','NSE')),
        next((str(x[k]) for k in key_fields if x.get(k)),str(x.get('symbol',x.get('tsym','UNKNOWN')))),
        str(x.get('segment','EQ')))
    typ=str(x.get('order_type',x.get('prctyp','MARKET'))).upper()
    side=str(x.get('transaction_type',x.get('trantype','BUY'))).upper()
    side={'B':'BUY','S':'SELL','1':'BUY','-1':'SELL'}.get(side,side)
    request=OrderRequest(key=key,side=side,qty=int(float(x.get('quantity',x.get('qty',0)) or 0)),
        order_type=typ,product=str(x.get('product',x.get('prd','MIS'))),
        price=float(x.get('price',x.get('prc',0)) or 0),
        client_order_id=str(x.get(tag_field,'') or ''))
    return Order(str(x.get(order_id_field,x.get('norenordno',x.get('id','')))),request,
                 str(x.get('status',x.get('order_status','UNKNOWN'))),
                 int(float(x.get('filled_quantity',x.get('fillshares',0)) or 0)),
                 float(x.get('average_price',x.get('avgprc',0)) or 0),
                 str(x.get(tag_field,'') or ''),str(x.get('status_message',x.get('remarks','')) or ''))

def normalize_positions(rows: list, broker: str='') -> list[Position]:
    result=[]
    for x in rows or []:
        if not isinstance(x,dict): continue
        key=InstrumentKey(str(x.get('exchange',x.get('exch','NSE'))),str(x.get('tradingsymbol',x.get('trading_symbol',x.get('symbol',x.get('tsym',''))))))
        q=x.get('quantity', x.get('qty',x.get('netqty',x.get('netQty',0))))
        result.append(Position(key,int(float(q or 0)),float(x.get('average_price',x.get('avgprc',x.get('avgPrice',0))) or 0),
                               float(x.get('last_price',x.get('lp',x.get('ltp',0))) or 0),float(x.get('pnl',x.get('rpnl',0)) or 0),
                               str(x.get('product',x.get('prd','MIS')))))
    return result

def normalize_holdings(rows: list) -> list[Holding]:
    result=[]
    for x in rows or []:
        if not isinstance(x,dict): continue
        result.append(Holding(InstrumentKey(str(x.get('exchange',x.get('exch','NSE'))),
            str(x.get('tradingsymbol',x.get('trading_symbol',x.get('symbol',x.get('tsym','')))))),
            int(float(x.get('quantity',x.get('qty',x.get('holdqty',0))) or 0)),
            float(x.get('average_price',x.get('avgprc',0)) or 0),float(x.get('last_price',x.get('lp',0)) or 0)))
    return result


def _safe_broker_detail(info: Any) -> str:
    """Extract a short human-readable error, never expose broker secrets in UI."""
    if not isinstance(info, dict):
        return ''
    err = info.get('error')
    nested = err if isinstance(err, dict) else {}
    candidate = nested.get('message') or info.get('message') or info.get('emsg') or (err if isinstance(err, str) else '')
    code = nested.get('code') or info.get('code')
    text = str(candidate or '').strip()
    # Do not pass through full broker responses, bearer credentials or opaque keys.
    if re.search(r'(?i)(bearer\s|access[_ -]?token\s*[=:]|api[_ -]?secret\s*[=:]|password\s*[=:]|[A-Za-z0-9_\-]{48,})', text):
        text = ''
    label = str(code) if isinstance(code, str) and re.fullmatch(r'[A-Za-z]{1,8}[0-9]{2,6}', code) else ''
    return (f'{label}: ' if label and text else label) + text[:180]

class HTTPBroker(BrokerAdapter):
    base_url = ''
    def __init__(self,account_id:str, client: httpx.AsyncClient|None=None):
        super().__init__(account_id)
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(20,connect=8), follow_redirects=False)
        self.access_token = ''
        self._instruments:dict[tuple[str,str],Instrument]={}
        self._orders:dict[str,OrderRequest]={}
    async def close(self):
        if self._owned_client: await self.client.aclose()
    async def logout(self):
        self.access_token=''
        self._instruments.clear()
    async def is_session_valid(self): return bool(self.access_token)
    def remember_instruments(self, items:list[Instrument]):
        for item in items:
            self._instruments[(item.key.exchange,item.key.symbol)]=item
        return items
    def token_for(self,key:InstrumentKey, allow_symbol=False):
        item=self._instruments.get((key.exchange,key.symbol))
        if item: return item.broker_token
        if allow_symbol: return key.symbol
        raise BrokerError(f'Instrument {key.exchange}:{key.symbol} is not mapped. Sync instrument master first.')
    async def _http(self,method,path,*,params=None,json_body=None,form=None,content=None,headers=None,base=None,order=False,raw=False):
        url=(base or self.base_url).rstrip('/')+'/'+path.lstrip('/')
        try:
            response=await self.client.request(method,url,params=params,json=json_body,data=form,content=content,headers=headers)
        except (httpx.TimeoutException,httpx.TransportError) as ex:
            # Critically, order submission timeout may occur AFTER exchange acceptance.
            if order: raise OrderUncertain('Transport failure; reconcile before further orders') from ex
            raise BrokerError(f'Broker request unavailable: {type(ex).__name__}') from ex
        if response.status_code in (401,403):
            # Preserve Upstox's published error code without echoing an access token,
            # response body, or untrusted error text into the browser.
            if getattr(self,'broker_id','') == 'upstox':
                code = ''
                try:
                    payload = response.json()
                    if isinstance(payload,dict):
                        errors=payload.get('errors',[])
                        details=errors[0] if isinstance(errors,list) and errors and isinstance(errors[0],dict) else payload
                        candidate=details.get('errorCode') or details.get('error_code') or details.get('code')
                        if isinstance(candidate,str) and re.fullmatch(r'UDAPI[0-9]{2,12}', candidate):
                            code=candidate
                except ValueError:
                    pass
                hints={
                    'UDAPI100050':'Invalid or expired access token. Generate a fresh live access_token in Upstox Developer Apps.',
                    'UDAPI100067':'An extended token cannot access this endpoint. Use a regular OAuth access_token.',
                    'UDAPI100058':'No active trading segments. Check activation in your Upstox account.',
                    'UDAPI100016':'Invalid credentials. Verify the token belongs to your Upstox developer app.',
                    'UDAPI100096':'Invalid API key. Check your Upstox developer app configuration.',
                }
                default=('The token was rejected. Try a new live OAuth access_token from Upstox Developer Apps.'
                         if response.status_code==401 else
                         'Upstox denied profile access. Verify the token type and app/account permissions.')
                code_display=f' ({code})' if code else ''
                raise AuthError(f'Upstox HTTP {response.status_code}{code_display}: {hints.get(code,default)}')
            broker=getattr(self,'broker_id','Broker')
            try:
                detail=_safe_broker_detail(response.json())
            except (ValueError,TypeError):
                detail=''
            if broker=='groww':
                hint=('Use a fresh trading access token (Groww tokens expire at 6:00 AM IST).'
                      if response.status_code==401 else
                      'Verify your Groww Trading API subscription and API-key daily approval.')
                raise AuthError(f'Groww HTTP {response.status_code}: {detail or hint}')
            raise AuthError(f'{broker} HTTP {response.status_code}: {detail or "Session expired, token invalid, or API access denied"}')
        if response.status_code == 429:
            raise RateLimitError('Broker API rate limit',float(response.headers.get('Retry-After',0) or 0))
        if response.status_code >= 500:
            if order: raise OrderUncertain(f'Broker returned {response.status_code}; reconcile')
            raise BrokerError(f'Broker server returned {response.status_code}')
        if raw:
            if response.is_error:raise BrokerError(f'Broker HTTP {response.status_code}')
            return response.text
        try: result=response.json()
        except ValueError: raise BrokerError('Invalid broker JSON response')
        if response.is_error:
            detail=_safe_broker_detail(result) or f'Broker request failed (HTTP {response.status_code})'
            if order:raise OrderRejected(detail)
            if getattr(self,'broker_id','')=='groww' and response.status_code in (400,422):
                if path.startswith('/v1/token/api/access'):
                    raise AuthError(f'Groww HTTP {response.status_code}: {detail}')
            raise BrokerError(detail)
        if isinstance(result,dict):
            status=str(result.get('status',result.get('stat',result.get('s','')))).lower()
            if status in ('error','failure','not_ok','false') or (result.get('code') not in (None,0,200,201,1101,1102,1103,1605) and status=='error'):
                message=_safe_broker_detail(result) or 'Broker rejected request'
                if 'session' in message.lower() or 'token' in message.lower() or (getattr(self,'broker_id','')=='groww' and path.startswith('/v1/token/api/access')):raise AuthError(message)
                if order:raise OrderRejected(message)
                raise BrokerError(message)
        return result
