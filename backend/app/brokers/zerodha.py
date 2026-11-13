"""Zerodha Kite Connect v3 adapter: https://kite.trade/docs/connect/v3/"""
from __future__ import annotations
import csv, io, hashlib
from datetime import datetime
from urllib.parse import quote
from .base import *
from .common import HTTPBroker,candles,normalize_order,normalize_positions,normalize_holdings,dt

@register_adapter
class ZerodhaBroker(HTTPBroker):
    broker_id='zerodha'; base_url='https://api.kite.trade'
    capabilities=frozenset({Capability.INSTRUMENT_MASTER,Capability.HISTORICAL_CANDLES,Capability.LIVE_STREAM,
                            Capability.MARKET_DEPTH,Capability.PLACE_ORDER,Capability.MODIFY_ORDER,
                            Capability.CANCEL_ORDER,Capability.ORDER_TAG,Capability.POSITIONS,Capability.HOLDINGS,
                            Capability.FUNDS,Capability.TRADEBOOK})
    verification='official-docs-implemented; live-untested'
    def _headers(self):
        h={'X-Kite-Version':'3'}
        if self.access_token: h['Authorization']=f'token {self.api_key}:{self.access_token}'
        return h
    async def _call(self,method,path,**kw):
        r=await self._http(method,path,headers=self._headers(),**kw)
        return r.get('data',r) if isinstance(r,dict) else r
    async def authenticate(self,credentials):
        self.api_key=credentials.get('api_key','')
        if not self.api_key:raise AuthError('Zerodha requires api_key')
        token=credentials.get('access_token')
        if token:self.access_token=token
        else:
            if not (credentials.get('request_token') and credentials.get('api_secret')):
                raise AuthError('Provide access_token or request_token + api_secret from official Kite redirect')
            req=credentials['request_token']; secret=credentials['api_secret']
            checksum=hashlib.sha256((self.api_key+req+secret).encode()).hexdigest()
            result=await self._call('POST','/session/token',form={'api_key':self.api_key,'request_token':req,'checksum':checksum})
            self.access_token=result['access_token']
        try:
            info=await self._call('GET','/user/profile')
        except Exception:
            self.access_token='';raise
        return Profile(str(info.get('user_id',self.account_id)),info.get('user_name',''),info.get('email',''))
    async def verify_session(self):
        if not self.access_token:return False
        info=await self._call('GET','/user/profile')
        return isinstance(info,dict) and bool(info.get('user_id'))
    async def logout(self):
        if self.access_token:
            try: await self._call('DELETE','/session/token',form={'api_key':self.api_key,'access_token':self.access_token})
            finally:await super().logout()
    async def get_instruments(self,exchange=''):
        path='/instruments'+('/'+quote(exchange,safe='') if exchange else '')
        data=await self._http('GET',path,headers=self._headers(),raw=True)
        results=[]
        for x in csv.DictReader(io.StringIO(data)):
            symbol=x.get('tradingsymbol',''); ex=x.get('exchange','')
            if not symbol:continue
            typ=x.get('instrument_type','EQ')
            key=InstrumentKey(ex,symbol,typ)
            results.append(Instrument(key,str(x['instrument_token']),x.get('name',''),
                int(float(x.get('lot_size',1) or 1)),float(x.get('tick_size',.05) or .05),
                dt(x['expiry']) if x.get('expiry') else None,
                float(x['strike']) if x.get('strike') else None,
                typ if typ in ('CE','PE') else None))
        return self.remember_instruments(results)
    async def get_historical_data(self,key,interval,start,end):
        itv={'1m':'minute','3m':'3minute','5m':'5minute','10m':'10minute','15m':'15minute','30m':'30minute','60m':'60minute','1d':'day'}.get(interval,interval)
        allowed={'minute','3minute','5minute','10minute','15minute','30minute','60minute','day'}
        if itv not in allowed:raise UnsupportedCapability('Kite interval not supported: '+interval)
        token=self.token_for(key,allow_symbol=key.symbol.isdigit())
        rows=await self._call('GET',f'/instruments/historical/{quote(token,safe="")}/{itv}',params={'from':start.strftime('%Y-%m-%d %H:%M:%S'),'to':end.strftime('%Y-%m-%d %H:%M:%S'),'oi':'1'})
        return candles(rows.get('candles',[]))
    async def place_order(self,req):
        product=req.product.upper()
        if product not in ('MIS','CNC','NRML'):raise UnsupportedCapability('Kite product unsupported')
        typ={'SL_M':'SL-M'}.get(req.order_type,req.order_type)
        form={'exchange':req.key.exchange,'tradingsymbol':req.key.symbol,'transaction_type':req.side,
              'quantity':req.qty,'product':product,'order_type':typ,'validity':req.validity,
              'price':req.price or 0,'trigger_price':req.trigger_price or 0}
        if req.client_order_id:form['tag']=req.client_order_id[:20]
        r=await self._call('POST','/orders/regular',form=form,order=True)
        oid=str(r.get('order_id',''))
        if not oid:raise OrderUncertain('Kite response missing order_id')
        self._orders[oid]=req
        return oid
    async def modify_order(self,order_id,**changes):
        allowed={'qty':'quantity','price':'price','trigger_price':'trigger_price','order_type':'order_type','validity':'validity'}
        f={allowed[k]:v for k,v in changes.items() if k in allowed and v is not None}
        if not f:raise ValueError('No modifiable fields')
        await self._call('PUT',f'/orders/regular/{quote(order_id,safe="")}',form=f,order=True)
    async def cancel_order(self,order_id):
        await self._call('DELETE',f'/orders/regular/{quote(order_id,safe="")}',order=True)
    async def get_orders(self):
        rows=await self._call('GET','/orders')
        return [normalize_order(x,tag_field='tag') for x in rows]
    async def get_tradebook(self):
        return await self._call('GET','/trades')
    async def get_positions(self):
        d=await self._call('GET','/portfolio/positions')
        return normalize_positions(d.get('net',[]))
    async def get_holdings(self):
        return normalize_holdings(await self._call('GET','/portfolio/holdings'))
    async def get_funds(self):
        r=await self._call('GET','/user/margins')
        x=r.get('equity',r);a=x.get('available',{});u=x.get('utilised',{})
        avail=float(a.get('live_balance',a.get('cash',0)) or 0);used=float(u.get('debits',0) or 0)
        return Funds(avail,used,avail+used)
    def subscribe_market_data(self,keys):
        from .streams import zerodha_stream
        return zerodha_stream(self,keys)
