"""Broker option chain into one documented, unambiguous response contract."""
from __future__ import annotations
from datetime import datetime,timezone
from typing import Any


def _f(v):
    if v is None or v=='': return None
    try: return float(v)
    except (TypeError,ValueError): return None

def _upstox_leg(obj):
    if not isinstance(obj,dict): return None
    m=obj.get('market_data') or {}
    greeks=obj.get('option_greeks') or {}
    return {'symbol':obj.get('trading_symbol') or '', 'instrument_key':obj.get('instrument_key') or '',
            'ltp':_f(m.get('ltp')),'bid':_f(m.get('bid_price')),'ask':_f(m.get('ask_price')),
            'oi':_f(m.get('oi')),'prev_oi':_f(m.get('prev_oi')),'volume':_f(m.get('volume')),
            'iv':_f(greeks.get('iv')),'delta':_f(greeks.get('delta')),'gamma':_f(greeks.get('gamma')),
            'theta':_f(greeks.get('theta')),'vega':_f(greeks.get('vega'))}

def upstox_chain(rows):
    result=[]
    for r in rows or []:
        if not isinstance(r,dict) or r.get('strike_price') is None:continue
        result.append({'strike':_f(r.get('strike_price')),'call':_upstox_leg(r.get('call_options')),
                       'put':_upstox_leg(r.get('put_options'))})
    return result

def fyers_chain(payload):
    rows={}
    for r in payload.get('optionsChain',[]) if isinstance(payload,dict) else []:
        if not isinstance(r,dict) or r.get('option_type') not in ('CE','PE'):continue
        strike=_f(r.get('strike_price'))
        if strike is None:continue
        x=rows.setdefault(strike,{'strike':strike,'call':None,'put':None})
        x['call' if r['option_type']=='CE' else 'put']={
            'symbol':str(r.get('symbol') or ''),'instrument_key':str(r.get('fyToken') or ''),
            **{k:_f(r.get(src)) for k,src in {'ltp':'ltp','bid':'bid','ask':'ask','oi':'oi','volume':'volume',
                                               'iv':'iv','delta':'delta','gamma':'gamma','theta':'theta',
                                               'vega':'vega'}.items()}}
    return list(rows.values())

def normalize_chain(broker,raw,underlying,expiry):
    if broker=='upstox': data=upstox_chain(raw)
    elif broker=='fyers':data=fyers_chain(raw)
    else:raise ValueError(f'{broker} has no validated chain normalizer')
    data.sort(key=lambda x:x['strike'])
    return {'broker':broker,'underlying':underlying,'expiry':expiry,'rows':data,'count':len(data),
            'as_of':datetime.now(timezone.utc).isoformat(),
            'note':'Broker snapshot; quotes and Greeks are not guaranteed realtime'}
