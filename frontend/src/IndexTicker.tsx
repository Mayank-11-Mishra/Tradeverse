import {useEffect,useMemo,useRef,useState} from 'react'
import {api,q,post} from './api'
import {getMarketFeed,quoteFromTick,type InstrumentId,type Quote,type FeedState} from './marketFeed'
const INDICES=[{name:'NIFTY 50',aliases:['NIFTY 50','NIFTY','Nifty 50'],exchange:'NSE'},
 {name:'BANK NIFTY',aliases:['BANKNIFTY','NIFTY BANK','BANK NIFTY'],exchange:'NSE'},
 {name:'SENSEX',aliases:['SENSEX','SENSEX 30'],exchange:'BSE'},
 {name:'FINNIFTY',aliases:['FINNIFTY','NIFTY FIN SERVICE','Nifty Fin Service'],exchange:'NSE'},
 {name:'MIDCPNIFTY',aliases:['MIDCPNIFTY','NIFTY MID SELECT'],exchange:'NSE'}]
type Instrument={exchange:string,symbol:string,segment:string,name?:string}
export default function IndexTicker({account,onPick,onStatus}:{account:string,onPick:(key:InstrumentId)=>void,onStatus:(state:FeedState)=>void}){
 const [mapping,setMapping]=useState<Record<string,InstrumentId>>({}),[quotes,setQuotes]=useState<Record<string,Quote>>({}),[flash,setFlash]=useState<Record<string,number>>({})
 const lastLiveTick=useRef<Record<string,number>>({})
 useEffect(()=>{let active=true
  void Promise.all(INDICES.map(async index=>{
   try{
    const found=await api<Instrument[]>('/instruments?'+q({account,query:index.aliases[0],exchange:index.exchange,limit:100}))
    const match=found.find(r=>index.aliases.some(s=>r.symbol.toUpperCase()===s.toUpperCase()||r.name?.toUpperCase()===s.toUpperCase()))
    const fallback=account.startsWith('upstox:')?{exchange:index.exchange,symbol:({ 'NIFTY 50':'NIFTY','BANK NIFTY':'BANKNIFTY'} as Record<string,string>)[index.name]||index.name,segment:'IDX'}:undefined
    return [index.name,match?{exchange:match.exchange,symbol:match.symbol,segment:match.segment}:fallback] as const
   }catch{return [index.name,account.startsWith('upstox:')?{exchange:index.exchange,symbol:({'NIFTY 50':'NIFTY','BANK NIFTY':'BANKNIFTY'} as Record<string,string>)[index.name]||index.name,segment:'IDX'}:undefined] as const}
  })).then(entries => {
  if (!active) return;

  const resolved: Record<string, InstrumentId> = {};

  for (const [name, instrument] of entries) {
    if (instrument !== undefined) {
      resolved[name] = instrument;
    }
  }

  setMapping(resolved);
})
  return ()=>{active=false}
 },[account])
 const keys=useMemo(()=>Object.values(mapping),[mapping])
 useEffect(()=>{
  if(!account.startsWith('upstox:')||!keys.length)return
  let active=true
  const load=async()=>{
   try{
    const response=await post<{quotes:Array<{key:InstrumentId,ltp:number,previous_close?:number,ts:string,source:string}>}>('/quotes/snapshot',{account,instruments:keys})
    if(!active)return
    setQuotes(previous=>{
     const next={...previous}
     for(const item of response.quotes){
      const name=Object.keys(mapping).find(s=>{
       const key=mapping[s];return key.exchange===item.key.exchange&&key.symbol===item.key.symbol&&key.segment===item.key.segment
      })
      if(name&&Date.now()-(lastLiveTick.current[name]||0)>45000){const quote=quoteFromTick(item,next[name]);if(quote)next[name]=quote}
     }
     return next
    })
   }catch{/* Missing quote permission is exposed in feed debug, never use artificial prices. */}
  }
  void load();const interval=window.setInterval(()=>void load(),30000)
  return ()=>{active=false;window.clearInterval(interval)}
 },[account,keys.map(k=>k.exchange+k.symbol+k.segment).join('|')])
 useEffect(()=>{
  if(!keys.length)return
  return getMarketFeed(account).subscribe(keys,e=>{
   if(e.event==='status'&&e.state)onStatus(e.state as FeedState)
   if(e.event==='tick'&&e.key){const name=Object.keys(mapping).find(s=>{
     const k=mapping[s];return k.exchange===e.key?.exchange&&k.symbol===e.key?.symbol&&k.segment===e.key?.segment
    });if(name){lastLiveTick.current[name]=Date.now();setQuotes(v=>{const next=quoteFromTick(e.data,v[name]);return next?{...v,[name]:next}:v});setFlash(v=>({...v,[name]:Date.now()}))}}
  })
 },[account,keys.map(k=>k.exchange+k.symbol+k.segment).join('|')])
 return <div className="index-ticker" aria-label="Live index quotes">{INDICES.map(x=>{
  const quote=quotes[x.name],direction=(quote?.change||0)>=0?'positive':'negative',recent=Date.now()-(flash[x.name]||0)<600
  return <button key={x.name} className={`index-quote ${recent?'quote-flash':''}`} onClick={()=>{const key=mapping[x.name];if(key)onPick(key)}} disabled={!mapping[x.name]} title={mapping[x.name]?'Open '+x.name:'Index not found in broker instruments'}>
   <strong>{x.name}</strong><b>{quote?quote.ltp.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}</b><small className={direction}>{quote&&quote.previous!==undefined&&quote.change!==undefined?`${quote.change>=0?'▲ +':'▼ '}${quote.change.toFixed(2)} (${quote.pct!==undefined&&quote.pct>=0?'+':''}${quote.pct?.toFixed(2)}%)`:'—'}</small>
  </button>})}</div>
}
