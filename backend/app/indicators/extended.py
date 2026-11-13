"""Additional causal, independently implemented standard technical indicators.

These are *standard formulas*, not reverse-engineered proprietary variants from the
user's studies inventory.  Unspecified vendor-specific versions remain unimplemented.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .engine import ema, sma, wma, rma, atr, true_range, obv


def output(name, value): return pd.DataFrame({name: value})

def hull(df, length=20):
    n=max(2,int(length));return output('hull', wma(2*wma(df.close,max(1,n//2))-wma(df.close,n),max(1,int(np.sqrt(n)))))

def dema(df, length=20):
    e1=ema(df.close,length);return output('dema',2*e1-ema(e1,length))

def tema(df,length=20):
    a=ema(df.close,length);b=ema(a,length);c=ema(b,length);return output('tema',3*a-3*b+c)

def zlema(df,length=20):
    lag=max(1,(length-1)//2);return output('zlema',ema(df.close*2-df.close.shift(lag),length))

def trima(df,length=20):
    a=(length+1)//2;b=(length+2)//2;return output('trima',sma(sma(df.close,a),b))

def roc(df,length=12):return output('roc',100*(df.close/df.close.shift(length)-1).replace([np.inf,-np.inf],np.nan))

def momentum(df,length=10):return output('momentum',df.close-df.close.shift(length))

def willr(df,length=14):
    lo=df.low.rolling(length).min();hi=df.high.rolling(length).max()
    return output('willr',(-100*(hi-df.close)/(hi-lo).replace(0,np.nan)))

def aroon(df,length=14):
    # Window is length+1, so today high yields 100, high length bars ago yields 0.
    up=df.high.rolling(length+1).apply(lambda v:100*np.argmax(v)/length,raw=True)
    down=df.low.rolling(length+1).apply(lambda v:100*np.argmin(v)/length,raw=True)
    return pd.DataFrame({'aroon_up':up,'aroon_down':down,'aroon_oscillator':up-down})

def cmf(df,length=20):
    spread=(df.high-df.low).replace(0,np.nan)
    mfv=((df.close-df.low)-(df.high-df.close))/spread*df.volume
    return output('cmf',mfv.rolling(length).sum()/df.volume.rolling(length).sum().replace(0,np.nan))

def ad_line(df):
    spread=(df.high-df.low).replace(0,np.nan)
    return output('ad_line',((((df.close-df.low)-(df.high-df.close))/spread).fillna(0)*df.volume).cumsum())

def chaikin_osc(df,fast=3,slow=10):
    a=ad_line(df).ad_line;return output('chaikin_osc',ema(a,fast)-ema(a,slow))

def pvt(df):
    ret=(df.close.pct_change().replace([np.inf,-np.inf],np.nan).fillna(0))
    return output('pvt',(ret*df.volume).cumsum())

def nvi(df):
    # Positive and negative volume indices; rebased at 1000.
    ret=df.close.pct_change().fillna(0)
    neg=np.where(df.volume.to_numpy()<df.volume.shift(1).fillna(df.volume.iloc[0]).to_numpy(),ret,0)
    pos=np.where(df.volume.to_numpy()>df.volume.shift(1).fillna(df.volume.iloc[0]).to_numpy(),ret,0)
    return pd.DataFrame({'nvi':1000*np.cumprod(1+neg),'pvi':1000*np.cumprod(1+pos)},index=df.index)

def natr(df,length=14):return output('natr',100*atr(df,length)/df.close.replace(0,np.nan))

def stddev(df,length=20):return output('stddev',df.close.rolling(length).std(ddof=0))

def variance(df,length=20):return output('variance',df.close.rolling(length).var(ddof=0))

def zscore(df,length=20):
    mean=sma(df.close,length);std=df.close.rolling(length).std(ddof=0)
    return output('zscore',(df.close-mean)/std.replace(0,np.nan))

def linreg(df,length=20):
    x=np.arange(length,dtype=float);xm=x.mean();div=((x-xm)**2).sum()
    slope=df.close.rolling(length).apply(lambda y:float(((x-xm)*(y-y.mean())).sum()/div),raw=True)
    mean=sma(df.close,length)
    return pd.DataFrame({'linreg':mean+slope*(length-1-xm),'linreg_slope':slope})

def cmo(df,length=14):
    diff=df.close.diff();up=diff.clip(lower=0).rolling(length).sum();down=(-diff.clip(upper=0)).rolling(length).sum()
    return output('cmo',100*(up-down)/(up+down).replace(0,np.nan))

def tsi(df,long=25,short=13):
    ch=df.close.diff();a=ema(ema(ch,long),short);b=ema(ema(ch.abs(),long),short)
    return output('tsi',100*a/b.replace(0,np.nan))

def awesome(df,fast=5,slow=34):
    mid=(df.high+df.low)/2
    return output('awesome',sma(mid,fast)-sma(mid,slow))

def force(df,length=13):return output('force',ema(df.close.diff()*df.volume,length))

def choppiness(df,length=14):
    tr=true_range(df).rolling(length).sum();span=df.high.rolling(length).max()-df.low.rolling(length).min()
    return output('choppiness',100*np.log10(tr/span.replace(0,np.nan))/np.log10(length))

def ultimate(df,short=7,medium=14,long=28):
    prev=df.close.shift(1)
    bp=df.close-pd.concat([df.low,prev],axis=1).min(axis=1)
    tr=pd.concat([df.high,prev],axis=1).max(axis=1)-pd.concat([df.low,prev],axis=1).min(axis=1)
    avgs=[bp.rolling(n).sum()/tr.rolling(n).sum().replace(0,np.nan) for n in (short,medium,long)]
    return output('ultimate',100*(4*avgs[0]+2*avgs[1]+avgs[2])/7)

def fisher(df,length=10):
    mid=(df.high+df.low)/2;highest=mid.rolling(length).max();lowest=mid.rolling(length).min()
    ratio=(2*((mid-lowest)/(highest-lowest).replace(0,np.nan)-0.5)).fillna(0)
    values=np.full(len(ratio),np.nan);previous=0.0;fish=0.0
    for i,r in enumerate(ratio):
        previous=np.clip(.33*float(r)+.67*previous,-.999,.999)
        fish=.5*np.log((1+previous)/(1-previous))+.5*fish
        if i>=length-1:values[i]=fish
    return output('fisher',pd.Series(values,index=df.index))

def vpo(df,fast=12,slow=26):
    a=ema(df.volume,fast);b=ema(df.volume,slow)
    return output('volume_oscillator',100*(a-b)/b.replace(0,np.nan))

def dpo(df,length=20):
    # Causal DPO: historical value at t depends on price at t-shift only.
    shift=length//2+1
    return output('dpo',df.close.shift(shift)-sma(df.close,length))

def bbwidth(df,length=20,mult=2.0):
    avg=sma(df.close,length);std=df.close.rolling(length).std(ddof=0)
    return output('bbwidth',100*(2*mult*std)/avg.replace(0,np.nan))

def prices(df):
    return pd.DataFrame({'median_price':(df.high+df.low)/2,'typical_price':(df.high+df.low+df.close)/3,
                         'weighted_close':(df.high+df.low+2*df.close)/4},index=df.index)

EXTENDED={
 'hull':(hull,{'length':20}), 'dema':(dema,{'length':20}), 'tema':(tema,{'length':20}),
 'zlema':(zlema,{'length':20}), 'trima':(trima,{'length':20}), 'roc':(roc,{'length':12}),
 'momentum':(momentum,{'length':10}), 'willr':(willr,{'length':14}),
 'aroon':(aroon,{'length':14}),'cmf':(cmf,{'length':20}),'ad_line':(ad_line,{}),
 'chaikin_osc':(chaikin_osc,{'fast':3,'slow':10}),'pvt':(pvt,{}),'nvi_pvi':(nvi,{}),
 'natr':(natr,{'length':14}),'stddev':(stddev,{'length':20}),'variance':(variance,{'length':20}),
 'zscore':(zscore,{'length':20}),'linreg':(linreg,{'length':20}),'cmo':(cmo,{'length':14}),
 'tsi':(tsi,{'long':25,'short':13}),'awesome':(awesome,{'fast':5,'slow':34}),
 'force':(force,{'length':13}),'choppiness':(choppiness,{'length':14}),
 'ultimate':(ultimate,{'short':7,'medium':14,'long':28}),'fisher':(fisher,{'length':10}),
 'volume_oscillator':(vpo,{'fast':12,'slow':26}),'dpo':(dpo,{'length':20}),
 'bbwidth':(bbwidth,{'length':20,'mult':2.0}),'price_lines':(prices,{})}
