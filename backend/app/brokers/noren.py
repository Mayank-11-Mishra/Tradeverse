"""Shared normalization for two different Noren-family gateways.
Flattrade Pi and Shoonya have different hosts/authentication; never treat sessions as interchangeable.
"""
from __future__ import annotations
import json
from .base import *
from .common import HTTPBroker,candles,normalize_order,normalize_positions,normalize_holdings

class NorenBroker(HTTPBroker):
    token_in_form=True
    product_map={'MIS':'M','CNC':'C','NRML':'M'}
    def _headers(self):
        return {'Authorization':f'Bearer {self.access_token}'} if not self.token_in_form else {}
    async def _call(self,path,body=None,order=False):
        if not self.access_token:raise AuthError('Connect using a valid broker access token')
        form={'jData':json.dumps(body or {'uid':self.user_id},separators=(',',':'))}
        if self.token_in_form:form['jKey']=self.access_token
        return await self._http('POST','/'+path,form=form,headers=self._headers(),order=order)
    async def authenticate(self,credentials):
        self.user_id=credentials.get('user_id',credentials.get('uid',''))
        self.account_id=credentials.get('account_id',self.account_id)
        self.access_token=credentials.get('access_token','')
        if not self.user_id or not self.access_token:
            raise AuthError(f'{self.broker_id} needs user_id and token obtained using its official login')
        try:
            d=await self._call('UserDetails',{'uid':self.user_id})
            if isinstance(d,dict) and d.get('stat')=='Not_Ok':raise AuthError(d.get('emsg','Session expired'))
        except Exception:self.access_token='';raise
        return Profile(self.account_id,str(d.get('uname',d.get('name',''))),'')
    async def verify_session(self):
        if not self.access_token:return False
        info=await self._call('UserDetails',{'uid':self.user_id})
        return isinstance(info,dict) and info.get('stat')!='Not_Ok' and bool(info.get('uid',info.get('uname',info.get('actid'))))
    async def get_instruments(self,query='',exchange='NSE'):
        if not query:raise ValueError('SearchScrip requires text input; no full-master download from this endpoint')
        d=await self._call('SearchScrip',{'uid':self.user_id,'exch':exchange,'stext':query})
        items=[]
        for x in (d.get('values',[]) if isinstance(d,dict) else []):
            if not isinstance(x,dict):continue
            sym=x.get('tsym',x.get('cname',''))
            if not sym:continue
            items.append(Instrument(InstrumentKey(exchange,sym,x.get('instname','EQ')),str(x.get('token','')),x.get('cname','')))
        return self.remember_instruments(items)
    async def get_historical_data(self,key,interval,start,end):
        s=interval[:-1] if interval.endswith('m') else interval
        if s not in ('1','3','5','10','15','30','60','120','240'):
            raise UnsupportedCapability('Only intraday TPSeries intervals supported')
        token=self.token_for(key,allow_symbol=key.symbol.isdigit())
        result=await self._call('TPSeries',{'uid':self.user_id,'exch':key.exchange,'token':token,
            'st':str(int(start.timestamp())),'et':str(int(end.timestamp())),'intrv':s})
        if isinstance(result,dict) and result.get('stat')=='Not_Ok':raise BrokerError(result.get('emsg','TPSeries error'))
        return candles(result if isinstance(result,list) else [],'noren')
    def _prctyp(self,typ):
        if typ=='LIMIT':return 'LMT'
        if typ=='SL':return 'SL-LMT'
        raise UnsupportedCapability(f'{self.broker_id} current documented API supports LIMIT and SL only')
    async def place_order(self,req):
        prd=self.product_map.get(req.product)
        if not prd:raise UnsupportedCapability('Unsupported Noren product')
        d={'uid':self.user_id,'actid':self.account_id,'exch':req.key.exchange,
           'tsym':req.key.symbol,'qty':str(req.qty),'prc':str(req.price or 0),
           'trgprc':str(req.trigger_price or 0),'prd':prd,'trantype':'B' if req.side=='BUY' else 'S',
           'prctyp':self._prctyp(req.order_type),'ret':req.validity,'dscqty':'0','remarks':req.client_order_id[:20]}
        r=await self._call('PlaceOrder',d,order=True)
        if isinstance(r,dict) and r.get('stat')!='Ok':raise OrderRejected(str(r.get('emsg','Order rejected')))
        oid=str(r.get('norenordno',''))
        if not oid:raise OrderUncertain('Noren order response missing ID')
        self._orders[oid]=req
        return oid
    async def modify_order(self,order_id,**changes):
        old=self._orders.get(order_id)
        if not old:raise BrokerError('Order not in session; first reconcile order book')
        typ=changes.get('order_type',old.order_type)
        data={'uid':self.user_id,'actid':self.account_id,'exch':old.key.exchange,'tsym':old.key.symbol,
              'norenordno':order_id,'qty':str(changes.get('qty',old.qty)),
              'prc':str(changes.get('price',old.price or 0)),
              'trgprc':str(changes.get('trigger_price',old.trigger_price or 0)),
              'prctyp':self._prctyp(typ)}
        result=await self._call('ModifyOrder',data,order=True)
        if result.get('stat')!='Ok':raise OrderRejected(str(result.get('emsg','Modify rejected')))
    async def cancel_order(self,order_id):
        d=await self._call('CancelOrder',{'uid':self.user_id,'norenordno':order_id},order=True)
        if d.get('stat')!='Ok':raise OrderRejected(str(d.get('emsg','Cancel rejected')))
    async def get_orders(self):
        d=await self._call('OrderBook',{'uid':self.user_id})
        if isinstance(d,dict):
            if d.get('stat')=='Not_Ok' and 'no data' in d.get('emsg','').lower():return []
            raise BrokerError(str(d.get('emsg','OrderBook response not a list')))
        return [normalize_order(x,order_id_field='norenordno',tag_field='remarks') for x in d]
    async def get_tradebook(self):
        d=await self._call('TradeBook',{'uid':self.user_id,'actid':self.account_id})
        if isinstance(d,dict) and 'no data' in d.get('emsg','').lower():return []
        if not isinstance(d,list):raise BrokerError('Broker tradebook unavailable')
        return d
    async def get_positions(self):
        d=await self._call('PositionBook',{'uid':self.user_id,'actid':self.account_id})
        return normalize_positions(d if isinstance(d,list) else [])
    async def get_holdings(self):
        d=await self._call('Holdings',{'uid':self.user_id,'actid':self.account_id})
        return normalize_holdings(d if isinstance(d,list) else [])
    async def get_funds(self):
        d=await self._call('Limits',{'uid':self.user_id,'actid':self.account_id})
        available=float(d.get('cash',d.get('marginavl',0)) or 0)
        used=float(d.get('marginused',0) or 0)
        return Funds(available,used,available+used)
    def subscribe_market_data(self,keys):
        from .streams import noren_stream
        return noren_stream(self,keys)
