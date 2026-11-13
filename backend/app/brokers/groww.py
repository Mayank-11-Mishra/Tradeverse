"""Groww Trade API v1 REST, officially documented GrowwFeed and backtesting SDK.
https://groww.in/trade-api/docs/python-sdk/
"""
from __future__ import annotations
import csv,io,asyncio,hashlib,time,base64,hmac,struct,re
from .base import *
from .common import HTTPBroker,candles,normalize_order,normalize_positions,normalize_holdings,dt

@register_adapter
class GrowwBroker(HTTPBroker):
    broker_id='groww';base_url='https://api.groww.in'
    capabilities=frozenset({Capability.INSTRUMENT_MASTER,Capability.HISTORICAL_CANDLES,Capability.LIVE_STREAM,
        Capability.MARKET_DEPTH,Capability.PLACE_ORDER,Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,
        Capability.ORDER_TAG,Capability.POSITIONS,Capability.HOLDINGS})
    verification='official-docs-implemented; live-untested'
    def _headers(self):return {'Authorization':f'Bearer {self.access_token}','X-API-VERSION':'1.0','Accept':'application/json'}
    async def _call(self,method,path,**kw):
        d=await self._http(method,path,headers=self._headers(),**kw)
        return d.get('payload',d) if isinstance(d,dict) else d
    @staticmethod
    def _totp_from_secret(secret: str, now: int | None = None) -> str:
        """RFC 6238 SHA-1 / 30 second / 6 digit OTP for a Groww TOTP secret."""
        try:
            normalized = re.sub(r'\s+', '', secret).upper()
            if not normalized or not re.fullmatch(r'[A-Z2-7]+', normalized):
                raise ValueError('bad base32')
            key = base64.b32decode(normalized + '=' * (-len(normalized) % 8), casefold=True)
            counter = (int(time.time()) if now is None else int(now)) // 30
            digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
            offset = digest[-1] & 0xf
            code = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1_000_000
            return f'{code:06d}'
        except (ValueError, TypeError, base64.binascii.Error) as exc:
            raise AuthError('Groww TOTP secret must be the Base32 secret supplied when creating a TOTP token') from exc

    async def authenticate(self, credentials):
        """Authenticate using an explicitly selected Groww token, approval key, or TOTP key.

        A pasted old token must never shadow a fresh API key and secret. Only a
        broker-verified token can unlock the terminal. No credentials are logged.
        """
        access_token = str(credentials.get('access_token') or '').strip()
        if access_token.lower().startswith('bearer '):
            access_token = access_token[7:].strip()
        api_key = str(credentials.get('api_key') or '').strip()
        if api_key.lower().startswith('bearer '):
            api_key = api_key[7:].strip()
        api_secret = str(credentials.get('api_secret') or '').strip()
        otp_key = str(credentials.get('totp_key') or '').strip()
        if otp_key.lower().startswith('bearer '):
            otp_key = otp_key[7:].strip()
        otp_secret = str(credentials.get('totp_secret') or '').strip()
        otp_code = str(credentials.get('totp_code') or '').strip()

        mode = str(credentials.get('auth_method') or '').strip().lower()
        if not mode:
            modes = [m for m, present in (
                ('token', bool(access_token)),
                ('api_key', bool(api_key and api_secret)),
                ('totp', bool(otp_key and (otp_secret or otp_code))),
            ) if present]
            if len(modes) != 1:
                raise AuthError('Groww: choose one authentication method (Access Token, API Key + Secret, or TOTP)')
            mode = modes[0]
        if mode not in ('token', 'api_key', 'totp'):
            raise AuthError('Groww authentication method must be token, api_key, or totp')

        if mode == 'token':
            if not access_token:
                raise AuthError('Groww access token is missing. Generate a fresh token in Groww Trading APIs')
            token = access_token
        else:
            if mode == 'api_key':
                if not api_key or not api_secret:
                    raise AuthError('Groww API Key + Secret mode requires both fields and daily key approval in Groww Cloud')
                timestamp = str(int(time.time()))
                payload = {
                    'key_type': 'approval',
                    'checksum': hashlib.sha256((api_secret + timestamp).encode('utf-8')).hexdigest(),
                    'timestamp': timestamp,
                }
                auth_key = api_key
            else:
                auth_key = otp_key or api_key
                if not auth_key or not (otp_secret or otp_code):
                    raise AuthError('Groww TOTP mode requires the TOTP token and its secret or current six-digit code')
                if otp_code and not re.fullmatch(r'[0-9]{6}', otp_code):
                    raise AuthError('Groww TOTP code must be exactly six digits')
                payload = {
                    'key_type': 'totp',
                    'totp': otp_code or self._totp_from_secret(otp_secret),
                }
            response = await self._http('POST', '/v1/token/api/access',
                headers={'Authorization': f'Bearer {auth_key}',
                         'Content-Type': 'application/json',
                         'Accept': 'application/json', 'X-API-VERSION': '1.0'},
                json_body=payload)
            body = response.get('payload', response) if isinstance(response, dict) else {}
            token = body.get('token') if isinstance(body, dict) else None
            if not isinstance(token, str) or not token.strip():
                raise AuthError('Groww did not return an access token. Check API subscription, daily key approval, and credential type')
            token = token.strip()

        self.access_token = token
        try:
            d = await self._call('GET', '/v1/user/detail')
            if not isinstance(d, dict) or not (d.get('vendor_user_id') or d.get('ucc')):
                raise AuthError('Groww profile returned no account ID. Confirm token type and Trading API entitlement')
        except BrokerError:
            self.access_token = ''
            raise
        return Profile(str(d.get('ucc') or d['vendor_user_id']), d.get('name',''), d.get('email',''))
    async def verify_session(self):
        if not self.access_token: return False
        d = await self._call('GET', '/v1/user/detail')
        return isinstance(d, dict) and bool(d.get('vendor_user_id') or d.get('ucc'))
    async def get_instruments(self):
        raw=await self._http('GET','/instruments/instrument.csv',base='https://growwapi-assets.groww.in',raw=True)
        output=[]
        if not hasattr(self,'_groww_symbols'):self._groww_symbols={}
        for x in csv.DictReader(io.StringIO(raw)):
            try:
                if not x.get('trading_symbol'):continue
                typ=x.get('instrument_type','EQ')
                self._groww_symbols[(x['exchange'],x['trading_symbol'])]=x.get('groww_symbol','')
                output.append(Instrument(InstrumentKey(x['exchange'],x['trading_symbol'],typ),str(x['exchange_token']),
                    x.get('name',''),int(float(x.get('lot_size',1) or 1)),float(x.get('tick_size',.05) or .05),
                    dt(x['expiry_date']) if x.get('expiry_date') else None,
                    float(x['strike_price']) if x.get('strike_price') else None,typ if typ in ('CE','PE') else None,
                    x.get('underlying_symbol')))
            except (ValueError,KeyError):continue
        return self.remember_instruments(output)
    async def get_historical_data(self,key,interval,start,end):
        try:from growwapi import GrowwAPI
        except ImportError as e:raise UnsupportedCapability('Install growwapi for new Groww historical candles') from e
        mapping={'1m':'CANDLE_INTERVAL_MIN_1','2m':'CANDLE_INTERVAL_MIN_2','3m':'CANDLE_INTERVAL_MIN_3',
                 '5m':'CANDLE_INTERVAL_MIN_5','10m':'CANDLE_INTERVAL_MIN_10','15m':'CANDLE_INTERVAL_MIN_15',
                 '30m':'CANDLE_INTERVAL_MIN_30','1h':'CANDLE_INTERVAL_HOUR_1','4h':'CANDLE_INTERVAL_HOUR_4',
                 '1d':'CANDLE_INTERVAL_DAY','1w':'CANDLE_INTERVAL_WEEK','1mo':'CANDLE_INTERVAL_MONTH'}
        if interval not in mapping:raise UnsupportedCapability('Groww interval unsupported')
        groww=GrowwAPI(self.access_token)
        sym=self._instruments.get((key.exchange,key.symbol))
        groww_symbol=getattr(self,'_groww_symbols',{}).get((key.exchange,key.symbol))
        if not groww_symbol:
            if key.symbol.startswith(key.exchange+'-'):
                groww_symbol=key.symbol
            elif key.segment in ('EQ','IDX','INDEX'):
                groww_symbol=f'{key.exchange}-{key.symbol}'
            elif sym and sym.expiry and sym.underlying and sym.option_type:
                groww_symbol=f'{key.exchange}-{sym.underlying}-{sym.expiry.strftime("%d%b%y")}-{int(sym.strike) if float(sym.strike or 0).is_integer() else sym.strike}-{sym.option_type}'
            else:
                raise UnsupportedCapability('Groww derivative history requires a Groww symbol from current instrument master')
        response=await asyncio.to_thread(groww.get_historical_candles,exchange=key.exchange,
            segment='CASH' if key.segment in ('EQ','IDX','INDEX') else 'FNO',groww_symbol=groww_symbol,
            start_time=start.strftime('%Y-%m-%d %H:%M:%S'),end_time=end.strftime('%Y-%m-%d %H:%M:%S'),
            candle_interval=getattr(groww,mapping[interval]))
        return candles(response.get('candles',[]))
    async def place_order(self,req):
        seg='FNO' if req.key.segment in ('FNO','FUT','OPT','CE','PE') else 'CASH'
        payload={'trading_symbol':req.key.symbol,'quantity':req.qty,'price':req.price or 0,
           'trigger_price':req.trigger_price or 0,'validity':req.validity,'exchange':req.key.exchange,
           'segment':seg,'product':req.product,'order_type':{'SL_M':'SL_M'}.get(req.order_type,req.order_type),
           'transaction_type':req.side,'order_reference_id':req.client_order_id[:20]}
        d=await self._call('POST','/v1/order/create',json_body=payload,order=True)
        oid=str(d.get('groww_order_id',''))
        if not oid:raise OrderUncertain('Groww order acknowledgement missing ID')
        self._orders[oid]=req
        return oid
    async def modify_order(self,order_id,**changes):
        original=self._orders.get(order_id)
        if not original:raise BrokerError('Order not in session; load order details')
        payload={'groww_order_id':order_id,'segment':'FNO' if original.key.segment in ('OPT','FUT','CE','PE','FNO') else 'CASH'}
        for k in ('quantity','price','trigger_price','order_type','validity'):
            source='qty' if k=='quantity' else k
            if source in changes:payload[k]=changes[source]
        await self._call('POST','/v1/order/modify',json_body=payload,order=True)
    async def cancel_order(self,order_id):
        original=self._orders.get(order_id)
        if not original:raise BrokerError('Order not in this session; cannot safely infer segment')
        seg='FNO' if original.key.segment in ('OPT','FUT','CE','PE','FNO') else 'CASH'
        await self._call('POST','/v1/order/cancel',json_body={'groww_order_id':order_id,'segment':seg},order=True)
    async def get_orders(self):
        rows=[]
        for segment in ('CASH','FNO'):
            d=await self._call('GET','/v1/order/list',params={'segment':segment,'page':0,'page_size':100})
            rows.extend(d.get('order_list',[]))
        return [normalize_order(x,order_id_field='groww_order_id',tag_field='order_reference_id') for x in rows]
    async def get_positions(self):
        positions=[]
        for seg in ('CASH','FNO'):
            d=await self._call('GET','/v1/positions/user',params={'segment':seg})
            positions.extend(d.get('positions',[]))
        return normalize_positions(positions)
    async def get_holdings(self):
        d=await self._call('GET','/v1/holdings/user')
        return normalize_holdings(d.get('holdings',[]))
    async def get_funds(self):
        # Until a confirmed funds endpoint is available, do not guess balances.
        raise UnsupportedCapability('Groww funds response mapping requires live API validation')
    def subscribe_market_data(self,keys):
        from .streams import groww_stream
        return groww_stream(self,keys)
