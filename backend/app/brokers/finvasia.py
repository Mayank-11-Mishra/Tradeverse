"""Finvasia Shoonya modern gateway, including Bearer token authentication.
https://shoonya.com/api-documentation/api-structure
"""
from .base import Capability,register_adapter
import json
from .noren import NorenBroker

@register_adapter
class FinvasiaBroker(NorenBroker):
    broker_id='finvasia';base_url='https://api.shoonya.com/NorenWClientAPI'
    websocket_url='wss://api.shoonya.com/NorenWSAPI/'
    token_in_form=False
    product_map={'MIS':'I','CNC':'C','NRML':'M'}
    verification='Shoonya OAuth API documented; live-untested'
    async def _call(self,path,body=None,order=False):
        if not self.access_token:
            from .base import AuthError
            raise AuthError('Shoonya session missing or expired. Complete official broker OAuth login.')
        # Shoonya's current documentation specifies text/plain jData and bearer
        # token rather than x-www-form-urlencoded jData or an old password/TOTP flow.
        data='jData='+json.dumps(body or {'uid':self.user_id},separators=(',',':'))
        return await self._http('POST','/'+path,content=data,
            headers={'Content-Type':'text/plain','Authorization':f'Bearer {self.access_token}'},order=order)
    capabilities=frozenset({Capability.INSTRUMENT_MASTER,Capability.HISTORICAL_CANDLES,
        Capability.LIVE_STREAM,Capability.MARKET_DEPTH,Capability.PLACE_ORDER,
        Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,Capability.POSITIONS,
        Capability.HOLDINGS,Capability.FUNDS,Capability.TRADEBOOK})
