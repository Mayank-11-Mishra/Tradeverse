"""FYERS API v3, following FyersDev official endpoint catalog.
https://github.com/FyersDev/fyers-skills/blob/master/skills/fyers-trading/references/endpoints.md
"""
from __future__ import annotations
from datetime import datetime
from .base import *
from .common import HTTPBroker,candles,normalize_order,normalize_positions,normalize_holdings

@register_adapter
class FyersBroker(HTTPBroker):
    broker_id='fyers';base_url='https://api-t1.fyers.in'
    capabilities=frozenset({Capability.HISTORICAL_CANDLES,Capability.LIVE_STREAM,Capability.MARKET_DEPTH,
        Capability.OPTION_CHAIN,Capability.PLACE_ORDER,Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,
        Capability.ORDER_TAG,Capability.POSITIONS,Capability.HOLDINGS,Capability.FUNDS,Capability.TRADEBOOK})
    verification='official-docs-implemented; live-untested'
    def _headers(self):return {'Authorization':f'{self.client_id}:{self.access_token}','Content-Type':'application/json'}
    async def _call(self,method,path,**kw):
        d=await self._http(method,path,headers=self._headers(),**kw)
        return d if isinstance(d,dict) else {'data':d}
    async def authenticate(self,credentials):
        self.client_id=credentials.get('client_id','')
        self.access_token=credentials.get('access_token','')
        if not self.client_id or not self.access_token:
            raise AuthError('FYERS requires client_id and OAuth access_token from official login flow')
        try:
            d=await self._call('GET','/api/v3/profile')
            x=d.get('data',d)
        except Exception:self.access_token='';raise
        return Profile(str(x.get('fy_id',x.get('id',self.account_id))),x.get('name',''),x.get('email_id',''))
    async def verify_session(self):
        if not self.access_token:return False
        info=await self._call('GET','/api/v3/profile')
        return isinstance(info,dict) and bool(info.get('fy_id',info.get('id')) or (info.get('data') or {}).get('fy_id'))
    async def get_historical_data(self,key,interval,start,end):
        resolution={'1d':'D','1w':'W','1mo':'M','1h':'60'}.get(interval,interval[:-1] if interval.endswith('m') else interval)
        if resolution not in ('1','2','3','5','10','15','30','60','120','240','D','W','M'):
            raise UnsupportedCapability('FYERS interval unsupported')
        broker_symbol=key.symbol if ':' in key.symbol else (f'{key.exchange}:{key.symbol}-EQ' if key.segment=='EQ' else key.symbol)
        if ':' not in broker_symbol:raise UnsupportedCapability('FYERS derivative/index history needs full broker symbol e.g. NSE:NIFTY50-INDEX')
        d=await self._call('GET','/data/history',params={'symbol':broker_symbol,'resolution':resolution,
            'date_format':1,'range_from':start.date().isoformat(),'range_to':end.date().isoformat(),'cont_flag':'1'})
        return candles(d.get('candles',[]))
    @staticmethod
    def _option_symbol(underlying):
        if ':' in underlying:return underlying
        symbols={'NIFTY':'NSE:NIFTY50-INDEX','NIFTY 50':'NSE:NIFTY50-INDEX',
                 'BANKNIFTY':'NSE:NIFTYBANK-INDEX','SENSEX':'BSE:SENSEX-INDEX',
                 'FINNIFTY':'NSE:FINNIFTY-INDEX'}
        return symbols.get(underlying.strip().upper(),f'NSE:{underlying.strip().upper()}-EQ')

    async def get_option_expiries(self,underlying):
        from datetime import datetime
        d=await self._call('GET','/data/options-chain-v3',params={'symbol':self._option_symbol(underlying),'strikecount':1})
        x=d.get('data',d)
        result=[]
        for e in x.get('expiryData',[]):
            try:result.append(datetime.strptime(e['date'],'%d-%m-%Y').date().isoformat())
            except (KeyError,ValueError,TypeError):continue
        return sorted(set(result))

    async def get_option_chain(self,underlying,expiry):
        # FYERS expiry selection uses the epoch expiry identifier, not YYYY-MM-DD.
        symbol=self._option_symbol(underlying)
        params={'symbol':symbol,'strikecount':20,'greeks':'1'}
        if expiry and str(expiry).isdigit():
            params['timestamp']=str(expiry)
        elif expiry:
            # First response lists epoch values and human-readable dates.
            nearest=await self._call('GET','/data/options-chain-v3',params=params)
            expiries=nearest.get('data',nearest).get('expiryData',[])
            from datetime import datetime
            target=datetime.fromisoformat(str(expiry)).date()
            found=next((x for x in expiries if datetime.strptime(x['date'],'%d-%m-%Y').date()==target),None)
            if not found:raise UnsupportedCapability('FYERS expiry not available in broker expiryData')
            params['timestamp']=str(found['expiry'])
        d=await self._call('GET','/data/options-chain-v3',params=params)
        return d.get('data',d)
    async def place_order(self,req):
        product={'MIS':'INTRADAY','CNC':'CNC','NRML':'MARGIN'}.get(req.product)
        if not product:raise UnsupportedCapability('FYERS product unsupported')
        typ={'LIMIT':1,'MARKET':2,'SL_M':3,'SL':4}.get(req.order_type)
        if not typ:raise UnsupportedCapability('FYERS order type unsupported')
        payload={'symbol':req.key.symbol,'qty':req.qty,'type':typ,'side':1 if req.side=='BUY' else -1,
            'productType':product,'limitPrice':req.price or 0,'stopPrice':req.trigger_price or 0,
            'disclosedQty':0,'validity':req.validity,'offlineOrder':False,'stopLoss':0,'takeProfit':0,
            'orderTag':req.client_order_id[:20]}
        d=await self._call('POST','/api/v3/orders/sync',json_body=payload,order=True)
        oid=str(d.get('id',d.get('data',{}).get('id','')))
        if not oid:raise OrderUncertain('FYERS order acknowledgement has no ID; reconcile')
        self._orders[oid]=req
        return oid
    async def modify_order(self,order_id,**changes):
        d={'id':order_id}
        for a,b in {'qty':'qty','price':'limitPrice','trigger_price':'stopPrice','order_type':'type'}.items():
            if a in changes:d[b]=({'LIMIT':1,'MARKET':2,'SL_M':3,'SL':4}.get(changes[a]) if a=='order_type' else changes[a])
        if len(d)==1:raise ValueError('No changes supplied')
        await self._call('PATCH','/api/v3/orders/sync',json_body=d,order=True)
    async def cancel_order(self,order_id):
        await self._call('DELETE','/api/v3/orders/sync',json_body={'id':order_id},order=True)
    async def get_orders(self):
        d=await self._call('GET','/api/v3/orders')
        out=[]
        for x in d.get('orderBook',d.get('orderbook',[])):
            if isinstance(x,dict):
                x={**x,'order_type':str(x.get('type','MARKET')),'transaction_type':'BUY' if x.get('side')==1 else 'SELL',
                   'quantity':x.get('qty',0),'exchange':x.get('symbol','NSE').split(':')[0]}
                out.append(normalize_order(x,order_id_field='id',tag_field='orderTag'))
        return out
    async def get_tradebook(self):
        d=await self._call('GET','/api/v3/tradebook')
        return d.get('tradeBook',d.get('tradebook',[]))
    async def get_positions(self):
        d=await self._call('GET','/api/v3/positions')
        return normalize_positions(d.get('netPositions',[]))
    async def get_holdings(self):
        d=await self._call('GET','/api/v3/holdings')
        return normalize_holdings(d.get('holdings',[]))
    async def get_funds(self):
        d=await self._call('GET','/api/v3/funds')
        limits={int(x.get('id',-1)):float(x.get('equityAmount',x.get('amount',0)) or 0) for x in d.get('fund_limit',[])}
        avail=limits.get(10,limits.get(3,0));used=limits.get(2,0)
        return Funds(avail,used,avail+used)
    def subscribe_market_data(self,keys):
        from .streams import fyers_stream
        return fyers_stream(self,keys)
