import {useCallback,useEffect,useMemo,useRef,useState,type ReactNode,type DragEvent} from 'react'
import {AlertTriangle,ArrowLeftRight,ChevronDown,ExternalLink,Eye,EyeOff,Settings2,Maximize2,Minimize2,Plus,RefreshCw,X} from 'lucide-react'
import {api,post,q,type Account,type Candle,type Strategy} from './api'
import {getMarketFeed,asCandle,quoteFromTick,type FeedState,type InstrumentId,type Quote} from './marketFeed'
import IndexTicker from './IndexTicker'
import NavigationDrawer from './NavigationDrawer'
import OptionChainPanel from './OptionChainPanel'
import OrderTicket,{type TicketRequest} from './OrderTicket'
import TradingChart,{type StudyPlot} from './TradingChart'
import StudiesPicker from './StudiesPicker'
import IndicatorSettings,{type IndicatorPreferences} from './IndicatorSettings'
import {useTheme} from './ThemeProvider'
import {DEFAULT_CHART_PARAMETERS,type ChartKind,type ChartParameters} from './chartTransforms'
import {defaultWorkspace,insertPane,removePane,movePane,pane,updatePane,layoutValid,traverse,type WorkspaceNode,type Pane,type LayoutDocument,type DockSide,type WindowType,type GridPreset,paneTitle} from './workspaceLayout'

type Props={account:string,accounts:Account[],onActiveChart:(chart:{exchange:string,symbol:string,segment:string,interval:string})=>void,onAccount:(a:string)=>void,onDisconnect:(a:string)=>void,onPage:(page:'terminal'|'brokers'|'strategies'|'backtest'|'options'|'portfolio'|'activity'|'settings')=>void,liveEnabled:boolean,legacyPage?:ReactNode}
type Instrument=InstrumentId&{name?:string}
const initialWatch:Instrument[]=[{symbol:'NIFTY',exchange:'NSE',segment:'IDX'},{symbol:'BANKNIFTY',exchange:'NSE',segment:'IDX'},{symbol:'RELIANCE',exchange:'NSE',segment:'EQ'}]
const STORAGE='tradeverse_workspace_v2'
const displayNum=(v:any)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:2})
const list=(v:any):any[]=>Array.isArray(v)?v:Array.isArray(v?.data)?v.data:[]
// Preserve all broker-returned candles when extending the chart; do not truncate older history.
const combineHistory=(old:Candle[],newRows:Candle[]):Candle[]=>{
 const index=new Map(old.map(c=>[Date.parse(c.ts),c]));newRows.forEach(c=>index.set(Date.parse(c.ts),c))
 return [...index.values()].sort((a,b)=>Date.parse(a.ts)-Date.parse(b.ts))
}

type HistoryBackfill={status:'queued'|'running'|'complete'|'partial'|'paused'|'not_started',oldest_target:string,scanned_until:string,oldest_cached:string|null,pages_scanned:number,fetched_pages:number,error:string,note:string}
function ChartWindow({account,item,onConfig,onOrder}:{account:string,item:Pane,onConfig:(config:Record<string,any>)=>void,onOrder:(ticket:TicketRequest)=>void}){
 const config=item.config,symbol=String(config.symbol||'NIFTY'),exchange=String(config.exchange||'NSE'),segment=String(config.segment||'IDX'),interval=String(config.interval||'15m')
 const kind=(config.chartKind||'candles') as ChartKind,params=useMemo(()=>({...DEFAULT_CHART_PARAMETERS,...(config.params||{})} as ChartParameters),[config.params])
 const {theme:chartTheme}=useTheme()
 const [bars,setBars]=useState<Candle[]>([]),[partial,setPartial]=useState<Candle|null>(null),[liveMinutes,setLiveMinutes]=useState<Candle[]>([]),[quote,setQuote]=useState<Quote|null>(null),[status,setStatus]=useState<FeedState>('disconnected')
 const [indicatorCatalog,setIndicatorCatalog]=useState<Record<string,{params:Record<string,number>,pane:'overlay'|'oscillator'}>>({}),[editingStudy,setEditingStudy]=useState('')
 const [loading,setLoading]=useState(false),[olderLoading,setOlderLoading]=useState(false),[noOlderCache,setNoOlderCache]=useState(false),[backfill,setBackfill]=useState<HistoryBackfill|null>(null),[feedError,setFeedError]=useState(''),[error,setError]=useState(''),[picker,setPicker]=useState(false),[studies,setStudies]=useState<StudyPlot[]>([]),[available,setAvailable]=useState<Instrument[]>([]),[query,setQuery]=useState('')
 // The chart always starts with recent bars but automatically requests the full
 // broker-available history in the background. No six-month/five-year cutoff.
 useEffect(()=>{let active=true;void api<{available:Array<{id:string,params:Record<string,number>,pane:'overlay'|'oscillator'}>}>('/studies/catalog').then(r=>{if(active)setIndicatorCatalog(Object.fromEntries(r.available.map(x=>[x.id,x])))}).catch(()=>{});return()=>{active=false}},[account])
 const key=useMemo(()=>({exchange,symbol,segment}),[exchange,symbol,segment])
 const request={account,exchange,symbol,segment,interval}
 const reload=useCallback(async()=>{
  setLoading(true);setError('');setNoOlderCache(false)
  try{
   // A broker's optional search endpoint must never block candle loading.
   const matches=await api<Instrument[]>('/instruments?'+q({account,exchange,query:symbol,limit:20})).catch(()=>[] as Instrument[])
   const match=matches.find(x=>x.symbol===symbol&&x.exchange===exchange)
   if(match&&match.segment!==segment){onConfig({...config,segment:match.segment});return}
   // Read latest stored bars, including candles cached on previous sessions.
   const cached=await api<Candle[]>('/history?'+q({account,exchange,symbol,segment,interval,limit:4000}))
   setBars(cached)
   // Fetch a small recent viewport first, then run the long download in the
   // background to avoid concurrent broker API requests at startup.
   const now=new Date(),start=new Date(now.getTime()-(interval==='1d'?365:45)*86400000)
   try{
    const recent=await api<Candle[]>('/history?'+q({account,exchange,symbol,segment,interval,start:start.toISOString(),end:now.toISOString(),refresh:true,limit:4000}))
    setBars(prev=>combineHistory(prev,recent).slice(-4000))
   }finally{
    await post('/history/backfill',{account,exchange,symbol,segment,interval})
   }
  }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setLoading(false)}
 },[account,exchange,symbol,segment,interval])
 useEffect(()=>{setBars([]);setPartial(null);setQuote(null);setFeedError('');setLiveMinutes([]);setBackfill(null);setNoOlderCache(false);void reload()},[reload])
 useEffect(()=>{
  let active=true
  const getStatus=async()=>{
   try{
    const state=await api<HistoryBackfill>('/history/backfill/status?'+q({account,exchange,symbol,segment,interval}))
    if(active)setBackfill(state)
   }catch{/* Chart errors and session re-authentication are handled elsewhere. */}
  }
  void getStatus()
  const timer=window.setInterval(()=>void getStatus(),2500)
  return ()=>{active=false;window.clearInterval(timer)}
 },[account,exchange,symbol,segment,interval])
 useEffect(()=>{
  if(noOlderCache&&bars.length&&backfill?.oldest_cached&&Date.parse(backfill.oldest_cached)<Date.parse(bars[0].ts))setNoOlderCache(false)
 },[backfill?.oldest_cached,noOlderCache,bars.length,bars[0]?.ts])
 const loadOlder=async()=>{
  if(loading||olderLoading||!bars.length)return
  setOlderLoading(true);setError('')
  try{
   const older=await api<Candle[]>('/history?'+q({...request,before:bars[0].ts,limit:4000}))
   if(older.length){setBars(prev=>combineHistory(older,prev));setNoOlderCache(false)}
   else{
    setNoOlderCache(true)
    if(backfill?.status==='partial'||backfill?.status==='paused')setError(backfill.error||backfill.note)
   }
  }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setOlderLoading(false)}
 }
 useEffect(()=>getMarketFeed(account).subscribe([key],e=>{
  if(e.event==='status'&&e.state)setStatus(e.state as FeedState)
  if(e.event==='error')setFeedError(e.message||'Broker stream failed; inspect feed status in drawer')
  if(e.event==='tick')setFeedError('')
  if(e.key&&(e.key.exchange!==exchange||e.key.symbol!==symbol||e.key.segment!==segment))return
  if (e.event === 'tick') {
  setQuote(previous =>
    quoteFromTick(e.data, previous ?? undefined)
  );
}
  if(e.event==='candle'){
   const c=asCandle(e.data);if(!c)return
   if(e.partial){setPartial(c);setLiveMinutes(old=>{const copy=new Map(old.map(m=>[Date.parse(m.ts),m]));copy.set(Date.parse(c.ts),c);return [...copy.values()].sort((a,b)=>Date.parse(a.ts)-Date.parse(b.ts)).slice(-240)})}
   else if(interval==='1m'){setPartial(null);setBars(prev=>{
    const rows=new Map(prev.map(x=>[Date.parse(x.ts),x]));rows.set(Date.parse(c.ts),c)
    return [...rows.values()].sort((a,b)=>Date.parse(a.ts)-Date.parse(b.ts))
   })}
   if(!e.partial)setLiveMinutes(old=>{const copy=new Map(old.map(m=>[Date.parse(m.ts),m]));copy.set(Date.parse(c.ts),c);return [...copy.values()].sort((a,b)=>Date.parse(a.ts)-Date.parse(b.ts)).slice(-240)})
  }
 }),[account,exchange,symbol,segment,interval])
 useEffect(()=>{
  if(!account.startsWith('upstox:'))return
  let active=true
  const read=async()=>{
   if(status==='connected')return
   try{
    const result=await post<{quotes:Array<{key:InstrumentId,ltp:number,previous_close?:number,ts:string,source:string}>}>('/quotes/snapshot',{account,instruments:[key]})
    if(active&&result.quotes.length)setQuote(prev=>quoteFromTick(result.quotes[0],prev||undefined))
   }catch{/* Live feed status and history errors remain visible independently. */}
  }
  void read();const id=window.setInterval(()=>void read(),30000)
  return ()=>{active=false;window.clearInterval(id)}
 },[account,exchange,symbol,segment,status])
 const names=useMemo(()=>Array.isArray(config.studies)?config.studies as string[]:[],[config.studies])
 const studySettings=useMemo(()=>((config.studySettings||{}) as Record<string,IndicatorPreferences>),[config.studySettings])
 useEffect(()=>{
  if(!names.length||!bars.length){setStudies([]);return}
  let active=true
  void Promise.all(names.map(async id=>{
   const prefs=studySettings[id]||{},current=indicatorCatalog[id]
   const response=await api<{timestamps:string[],values:Record<string,(number|null)[]>}>('/indicators?'+q({account,exchange,symbol,segment,interval,name:id,inputs:JSON.stringify({...current?.params,...prefs.inputs})}))
   const oscillators=new Set(['rsi','macd','stoch','stochrsi','atr','adx','cci','mfi','obv','roc','cmf','zscore','cmo','tsi'])
   return {...response,id,pane:current?.pane||(oscillators.has(id)?'oscillator':'overlay'),color:prefs.color,lineWidth:prefs.lineWidth,
    visible:prefs.visible!==false&&(!(prefs.timeframes||[]).length||(prefs.timeframes||[]).includes(interval))} as StudyPlot
  })).then(x=>{if(active){setStudies(x);setError('')}}).catch(e=>{if(active)setError('Indicator calculation: '+String(e))})
  return()=>{active=false}
 },[account,exchange,symbol,segment,interval,names.join('|'),studySettings,indicatorCatalog,bars.length,bars[0]?.ts,bars[bars.length-1]?.ts])
 const updateIndicator=(id:string,prefs:IndicatorPreferences)=>onConfig({...config,studySettings:{...studySettings,[id]:prefs}})
 const find=async()=>{
  if(!query.trim())return
  try{const items=await api<Instrument[]>('/instruments?'+q({account,query,exchange,limit:50}));setAvailable(items)}catch(e){setError((e as Error).message)}
 }
 const openSymbol=(it:Instrument)=>{onConfig({...config,symbol:it.symbol,exchange:it.exchange,segment:it.segment});setPicker(false);setAvailable([]);setQuery('')}
 const levels=useMemo(()=>Array.isArray(config.levels)?config.levels as number[]:[],[config.levels])
 const addLevel=()=>{const entry=window.prompt('Price for horizontal drawing level',String(quote?.ltp||bars.at(-1)?.close||''));if(entry==null)return;const n=Number(entry);if(Number.isFinite(n)&&n>0)onConfig({...config,levels:[...levels,n]})}
 const toggleStudy=(name:string)=>{const selected=Array.isArray(config.studies)?config.studies as string[]:[];onConfig({...config,studies:selected.includes(name)?selected.filter(x=>x!==name):[...selected,name].slice(0,8)})}
 return <div className="ws-chart">
  <div className="ws-chart-toolbar"><button title="Select chart instrument" onClick={()=>setPicker(v=>!v)}><b>{symbol}</b> <ChevronDown size={12}/></button>
   <select aria-label="Chart timeframe" value={interval} onChange={e=>onConfig({...config,interval:e.target.value})}>{['1m','3m','5m','15m','30m','1h','1d'].map(i=><option key={i}>{i}</option>)}</select>
   <span className="ws-history-span" title="Automatically backfills to the earliest history supplied by your connected broker API">History: full broker API</span>
   <select aria-label="Chart type" value={kind} onChange={e=>onConfig({...config,chartKind:e.target.value})}>{[['candles','Candlestick'],['heikin-ashi','Heikin-Ashi'],['renko','Renko'],['point-figure','Point & Figure'],['bars','OHLC Bars'],['line','Line'],['area','Area']].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
   <button onClick={()=>setPicker(true)}>Symbol</button><button onClick={()=>onConfig({...config,showStudies:true})}>Indicators</button><button onClick={addLevel}>Draw level</button><button title="Refresh history" onClick={()=>void reload()} disabled={loading}><RefreshCw size={15}/></button><button title="Show the next older cached candles. Older data is downloaded automatically in the background." onClick={()=>void loadOlder()} disabled={loading||olderLoading||!bars.length}>Load older</button>
   <button className="ws-trade-btn" onClick={()=>onOrder({instrument:key,side:'BUY',lastPrice:quote?.ltp})}>Buy</button><button className="ws-trade-btn sell" onClick={()=>onOrder({instrument:key,side:'SELL',lastPrice:quote?.ltp})}>Sell</button></div>
  {(kind==='renko'||kind==='point-figure')&&<div className="ws-chart-params">{kind==='renko'&&<label>Brick method <select value={params.brickMode} onChange={e=>onConfig({...config,params:{...params,brickMode:e.target.value}})}><option value="fixed">Fixed</option><option value="atr">ATR</option><option value="percent">Percent</option></select></label>}
   <label>{kind==='renko'?'Brick size':'Box size'}<input type="number" min=".01" step="any" value={kind==='renko'?params.brickSize:params.boxSize} onChange={e=>onConfig({...config,params:{...params,[kind==='renko'?'brickSize':'boxSize']:Number(e.target.value)}})}/></label>
   {kind==='point-figure'&&<label>Reversal<input type="number" min="1" max="10" step="1" value={params.reversal} onChange={e=>onConfig({...config,params:{...params,reversal:Number(e.target.value)}})}/></label>}</div>}
  <div className="ws-chart-stats"><b>{exchange}:{symbol}</b><span>{quote?'₹'+displayNum(quote.ltp):bars.length?'₹'+displayNum(bars.at(-1)?.close):'Waiting for broker quotes'}</span><small className={status==='connected'?'up':''}>{status} · {bars.length} bars {loading?'· loading':''}{olderLoading?'· fetching older bars':''}{bars.length?' · chart from '+new Date(bars[0].ts).toLocaleDateString('en-IN'):''}{backfill?.oldest_cached?' · cached from '+new Date(backfill.oldest_cached).toLocaleDateString('en-IN'):''}{quote?.source==='snapshot'?' · REST snapshot (not streaming)':''}</small></div>
  {backfill&&<div className="ws-backfill" aria-live="polite">History backfill: <b>{backfill.status}</b>{backfill.scanned_until?` · scanned to ${new Date(backfill.scanned_until).toLocaleDateString('en-IN')}`:''}{backfill.oldest_target?` · API search target ${new Date(backfill.oldest_target).toLocaleDateString('en-IN')}`:''}{backfill.error?` · ${backfill.error}`:''}{noOlderCache?' · No earlier downloaded page yet; backfill continues automatically.':''}</div>}
  {feedError&&<div className="ws-error">Live feed: {feedError}. REST snapshot may still work.</div>}
  {error&&<div className="ws-error">{error}</div>}
  {!!names.length&&<div className="ws-study-legends">{names.map(id=>{const prefs=studySettings[id]||{},plot=studies.find(x=>x.id===id),last=plot&&Object.entries(plot.values).find(([key])=>!['direction','trend','bullish'].includes(key)),value=last&&[...last[1]].reverse().find(x=>x!=null&&Number.isFinite(x))
   return <div className="ws-study-legend" key={id}><b>{id.toUpperCase()}</b><small>{Object.values({...indicatorCatalog[id]?.params,...prefs.inputs}).join(', ')}</small><span>{typeof value==='number'?value.toFixed(2):'—'}</span><button aria-label={`Toggle ${id} visibility`} title="Show/hide" onClick={()=>updateIndicator(id,{...prefs,visible:prefs.visible===false})}>{prefs.visible===false?<EyeOff size={13}/>:<Eye size={13}/>}</button><button aria-label={`Configure ${id}`} title="Settings" onDoubleClick={()=>setEditingStudy(id)} onClick={()=>setEditingStudy(id)}><Settings2 size={13}/></button><button title="Remove indicator" aria-label={`Remove ${id}`} onClick={()=>toggleStudy(id)}><X size={13}/></button></div>})}</div>}
  <div className="ws-chart-canvas">{bars.length||liveMinutes.length?<TradingChart onNeedOlder={()=>{if(!olderLoading&&!noOlderCache)void loadOlder()}} candles={bars} streamCandle={partial} streamMinutes={liveMinutes} interval={interval} ema9={config.ema9===true} ema21={config.ema21===true} studies={studies} kind={kind} params={params} levels={levels} theme={chartTheme==='system'?(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):chartTheme}/>:<div className="ws-chart-no-data">{loading?'Loading broker historical candles…':'No broker candles returned. Choose a supported instrument or refresh.'}</div>}</div>
  {picker&&<div className="ws-instrument-popover"><input autoFocus placeholder="Search broker instrument" value={query} onChange={e=>setQuery(e.target.value.toUpperCase())} onKeyDown={e=>{if(e.key==='Enter')void find()}}/><button onClick={()=>void find()}>Search</button><button title="Close" onClick={()=>setPicker(false)}><X size={15}/></button><div className="ws-results">{available.map(x=><button key={x.exchange+x.symbol+x.segment} onClick={()=>openSymbol(x)}>{x.exchange}:{x.symbol}<small>{x.segment} · {x.name}</small></button>)}</div></div>}
  {editingStudy&&<IndicatorSettings id={editingStudy} defaults={indicatorCatalog[editingStudy]?.params||{}} value={studySettings[editingStudy]||{}} onApply={prefs=>{updateIndicator(editingStudy,prefs);setEditingStudy('')}} onClose={()=>setEditingStudy('')}/>}
  {config.showStudies&&<StudiesPicker selected={config.studies||[]} onToggle={toggleStudy} onClose={()=>onConfig({...config,showStudies:false})}/>}
 </div>
}

function WatchlistWindow({account,onOpen,onTrade,extra}:{account:string,onOpen:(it:Instrument)=>void,onTrade:(ticket:TicketRequest)=>void,extra:Instrument[]}){
 const symbols=useMemo(()=>[...initialWatch,...extra.filter(x=>!initialWatch.some(y=>y.symbol===x.symbol&&y.exchange===x.exchange))],[extra])
 const [quotes,setQuotes]=useState<Record<string,Quote>>({})
 useEffect(()=>getMarketFeed(account).subscribe(symbols,ev=>{if(ev.event==='tick'&&ev.key){setQuotes(prev=>{const k=`${ev.key!.exchange}:${ev.key!.symbol}`;const next=quoteFromTick(ev.data,prev[k]);return next?{...prev,[k]:next}:prev})}}),[account,symbols.map(x=>x.exchange+x.symbol+x.segment).join('|')])
 useEffect(()=>{
  if(!account.startsWith('upstox:'))return
  let active=true
  const read=async()=>{
   try{
    const result=await post<{quotes:Array<{key:InstrumentId,ltp:number,previous_close?:number,ts:string,source:string}>}>('/quotes/snapshot',{account,instruments:symbols})
    if(!active)return
    setQuotes(previous=>{
     const next={...previous}
     for(const item of result.quotes){const id=`${item.key.exchange}:${item.key.symbol}`,prior=next[id]
      if(prior?.source==='live'&&Date.now()-Date.parse(prior.ts)<45000)continue
      const quote=quoteFromTick(item,prior);if(quote)next[id]=quote
     }return next
    })
   }catch{/* No fabricated watchlist prices if broker denies snapshots. */}
  }
  void read();const timer=window.setInterval(()=>void read(),30000)
  return ()=>{active=false;window.clearInterval(timer)}
 },[account,symbols.map(s=>s.exchange+s.symbol+s.segment).join('|')])
 return <div className="ws-scroll"><table className="ws-table"><thead><tr><th>Symbol</th><th>LTP</th><th>Change</th><th>Trade</th></tr></thead><tbody>{symbols.map(x=>{const quote=quotes[`${x.exchange}:${x.symbol}`];return <tr key={x.exchange+x.symbol}><td><button onClick={()=>onOpen(x)}>{x.symbol}</button></td><td>{displayNum(quote?.ltp)}</td><td className={(quote?.change||0)>=0?'up':'down'}>{quote?.previous&&quote.previous!==quote.ltp?quote?.change?.toFixed(2):'—'}</td><td><button onClick={()=>onTrade({instrument:x,side:'BUY',lastPrice:quote?.ltp})}>Buy</button></td></tr>})}</tbody></table></div>
}

function DataWindow({account,type,accounts}:{account:string,type:WindowType,accounts:Account[]}){
 const [rows,setRows]=useState<any[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true),[actionBusy,setActionBusy]=useState('')
 const read=useCallback(async()=>{try{
  const connected=accounts.filter(a=>a.connected)
  if(type==='portfolio'||type==='orders'||type==='positions'||type==='funds'){
   const records:any[]=await api('/accounts/combined')
   const k=type==='portfolio'?'positions':type
   setRows(records.flatMap(r=>{const x=r[k];return Array.isArray(x)?x.map((item:any)=>({...item,broker:r.broker,broker_account:r.account})):x?[{...x,broker:r.broker,broker_account:r.account}]:r[k+'_error']?[{broker:r.broker,broker_account:r.account,error:r[k+'_error']}]:[]}))
  }else if(type==='tradebook'){
   const all=await Promise.all(connected.map(async a=>{try{return list(await api(`/tradebook/${encodeURIComponent(a.id)}`)).map(x=>({...x,broker:a.broker,broker_account:a.id}))}catch(e){return [{broker:a.broker,error:(e as Error).message}]}}));setRows(all.flat())
  }
  setError('')
 }catch(e){setError((e as Error).message)}finally{setLoading(false)}},[account,type,accounts.map(a=>a.id+a.connected).join('|')])
 useEffect(()=>{void read();const t=setInterval(()=>void read(),5000);return ()=>clearInterval(t)},[read])
 const act=async(row:any,action:'cancel'|'modify')=>{
  const order_id=String(row.order_id||row.orderId||row.id||''),broker_account=String(row.broker_account||'')
  if(!order_id||!broker_account){setError('Broker order ID or account is missing');return}
  if(action==='cancel'&&!window.confirm(`Cancel order ${order_id} on account ${broker_account}?`))return
  let update:Record<string,any>={}
  if(action==='modify'){const next=window.prompt(`New limit price for order ${order_id} (broker may reject incompatible order types)`,String(row.request?.price||row.price||''));if(next==null)return;const value=Number(next);if(!Number.isFinite(value)||value<=0){setError('Enter a positive limit price');return}update={price:value}}
  setActionBusy(order_id);setError('')
  try{await post(action==='cancel'?'/orders/cancel':'/orders/modify',{account:broker_account,order_id,...update});await read()}
  catch(e){setError(e instanceof Error?e.message:String(e))}finally{setActionBusy('')}
 }
 const cols=rows.length?Object.keys(rows[0]).filter(k=>!['request','key','raw'].includes(k)).slice(0,10):[]
 return <div className="ws-scroll"><div className="ws-subheading"><small>Combined across connected accounts · broker labels retained</small><button onClick={()=>void read()}><RefreshCw size={14}/></button></div>{error&&<p className="ws-error">{error}</p>}
  {rows.length?<table className="ws-table"><thead><tr>{cols.map(c=><th key={c}>{c.replaceAll('_',' ')}</th>)}{type==='orders'&&<th>Actions</th>}</tr></thead><tbody>{rows.slice(0,300).map((r,i)=><tr key={i}>{cols.map(c=><td key={c}>{typeof r[c]==='object'?JSON.stringify(r[c]).slice(0,60):String(r[c]??'—')}</td>)}{type==='orders'&&<td className="ws-order-actions">{['OPEN','PENDING','PARTIAL','TRIGGER PENDING','VALIDATION PENDING'].includes(String(r.status||'').toUpperCase())&&<><button disabled={Boolean(actionBusy)} onClick={()=>void act(r,'modify')}>Modify</button><button disabled={Boolean(actionBusy)} onClick={()=>void act(r,'cancel')}>Cancel</button></>}</td>}</tr>)}</tbody></table>:<p className="ws-empty">{loading?'Loading broker account data…':'No records returned by connected brokers.'}</p>}</div>
}
function StrategiesWindow({account,onLegacy}:{account:string,onLegacy:()=>void}){
 const [strategies,setStrategies]=useState<Strategy[]>([]),[error,setError]=useState('')
 const load=useCallback(async()=>{try{setStrategies(await api('/strategies'));setError('')}catch(e){setError((e as Error).message)}},[])
 useEffect(()=>{void load();const t=setInterval(()=>void load(),5000);return ()=>clearInterval(t)},[load])
 const toggle=async(x:Strategy)=>{if(!x.active&&x.mode==='live'&&!window.confirm(`Deploy LIVE strategy ${x.name}? Verify the broker and risk checks before continuing.`))return
  try{await post(`/strategies/${x.id}/${x.active?'stop':'start'}`,{});await load()}catch(e){setError((e as Error).message)}}
 return <div className="ws-scroll"><div className="ws-subheading"><small>Backend-controlled deployments · stop on feed failure</small><button onClick={onLegacy}>New strategy / editor</button></div>{error&&<p className="ws-error">{error}</p>}
 {strategies.filter(x=>x.account===account).map(x=><div className="ws-strategy" key={x.id}><span><b>{x.name}</b><small>{x.exchange}:{x.symbol} · {x.mode} · {x.active?'Running':'Stopped'}</small></span><button onClick={()=>void toggle(x)}>{x.active?'Stop':'Deploy'}</button></div>)}
 {!strategies.some(x=>x.account===account)&&<p className="ws-empty">No saved strategies on this account.</p>}</div>
}
function BrokerWindow({accounts,onAdd,onChange,onLogout}:{accounts:Account[],onAdd:()=>void,onChange:(id:string)=>void,onLogout:(id:string)=>void}){
 return <div className="ws-scroll"><div className="ws-subheading">Authenticated broker sessions <button onClick={onAdd}>+ Connect broker</button></div>{accounts.filter(a=>a.connected).map(a=><div className="ws-strategy" key={a.id}><span><b>{a.broker.toUpperCase()}</b><small>{a.user_id||a.display_name||a.id} · {a.read_only?'Analytics only':'Trading permitted by session'}</small></span><button onClick={()=>onChange(a.id)}>Use</button><button onClick={()=>onLogout(a.id)}>Disconnect</button></div>)}</div>
}

export default function TerminalWorkspace(p:Props){
 const {theme}=useTheme()
 const [layout,setLayout]=useState<LayoutDocument>(defaultWorkspace)
 void theme
 const [ready,setReady]=useState(false),[drawer,setDrawer]=useState(false),[status,setStatus]=useState<FeedState>('disconnected'),[debug,setDebug]=useState(false)
 const [focused,setFocused]=useState(''),[maximized,setMaximized]=useState(''),[ticket,setTicket]=useState<TicketRequest|null>(null),[extraWatch,setExtraWatch]=useState<Instrument[]>([])
 const [saveState,setSaveState]=useState(''),[error,setError]=useState('')
 const root=layout.root
 const tileMode=layout.mode==='tile',tilePreset=layout.tilePreset||'2x2'
 const tiles=useMemo(()=>{const all:Pane[]=[];traverse(layout.root,x=>all.push(x));layout.floating.forEach(f=>all.push(f.pane));const order=layout.tileOrder||[];return all.sort((a,b)=>{const ai=order.indexOf(a.id),bi=order.indexOf(b.id);return (ai<0?999:ai)-(bi<0?999:bi)})},[layout])
 const layouts:GridPreset[]=['1x1','1x2','2x1','2x2','2x3','3x2']
 const tileSize=(x:GridPreset)=>x.split('x').map(Number) as [number,number]
 const autoPreset=(n:number):GridPreset=>n<=1?'1x1':n<=2?'1x2':n<=4?'2x2':'2x3'
 const setMode=(mode:'tab'|'tile')=>{if(mode==='tile'&&tiles.length>6){setError('Tile mode supports a maximum of six windows. Close extra windows first.');return}setLayout(v=>({...v,mode,tilePreset:mode==='tile'?autoPreset(tiles.length):v.tilePreset}))}
 const setTilePreset=(preset:GridPreset)=>{const [rows,cols]=tileSize(preset);if(rows*cols<tiles.length){setError(`Preset ${preset} cannot fit ${tiles.length} windows.`);return}setLayout(v=>({...v,tilePreset:preset}))}
 const reorderTiles=(from:string,to:string)=>setLayout(v=>{const ids=tiles.map(t=>t.id),a=ids.indexOf(from),b=ids.indexOf(to);if(a<0||b<0)return v;ids.splice(a,1);ids.splice(b,0,from);return {...v,tileOrder:ids}})

 useEffect(()=>{let chart:Pane|undefined;traverse(layout.root,pane=>{if(pane.type==='chart'&&(!chart||pane.id===focused))chart=pane});if(chart)p.onActiveChart({exchange:chart.config.exchange||'NSE',symbol:chart.config.symbol||'NIFTY',segment:chart.config.segment||'IDX',interval:chart.config.interval||'15m'})},[focused,layout.root])
 const latest=useRef(layout)
 useEffect(()=>{latest.current=layout},[layout])
 const persist=useCallback(async(value:LayoutDocument)=>{
  localStorage.setItem(STORAGE,JSON.stringify(value))
  try{await api('/preferences/workspace',{method:'PUT',body:JSON.stringify(value)});setSaveState('Saved')}catch{setSaveState('Local copy saved (backend unavailable)')}
 },[])
 useEffect(()=>{let active=true;let fallback:LayoutDocument|undefined
  try{const stored=JSON.parse(localStorage.getItem(STORAGE)||'null');if(layoutValid(stored))fallback=stored}catch{}
  setLayout(fallback||defaultWorkspace())
  void api<{data:any}>('/preferences/workspace').then(res=>{if(active&&layoutValid(res.data))setLayout(res.data)}).catch(()=>{}).finally(()=>{if(active)setReady(true)})
  return ()=>{active=false}
 },[])
 useEffect(()=>{if(!ready)return;setSaveState('Saving…');const t=setTimeout(()=>void persist(layout),800);return ()=>clearTimeout(t)},[layout,ready,persist])
 const findPane=(id:string)=>{let found:Pane|undefined;traverse(latest.current.root,p=>{if(p.id===id)found=p});return found||latest.current.floating.find(x=>x.pane.id===id)?.pane}
 const editPane=(id:string,config:Record<string,any>)=>setLayout(old=>({...old,root:updatePane(old.root,id,p=>({...p,config})),floating:old.floating.map(f=>f.pane.id===id?{...f,pane:{...f.pane,config}}:f)}))
 const firstPane=(type:WindowType)=>{let found:Pane|undefined;traverse(latest.current.root,p=>{if(!found&&p.type===type)found=p});return found}
 const openWindow=(type:WindowType)=>{
  p.onPage('terminal')
  if(latest.current.mode==='tile'){let n=0;traverse(latest.current.root,()=>n++);n+=latest.current.floating.length;if(n>=6){setError('Tile mode allows a maximum of six windows. Close a tile before opening another.');return}}
  const newPane=pane(type)
  setLayout(old=>({...old,root:insertPane(old.root,undefined,newPane),tilePreset:old.mode==='tile'?autoPreset(tiles.length+1):old.tilePreset}))
  setFocused(newPane.id);setMaximized('')
 }
 const pick=(instrument:InstrumentId,destination:'chart'|'optionchain'|'watchlist')=>{
  p.onPage('terminal')
  if(destination==='watchlist'){setExtraWatch(w=>w.some(x=>x.symbol===instrument.symbol&&x.exchange===instrument.exchange)?w:[...w,instrument]);if(!firstPane('watchlist'))openWindow('watchlist');return}
  let existing=findPane(focused)
  if(existing?.type!==destination)existing=firstPane(destination)
  if(!existing){if(latest.current.mode==='tile'&&tiles.length>=6){setError('Tile mode allows only six windows. Close an existing tile to add another.');return}const newPane=pane(destination,destination==='chart'?instrument:{underlying:instrument.symbol});setLayout(old=>({...old,root:insertPane(old.root,undefined,newPane),tilePreset:old.mode==='tile'?autoPreset(tiles.length+1):old.tilePreset}));setFocused(newPane.id)}
  else editPane(existing.id,destination==='chart'?{...existing.config,...instrument}:{...existing.config,underlying:instrument.symbol})
 }
 const reset=()=>{if(window.confirm('Reset saved layout to a single chart?')){setLayout(defaultWorkspace());setFocused('');setMaximized('')}}
 const activateTab=(node:WorkspaceNode,id:string):WorkspaceNode=>node.kind==='tabs'?{...node,active:node.id===id||node.panes.some(x=>x.id===id)?id:node.active}:
  node.kind==='split'?{...node,first:activateTab(node.first,id),second:activateTab(node.second,id)}:node
 const updateSplit=(node:WorkspaceNode,id:string,ratio:number):WorkspaceNode=>node.kind==='split'?{...node,ratio:node.id===id?ratio:node.ratio,first:updateSplit(node.first,id,ratio),second:updateSplit(node.second,id,ratio)}:node
 const close=(id:string)=>{setLayout(old=>{const remaining=removePane(old.root,id);return {...old,root:remaining||defaultWorkspace().root,floating:old.floating.filter(f=>f.pane.id!==id)}});if(maximized===id)setMaximized('')}
 const float=(id:string)=>{const target=findPane(id);if(!target)return
  setLayout(old=>({...old,root:removePane(old.root,id)||defaultWorkspace().root,floating:[...old.floating,{pane:target,x:Math.max(70,window.innerWidth*.2),y:130,w:Math.min(720,window.innerWidth*.7),h:450}]}))}
 const dockFloat=(id:string)=>setLayout(old=>{const f=old.floating.find(x=>x.pane.id===id);return f?{...old,root:insertPane(old.root,undefined,f.pane),floating:old.floating.filter(x=>x.pane.id!==id)}:old})
 const onDrop=(target:string,e:DragEvent)=>{e.preventDefault();const source=e.dataTransfer.getData('text/tradeverse-pane');if(!source||source===target)return
  const rect=(e.currentTarget as HTMLElement).getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width,y=(e.clientY-rect.top)/rect.height
  const side:DockSide=x<.25?'left':x>.75?'right':y<.25?'top':y>.75?'bottom':'center'
  setLayout(old=>({...old,root:movePane(old.root,source,target,side)}));setFocused(source)
 }
 const chrome=(item:Pane,content:ReactNode,showHeader=true)=> <section className="ws-pane" onClick={()=>setFocused(item.id)} onDragOver={e=>e.preventDefault()} onDrop={e=>onDrop(item.id,e)}>
  {showHeader&&<div className="ws-pane-header"><span className="ws-pane-drag" draggable onDragStart={e=>{e.dataTransfer.setData('text/tradeverse-pane',item.id);e.dataTransfer.effectAllowed='move'}} title="Drag to tile or tab stack">⠿</span><b>{paneTitle(item)}</b><span className="ws-pane-subtitle">{item.type==='chart'?`${item.config.exchange||'NSE'} · ${item.config.interval||'15m'}`:''}</span><div className="ws-pane-buttons">{!tileMode&&<button title="Float window" onClick={()=>float(item.id)}><ExternalLink size={14}/></button>}<button title={maximized===item.id?'Restore':'Maximize'} onClick={()=>setMaximized(maximized===item.id?'':item.id)}>{maximized===item.id?<Minimize2 size={14}/>:<Maximize2 size={14}/>}</button><button title="Close window" onClick={()=>close(item.id)}><X size={14}/></button></div></div>}
  <div className="ws-pane-body">{content}</div></section>
 const content=(item:Pane):ReactNode=>{
  if(item.type==='chart')return <ChartWindow key={item.id} account={p.account} item={item} onConfig={c=>editPane(item.id,c)} onOrder={setTicket}/>
  if(item.type==='optionchain')return <OptionChainPanel account={p.account} initialUnderlying={item.config.underlying||'NIFTY'} onOrder={setTicket} onUnderlying={x=>{if(x!==item.config.underlying)editPane(item.id,{...item.config,underlying:x})}}/>
  if(item.type==='watchlist')return <WatchlistWindow account={p.account} extra={extraWatch} onOpen={x=>pick(x,'chart')} onTrade={setTicket}/>
  if(['orders','positions','funds','tradebook','portfolio'].includes(item.type))return <DataWindow account={p.account} type={item.type} accounts={p.accounts}/>
  if(item.type==='strategies')return <StrategiesWindow account={p.account} onLegacy={()=>p.onPage('strategies')}/>
  if(item.type==='brokers')return <BrokerWindow accounts={p.accounts} onAdd={()=>p.onPage('brokers')} onChange={p.onAccount} onLogout={p.onDisconnect}/>
  return <div className="ws-settings-panel"><b>Appearance & safety</b><p>Theme and live feed debugging are available in the left drawer.</p><button onClick={()=>p.onPage('settings')}>Open safety and live-trading controls</button></div>
 }
 const draw=(node:WorkspaceNode):ReactNode=>{
  if(node.kind==='split')return <div className={'ws-split '+node.direction} key={node.id}>
   <div className="ws-split-child" style={{flexBasis:`${node.ratio*100}%`}}>{draw(node.first)}</div>
   <input title="Resize docked windows" aria-label="Resize split" type="range" className="ws-split-divider" min="15" max="85" value={Math.round(node.ratio*100)} onChange={e=>setLayout(old=>({...old,root:updateSplit(old.root!,node.id,Number(e.target.value)/100)}))}/>
   <div className="ws-split-child" style={{flexBasis:`${(1-node.ratio)*100}%`}}>{draw(node.second)}</div></div>
  if(node.kind==='tabs'){
   const active=node.panes.find(x=>x.id===node.active)||node.panes[0]
   return <section className="ws-tabs" key={node.id}><div className="ws-tabs-head">{node.panes.map(tab=><button className={active.id===tab.id?'active':''} key={tab.id} draggable onDragStart={e=>e.dataTransfer.setData('text/tradeverse-pane',tab.id)} onClick={()=>{setLayout(old=>({...old,root:activateTab(old.root!,tab.id)}));setFocused(tab.id)}}>{paneTitle(tab)} <span onClick={e=>{e.stopPropagation();close(tab.id)}}>×</span></button>)}</div>{chrome(active,content(active),false)}</section>
  }
  return chrome(node,content(node))
 }
 const activeWindow=findPane(focused)
 const focusKind=activeWindow?.type==='chart'?'chart':activeWindow?.type==='optionchain'?'optionchain':activeWindow?.type==='watchlist'?'watchlist':'other'
 return <div className="terminal-v2">
  <IndexTicker account={p.account} onPick={x=>pick(x,'chart')} onStatus={setStatus}/>
  <NavigationDrawer account={p.account} accounts={p.accounts} open={drawer} onOpen={setDrawer} onWindow={openWindow} onInstrument={pick}
   onAccount={p.onAccount} onSave={()=>void persist(layout)} onReset={reset} onConnect={()=>p.onPage('brokers')} onLogout={p.onDisconnect} status={status} debug={debug} onDebug={setDebug} focused={focusKind}/>
  {!p.legacyPage&&<div className="ws-layout-toolbar" role="toolbar" aria-label="Workspace layout mode"><span className="ws-mode-toggle"><button className={!tileMode?'active':''} onClick={()=>setMode('tab')} aria-pressed={!tileMode}>Tab</button><button className={tileMode?'active':''} onClick={()=>setMode('tile')} aria-pressed={tileMode}>Tile</button></span>{tileMode&&<><label htmlFor="tile-grid-preset">Grid</label><select id="tile-grid-preset" value={tilePreset} onChange={e=>setTilePreset(e.target.value as GridPreset)}>{layouts.map(preset=>{const [rows,cols]=tileSize(preset);return <option key={preset} disabled={rows*cols<tiles.length}>{preset}</option>})}</select><small>{tiles.length}/6 tiles · Drag headers to reorder</small></>}</div>}
  {debug&&<div className="ws-debug-bar">Account {p.account} · Feed {status} · {saveState} <button onClick={async()=>{try{const x=await api('/feeds/status');setError(JSON.stringify(x).slice(0,400))}catch(e){setError((e as Error).message)}}}>Inspect feed</button></div>}
  {error&&<div className="ws-error" role="alert"><AlertTriangle size={16}/>{error}<button onClick={()=>setError('')}>×</button></div>}
  {p.legacyPage?<main className="ws-legacy">{p.legacyPage}</main>:<main className="ws-root">{!ready?<p className="ws-loading">Restoring workspace…</p>:maximized&&findPane(maximized)?chrome(findPane(maximized)!,content(findPane(maximized)!)):tileMode?<div className="ws-tile-grid" style={{gridTemplateColumns:`repeat(${tileSize(tilePreset)[1]},minmax(0,1fr))`,gridTemplateRows:`repeat(${tileSize(tilePreset)[0]},minmax(0,1fr))`}}>{tiles.slice(0,6).map(item=><div className="ws-tile-cell" key={item.id} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const from=e.dataTransfer.getData('text/tradeverse-tile');if(from)reorderTiles(from,item.id)}}><div className="ws-tile-grip" draggable onDragStart={e=>e.dataTransfer.setData('text/tradeverse-tile',item.id)} title="Drag to rearrange tiles">⠿</div>{chrome(item,content(item))}</div>)}</div>:root?draw(root):<p className="ws-loading">Open a window from the left drawer.</p>}
  {!tileMode&&layout.floating.map(f=><div key={f.pane.id} className="ws-floating" style={{left:f.x,top:f.y,width:f.w,height:f.h}}>
   <div className="ws-floating-handle" onPointerDown={e=>{if((e.target as HTMLElement).closest('button'))return;e.preventDefault();const initialX=e.clientX,initialY=e.clientY,startX=f.x,startY=f.y
    const move=(ev:PointerEvent)=>setLayout(old=>({...old,floating:old.floating.map(item=>item.pane.id===f.pane.id?{...item,x:Math.max(4,startX+ev.clientX-initialX),y:Math.max(40,startY+ev.clientY-initialY)}:item)}))
    const stop=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',stop)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',stop)
   }}><b>{paneTitle(f.pane)}</b><button title="Dock window" onClick={()=>dockFloat(f.pane.id)}><ArrowLeftRight size={14}/></button><button title="Close" onClick={()=>close(f.pane.id)}><X size={14}/></button></div>{content(f.pane)}</div>)}
  </main>}
  <button className="ws-add-pane" title="Open a new window from the navigation drawer" onClick={()=>setDrawer(true)}><Plus size={17}/></button>
  {ticket&&<OrderTicket ticket={ticket} accounts={p.accounts} liveEnabled={p.liveEnabled} onClose={()=>setTicket(null)} onCompleted={()=>{setError('Order request completed; refresh orderbook to reconcile broker result.')}}/>}
 </div>
}
