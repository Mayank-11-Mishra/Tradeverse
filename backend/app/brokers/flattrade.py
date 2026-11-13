"""Flattrade PiConnect API, docs updated 31 March 2026.
https://pi.flattrade.in/docs
"""
from .base import Capability,register_adapter
from .noren import NorenBroker

@register_adapter
class FlattradeBroker(NorenBroker):
    broker_id='flattrade';base_url='https://piconnect.flattrade.in/PiConnectAPI'
    websocket_url='wss://piconnect.flattrade.in/PiConnectWSAPI/'
    token_in_form=True
    product_map={'MIS':'M','CNC':'C','NRML':'M'}
    verification='official-docs-implemented; live-untested'
    capabilities=frozenset({Capability.INSTRUMENT_MASTER,Capability.HISTORICAL_CANDLES,
        Capability.LIVE_STREAM,Capability.MARKET_DEPTH,Capability.PLACE_ORDER,
        Capability.MODIFY_ORDER,Capability.CANCEL_ORDER,Capability.ORDER_TAG,
        Capability.POSITIONS,Capability.HOLDINGS,Capability.FUNDS,Capability.TRADEBOOK})
