"""Inventory of user-provided studies. Status is deliberately truthful.

A listed vendor study is not necessarily mathematically equivalent to a generic
public formula. Only explicitly mapped standard equivalents may be plotted.
"""
from __future__ import annotations
from pathlib import Path
import json,re
from .engine import REGISTRY

ALIASES={
 'average - simple':'sma','average':'sma','average - exponential':'ema',
 'average - weighted':'wma','average - volume adjusted':'vwma',
 'average - wilder smoothening':'ema', # differs in convention: do not expose as equivalent
 'average - zero lag exponential':'zlema','average - triangular':'trima',
 'average - hull':'hull','double exponential moving average':'dema',
 'triple exponential moving average':'tema',
 'bollinger band':'bbands','bollinger band width':'bbwidth','keltner channel':'keltner',
 'price channel':'donchian','parabolic stop and reverse':'psar',
 'dir. movement(adx +di & -di)':'adx','dir. movement index(dx)':'adx',
 'choppiness index':'choppiness','chande momentum oscillator':'cmo',
 'commodity channel index':'cci','rate of change - percentage':'roc','trix':'tsi', # different formula: unmapped below
 'money flow index':'mfi','relative strength index':'rsi',
 'stochastics':'stoch','stochastics fast':'stoch','stochastics slow':'stoch',
 'stochastics rsi(dt oscillator)':'stochrsi','williams percent r':'willr',
 'aroon index':'aroon','aroon oscillator':'aroon','chaikin money flow':'cmf',
 'chaikin s oscillator':'chaikin_osc','detrend price oscillator':'dpo',
 'fisher transform':'fisher','force index':'force','macd':'macd',
 'macd histogram':'macd','awesome oscillator':'awesome',
 'true strength index':'tsi','ultimate oscillator':'ultimate',
 'volume oscillator':'volume_oscillator','option - implied volatility':None,
 'median price':'price_lines','typical price':'price_lines','weighted close':'price_lines',
 'volume weighted avg price':'vwap','supertrend':'supertrend',
 'ichimoku kinko hyo':'ichimoku','accumulation distribution line':'ad_line',
 'on balance volume':'obv','negative volume index':'nvi_pvi',
 'positive volume index':'nvi_pvi','price volume trend':'pvt',
 'z score':'zscore','standard variance':'variance','standard deviation':'stddev',
 'regression line':'linreg','regression slope':'linreg',
 'average true range':'atr','average true range - percentage':'natr',
 'relative strength index - cutler':None,
}
# Do not equate a Wilder average with EMA, or TRIX with TSI.
ALIASES.pop('average - wilder smoothening',None)
ALIASES.pop('trix',None)
# Standard calculations, not a claim of equivalence to any "Old", "Adv", or
# bespoke commercial variant.
OSCILLATORS={'rsi','macd','stoch','stochrsi','atr','adx','cci','mfi','obv','roc','momentum','willr','aroon','cmf',
             'ad_line','chaikin_osc','pvt','nvi_pvi','natr','stddev','variance','zscore','cmo','tsi','awesome',
             'force','choppiness','ultimate','fisher','volume_oscillator','dpo','bbwidth'}


def inventory():
    entries=json.loads((Path(__file__).parent/'studies_inventory.json').read_text(encoding='utf8'))
    result=[]
    for item in entries:
        indicator=ALIASES.get(item['name'].strip().lower())
        supported=indicator in REGISTRY
        result.append({**item,'indicator_id':indicator if supported else None,'implemented':supported,
                       'pane':'oscillator' if indicator in OSCILLATORS else 'overlay'})
    return result


def implemented():
    return [{'id':name,'params':defaults,'pane':'oscillator' if name in OSCILLATORS else 'overlay'}
            for name,(_,defaults) in sorted(REGISTRY.items())]
