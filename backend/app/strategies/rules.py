"""Deterministic declarative trading rules: no eval/exec, same engine for backtest and live.
Each operand can be price or a calculated indicator; conditions can be nested groups.
"""
from __future__ import annotations
import math
import pandas as pd
from app.backtesting.engine import Strategy, Context

DEFAULT_RULES={
 'entry':{'left':{'indicator':'ema','params':{'length':9}},'operator':'crosses_above',
          'right':{'indicator':'ema','params':{'length':21}}},
 'exit':{'left':{'indicator':'ema','params':{'length':9}},'operator':'crosses_below',
         'right':{'indicator':'ema','params':{'length':21}}},
 'quantity':1,'sl_pct':1.0,'tp_pct':2.0,
}

def _operand(ctx:Context,op,shift):
    if isinstance(op,(int,float)):return float(op)
    if not isinstance(op,dict):raise ValueError('operand must be a number or indicator/price object')
    if 'value' in op:return float(op['value'])
    if 'indicator' in op:
        name=str(op['indicator']).lower()
        if name not in ('ema','sma','rsi','macd','supertrend','atr','vwap','bbands','adx','obv','cci','mfi','psar','donchian','keltner','stoch','stochrsi'):
            raise ValueError('indicator not permitted: '+name)
        params=dict(op.get('params',{}))
        if 'n' in params: # Accept older visual strategy definitions.
            n=params.pop('n')
            params['period' if name=='supertrend' else 'length']=n
        return ctx.ind(name,col=op.get('column'),shift=shift,**params)
    col=op.get('price',op.get('field','close'))
    if col not in ('open','high','low','close','volume'):raise ValueError('invalid price column')
    at=ctx.i-shift
    return float(ctx._data.iloc[at][col]) if at>=0 else float('nan')

def evaluate(ctx:Context,condition:dict,shift=0)->bool:
    if not condition:return False
    if 'all' in condition:return all(evaluate(ctx,c,shift) for c in condition['all'])
    if 'any' in condition:return any(evaluate(ctx,c,shift) for c in condition['any'])
    if 'not' in condition:return not evaluate(ctx,condition['not'],shift)
    op=condition.get('operator','>')
    left=condition.get('left',{'price':'close'});right=condition.get('right',0)
    a=_operand(ctx,left,shift);b=_operand(ctx,right,shift)
    if math.isnan(a) or math.isnan(b):return False
    if op in ('crosses_above','crosses_below'):
        if ctx.i-shift <1:return False
        pa=_operand(ctx,left,shift+1);pb=_operand(ctx,right,shift+1)
        if math.isnan(pa) or math.isnan(pb):return False
        return pa<=pb and a>b if op=='crosses_above' else pa>=pb and a<b
    return {'>':lambda:a>b,'>=':lambda:a>=b,'<':lambda:a<b,'<=':lambda:a<=b,
            '==':lambda:a==b,'!=':lambda:a!=b}.get(op,lambda:False)()

class RuleStrategy(Strategy):
    name='Visual Rule Strategy'
    def __init__(self,definition=None):
        self.definition={**DEFAULT_RULES,**(definition or {})}
        super().__init__(**self.definition)
    def on_bar(self,ctx):
        rules=self.definition
        if ctx.position==0:
            if evaluate(ctx,rules['entry']):
                q=int(rules.get('quantity',1))
                if q<=0:raise ValueError('quantity must be positive')
                kw={}
                for name in ('sl_pct','tp_pct','trail_pct'):
                    if rules.get(name) is not None:kw[name]=float(rules[name])/100
                ctx.buy(q,**kw)
        elif ctx.position>0 and evaluate(ctx,rules.get('exit',{})):
            ctx.close()

def signal_from_frame(frame:pd.DataFrame,definition:dict,current_position:int=0):
    if len(frame)<2:return None
    ctx=Context(frame);ctx.i=len(frame)-1;ctx.position=current_position
    rules={**DEFAULT_RULES,**definition}
    if current_position==0 and evaluate(ctx,rules['entry']):return 'BUY'
    if current_position>0 and evaluate(ctx,rules.get('exit',{})):return 'SELL'
    return None
