"""Upstox v3 trading/history, v2 profile/options/instruments, SDK v3 live feed.
Docs: https://upstox.com/developer/api-documentation/
"""
from __future__ import annotations
from datetime import datetime,timezone
import os
import re
from urllib.parse import quote
from .base import *
from .common import HTTPBroker,candles,normalize_order,normalize_positions,normalize_holdings

@register_adapter
class UpstoxBroker(HTTPBroker):
    broker_id='upstox';base_url='https://api.upstox.com'
    capabilities=frozenset({Capability.INSTRUMENT_MASTER,Capability.HISTORICAL_CANDLES,Capability.LIVE_STREAM,
        Capability.MARKET_DEPTH,Capability.OPTION_CHAIN,Capability.OPTION_GREEKS,Capability.PLACE_ORDER,
        Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,Capability.ORDER_TAG,Capability.POSITIONS,
        Capability.HOLDINGS,Capability.FUNDS,Capability.TRADEBOOK})
    verification='official-docs-implemented; live-untested'
    read_only=False
    _private_capabilities={Capability.PLACE_ORDER,Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,
                           Capability.POSITIONS,Capability.HOLDINGS,Capability.FUNDS,Capability.TRADEBOOK}
    def supports(self,capability):
        return super().supports(capability) and not (self.read_only and capability in self._private_capabilities)
    async def _verify_read_only(self):
        # Analytics tokens are validated on a documented MARKET DATA endpoint;
        # the Profile endpoint may be inaccessible to such tokens.
        quote=await self._call('GET','/v3/market-quote/ltp',params={'instrument_key':'NSE_INDEX|Nifty 50'})
        if not isinstance(quote,dict) or not quote:
            raise AuthError('Analytics token did not return a valid market-data response')
        return True

    @staticmethod
    def _clean_access_token(value):
        """Normalize tokens copied from the Upstox console or a Bearer header.

        Never log or return the token in an error response.
        """
        if not isinstance(value,str):
            raise AuthError('Paste the Upstox OAuth access_token as text.')
        value=value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[:1]) and len(value)>1:
            value=value[1:-1].strip()
        value=re.sub(r'^Bearer\s+', '', value, flags=re.IGNORECASE).strip()
        if not value or value.lower()=='bearer':
            raise AuthError('Upstox access token is empty. Generate one in Upstox Developer Apps.')
        if value.startswith('{') or re.search(r'\s',value):
            raise AuthError('Paste only the access_token value, not a JSON object, authorization code or extra text.')
        return value
    # Verified index instrument keys from official Upstox instrument API. These are
    # stable market-data identifiers, not synthetic prices.
    INDEX_TOKENS = {
        ('NSE','NIFTY'): 'NSE_INDEX|Nifty 50',
        ('NSE','NIFTY 50'): 'NSE_INDEX|Nifty 50',
        ('NSE','BANKNIFTY'): 'NSE_INDEX|Nifty Bank',
        ('NSE','NIFTY BANK'): 'NSE_INDEX|Nifty Bank',
        ('NSE','FINNIFTY'): 'NSE_INDEX|Nifty Fin Service',
        ('NSE','MIDCPNIFTY'): 'NSE_INDEX|NIFTY MID SELECT',
        ('BSE','SENSEX'): 'BSE_INDEX|SENSEX',
    }
    def token_for(self,key,allow_symbol=False):
        if '|' in key.symbol:
            return key.symbol
        if key.segment.upper() in ('IDX','INDEX'):
            known=self.INDEX_TOKENS.get((key.exchange.upper(),key.symbol.upper()))
            if known:return known
        return super().token_for(key,allow_symbol=allow_symbol)
    def _headers(self):return {'Accept':'application/json','Authorization':f'Bearer {self.access_token}'}
    async def _call(self,method,path,**kw):
        headers=self._headers()
        # Upstox Algo Trading Apps may require the registered Algo Name in
        # X-Algo-Name on order operations; never invent a broker-issued name.
        if kw.get('order') and os.getenv('UPSTOX_ALGO_NAME','').strip():
            headers['X-Algo-Name']=os.environ['UPSTOX_ALGO_NAME'].strip()
        r=await self._http(method,path,headers=headers,**kw)
        return r.get('data',r) if isinstance(r,dict) else r
    async def authenticate(self,credentials):
        self.read_only=str(credentials.get('token_type','oauth')).lower()=='analytics'
        raw_token=credentials.get('access_token','')
        self.access_token=self._clean_access_token(raw_token) if raw_token else ''
        if not self.access_token:
            values=['code','client_id','client_secret','redirect_uri']
            if not all(credentials.get(k) for k in values):raise AuthError('Need access_token or official OAuth code, client_id, client_secret, redirect_uri')
            d=await self._http('POST','/v2/login/authorization/token',form={**{k:credentials[k] for k in values},'grant_type':'authorization_code'})
            self.access_token=self._clean_access_token(d['access_token'])
        if self.read_only:
            try: await self._verify_read_only()
            except Exception:self.access_token='';raise
            return Profile(self.account_id,'Upstox Analytics (data only)','')
        try: x=await self._call('GET','/v2/user/profile')
        except Exception:self.access_token='';raise
        return Profile(str(x.get('user_id',self.account_id)),x.get('user_name',''),x.get('email',''))
    async def verify_session(self):
        if not self.access_token:return False
        if self.read_only:return await self._verify_read_only()
        info=await self._call('GET','/v2/user/profile')
        return isinstance(info,dict) and bool(info.get('user_id'))
    async def get_instruments(self,query='',exchange=''):
        # Upstox instrument search is query-based, unlike the gzip BOD bulk file.
        if not query:raise ValueError('Upstox instrument search needs query; for entire master use official BOD files')
        p={'query':query,'records':30}
        if exchange:p['exchanges']=exchange
        d=await self._call('GET','/v2/instruments/search',params=p)
        rows=d if isinstance(d,list) else d.get('instruments',d.get('data',[]))
        items=[]
        for x in rows:
            if not isinstance(x,dict):continue
            symbol=x.get('trading_symbol',x.get('tradingsymbol',''));ex=x.get('exchange',x.get('segment','NSE').split('_')[0])
            if not symbol:continue
            typ=x.get('instrument_type','EQ')
            segment='IDX' if typ=='INDEX' or str(x.get('segment','')).endswith('_INDEX') else typ
            items.append(Instrument(InstrumentKey(ex,symbol,segment),str(x.get('instrument_key','')),
                                    x.get('name',''),int(x.get('lot_size',1) or 1),float(x.get('tick_size',.05) or .05)))
        return self.remember_instruments(items)
    async def get_historical_data(self,key,interval,start,end):
        units={'1d':('days',1),'1w':('weeks',1),'1mo':('months',1),'1h':('hours',1)}
        if interval in units:unit,n=units[interval]
        else:
            n=int(interval[:-1]) if interval.endswith('m') and interval[:-1].isdigit() else 0
            if n<1 or n>300:raise UnsupportedCapability('Unsupported Upstox candle interval')
            unit='minutes'
        token=self.token_for(key,allow_symbol='|' in key.symbol)
        path='/v3/historical-candle/{}/{}/{}/{}/{}'.format(quote(token,safe=''),unit,n,end.date().isoformat(),start.date().isoformat())
        d=await self._call('GET',path)
        result=candles(d.get('candles',[]))
        # Historical V3 data and the current trading-day bars use separate endpoints.
        # A missing intraday response must not erase valid older history.
        if end.astimezone(timezone.utc).date() >= datetime.now(timezone.utc).date() and start.date()<=datetime.now(timezone.utc).date():
            try:
                today=await self._call('GET',f'/v3/historical-candle/intraday/{quote(token,safe="")}/{unit}/{n}')
                result=candles([*d.get('candles',[]),*today.get('candles',[])])
            except (BrokerError,ValueError,KeyError,TypeError):
                pass
        return result
    async def resolve_option_underlying(self,underlying):
        """Upstox expects underlying instrument_key, not NIFTY display symbol."""
        raw=underlying.strip()
        if '|' in raw:return raw
        alias={
            'NIFTY':'NSE_INDEX|Nifty 50','NIFTY 50':'NSE_INDEX|Nifty 50',
            'BANKNIFTY':'NSE_INDEX|Nifty Bank','NIFTY BANK':'NSE_INDEX|Nifty Bank',
            'FINNIFTY':'NSE_INDEX|Nifty Fin Service',
            'MIDCPNIFTY':'NSE_INDEX|NIFTY MID SELECT',
            'SENSEX':'BSE_INDEX|SENSEX',
        }
        if raw.upper() in alias:return alias[raw.upper()]
        matches=await self._call('GET','/v2/instruments/search',params={'query':raw,'records':30})
        if not isinstance(matches,list):matches=matches.get('data',[]) if isinstance(matches,dict) else []
        exact=[x for x in matches if str(x.get('trading_symbol','')).upper()==raw.upper()
               and str(x.get('segment','')).endswith(('_EQ','_INDEX'))]
        if not exact:raise UnsupportedCapability('Cannot resolve option underlying. Search an exact underlying instrument first.')
        return exact[0]['instrument_key']

    async def get_option_expiries(self,underlying):
        key=await self.resolve_option_underlying(underlying)
        result=await self._call('GET','/v2/option/contract',params={'instrument_key':key})
        rows=result if isinstance(result,list) else result.get('data',[]) if isinstance(result,dict) else []
        expiries=sorted({str(x.get('expiry'))[:10] for x in rows if isinstance(x,dict) and x.get('expiry')})
        return expiries

    async def get_option_chain(self,underlying,expiry):
        key=await self.resolve_option_underlying(underlying)
        result=await self._call('GET','/v2/option/chain',params={'instrument_key':key,'expiry_date':str(expiry)})
        return result if isinstance(result,list) else result.get('data',[]) if isinstance(result,dict) else []
    async def get_ltp_quotes(self, keys):
        """Read-only REST snapshot fallback; never label these as streaming ticks."""
        token_map={self.token_for(k):k for k in keys}
        if not token_map:return []
        rows=await self._call('GET','/v3/market-quote/ltp',params={'instrument_key':','.join(token_map)})
        out=[]
        for row in (rows or {}).values():
            if not isinstance(row,dict):continue
            key=token_map.get(str(row.get('instrument_token','')))
            if key is None:continue
            try:
                ltp=float(row.get('last_price'))
                if ltp<=0:continue
                previous=float(row['cp']) if row.get('cp') is not None else None
            except (ValueError,TypeError):continue
            out.append({'key':{'exchange':key.exchange,'symbol':key.symbol,'segment':key.segment},
                        'ltp':ltp,'previous_close':previous,'source':'snapshot',
                        'ts':datetime.now(timezone.utc).isoformat()})
        return out

    async def place_order(self,req):
        if req.product not in ('MIS','CNC','NRML','MTF'):raise UnsupportedCapability('Unsupported product')
        product={'MIS':'I','CNC':'D','NRML':'D','MTF':'MTF'}[req.product]
        token=self.token_for(req.key,allow_symbol='|' in req.key.symbol)
        payload={'quantity':req.qty,'product':product,'validity':req.validity,'price':req.price or 0,
            'tag':req.client_order_id,'instrument_token':token,'order_type':{'SL_M':'SL-M'}.get(req.order_type,req.order_type),
            'transaction_type':req.side,'disclosed_quantity':0,'trigger_price':req.trigger_price or 0,
            'is_amo':False,'slice':False,'market_protection':-1}
        d=await self._call('POST','/v3/order/place',base='https://api-hft.upstox.com',json_body=payload,order=True)
        ids=d.get('order_ids') or ([d['order_id']] if d.get('order_id') else [])
        if len(ids)!=1:raise OrderUncertain('Unexpected multi-order response, reconcile orderbook')
        oid=str(ids[0]);self._orders[oid]=req
        return oid
    async def modify_order(self,order_id,**changes):
        original=self._orders.get(order_id)
        if not original:raise BrokerError('Order not in this session; fetch order details first')
        d={'order_id':order_id,'quantity':original.qty,'validity':original.validity,
           'price':original.price or 0,'order_type':{'SL_M':'SL-M'}.get(original.order_type,original.order_type),
           'trigger_price':original.trigger_price or 0,'market_protection':-1}
        for a,b in {'qty':'quantity','price':'price','order_type':'order_type','trigger_price':'trigger_price','validity':'validity'}.items():
            if a in changes:d[b]=changes[a]
        await self._call('PUT','/v3/order/modify',base='https://api-hft.upstox.com',json_body=d,order=True)
    async def cancel_order(self,order_id):
        await self._call('DELETE','/v3/order/cancel',base='https://api-hft.upstox.com',params={'order_id':order_id},order=True)
    async def get_orders(self):
        d=await self._call('GET','/v2/order/retrieve-all')
        return [normalize_order(x,order_id_field='order_id',tag_field='tag') for x in (d if isinstance(d,list) else [])]
    async def get_tradebook(self):
        rows=await self._call('GET','/v2/order/trades/get-trades-for-day')
        return rows if isinstance(rows,list) else []
    async def get_positions(self):return normalize_positions(await self._call('GET','/v2/portfolio/short-term-positions'))
    async def get_holdings(self):return normalize_holdings(await self._call('GET','/v2/portfolio/long-term-holdings'))
    async def get_funds(self):
        d=await self._call('GET','/v2/user/get-funds-and-margin')
        x=d.get('equity',d);a=float(x.get('available_margin',0) or 0);u=float(x.get('used_margin',0) or 0)
        return Funds(a,u,a+u)
    def subscribe_market_data(self,keys):
        from .streams import upstox_stream
        return upstox_stream(self,keys)
