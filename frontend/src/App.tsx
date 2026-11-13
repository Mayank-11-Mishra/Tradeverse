import {useCallback,useEffect,useMemo,useState,type FormEvent,type ReactNode} from 'react'
import {Activity,AlertTriangle,BarChart3,BookOpen,CheckCircle2,History,KeyRound,Link2,Loader2,LogOut,Play,Plus,RefreshCcw,Settings2,ShieldCheck,Square,Wallet,X,Zap} from 'lucide-react'
import BrokerGateway from './BrokerGateway'
import TerminalWorkspace from './TerminalWorkspace'
import {api,post,q,token,type Account,type Candle,type Strategy,type EventRow} from './api'

type Screen='terminal'|'brokers'|'strategies'|'backtest'|'options'|'portfolio'|'activity'|'settings'
type Instrument={exchange:string,symbol:string,segment:string,broker_token?:string,name?:string}
const BROKERS=['groww','zerodha','upstox','fyers','flattrade','finvasia']
const MENU:{id:Screen,label:string,icon:ReactNode}[]=[
 {id:'terminal',label:'Trading terminal',icon:<BarChart3 size={18}/>},
 {id:'brokers',label:'Broker accounts',icon:<Link2 size={18}/>},
 {id:'strategies',label:'My strategies',icon:<Zap size={18}/>},
 {id:'backtest',label:'Backtesting',icon:<History size={18}/>},
 {id:'options',label:'Options & payoff',icon:<Activity size={18}/>},
 {id:'portfolio',label:'Portfolio & orders',icon:<Wallet size={18}/>},
 {id:'activity',label:'Activity log',icon:<BookOpen size={18}/>},
 {id:'settings',label:'Settings & safety',icon:<Settings2 size={18}/>},
]
function Button({children,onClick,kind='secondary',disabled=false,type='button',title}:{children:ReactNode,onClick?:()=>void,kind?:'primary'|'secondary'|'danger'|'quiet',disabled?:boolean,type?:'button'|'submit',title?:string}){
 return <button title={title} type={type} className={'btn '+kind} disabled={disabled} onClick={onClick}>{children}</button>
}
function Section({title,action,children}:{title:string,action?:ReactNode,children:ReactNode}){return <section className="panel"><header className="panel-header"><strong>{title}</strong>{action}</header><div className="panel-body">{children}</div></section>}
function Field({label,children}:{label:string,children:ReactNode}){return <label className="field"><span>{label}</span>{children}</label>}
function Stat({label,value,hint}:{label:string,value:ReactNode,hint?:string}){return <div className="metric"><div className="muted tiny">{label}</div><strong>{value??'—'}</strong>{hint&&<div className="muted tiny">{hint}</div>}</div>}
function fmt(v:unknown,decimal=2){const n=Number(v);return Number.isFinite(n)?n.toLocaleString('en-IN',{maximumFractionDigits:decimal,minimumFractionDigits:decimal}):'—'}
function table(rows:Record<string,any>[],columns?:string[]){if(!rows.length)return <div className="empty">No records returned by the connected broker.</div>;
 const cols=columns||Object.keys(rows[0]).filter(k=>typeof rows[0][k]!=='object').slice(0,12)
 return <div className="table-scroll"><table><thead><tr>{cols.map(k=><th key={k}>{k.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{rows.slice(0,100).map((r,i)=><tr key={i}>{cols.map(k=><td key={k}>{typeof r[k]==='number'?fmt(r[k]):String(r[k]??'—').slice(0,64)}</td>)}</tr>)}</tbody></table></div>}
function ErrorLine({message}:{message:string}){return message?<div className="error-line"><AlertTriangle size={15}/>{message}</div>:null}

export default function App(){
 const [screen,setScreen]=useState<Screen>('terminal')
 const [booting,setBooting]=useState(true)
 const [accounts,setAccounts]=useState<Account[]>([]),[account,setAccount]=useState('')
 const [capabilities,setCapabilities]=useState<Record<string,any>>({})
 const [health,setHealth]=useState<Record<string,any>>({})
 const [notice,setNotice]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const [exchange,setExchange]=useState('NSE'),[symbol,setSymbol]=useState('NIFTY'),[segment,setSegment]=useState('IDX'),[interval,setInterval]=useState('15m')
 const [candles,setCandles]=useState<Candle[]>([])
 const [strategyName,setStrategyName]=useState('EMA crossover'),[fast,setFast]=useState(9),[slow,setSlow]=useState(21),[stratQty,setStratQty]=useState(1),[strategyMode,setStrategyMode]=useState('paper'),[strategies,setStrategies]=useState<Strategy[]>([])
 const [backtestResult,setBacktestResult]=useState<any>(null)
 const [broker,setBroker]=useState('zerodha'),[accountId,setAccountId]=useState(''),[creds,setCreds]=useState<Record<string,string>>({})
 const [portfolio,setPortfolio]=useState<any>({}),[events,setEvents]=useState<EventRow[]>([])
 const [expiry,setExpiry]=useState(''),[underlying,setUnderlying]=useState('NIFTY'),[chain,setChain]=useState<any>(null)
 const [expiries,setExpiries]=useState<string[]>([]),[chainError,setChainError]=useState(''),[chainBusy,setChainBusy]=useState(false)
 const [legs,setLegs]=useState([{kind:'CE',strike:'25000',premium:'100',qty:'1'}]),[payoff,setPayoff]=useState<any>(null)
 const [savedToken,setSavedToken]=useState(token())
 const selected=useMemo(()=>accounts.find(a=>a.id===account),[accounts,account])
 const connected=Boolean(selected?.connected)
 const setErrorSafe=(e:unknown)=>{setError(e instanceof Error?e.message:String(e));setNotice('')}
 const done=(message:string)=>{setNotice(message);setError('')}
 const refresh=useCallback(async()=>{
  try{
   const [a,b,h]=await Promise.all([api<Account[]>('/accounts'),api<Record<string,any>>('/brokers'),api<any>('/health')]);
   const checked=await Promise.all(a.map(async x=>{
    if(!x.connected)return x
    try{const result=await post<{verified:boolean}>('/accounts/verify',{account:x.id});return {...x,connected:result.verified}}
    catch{return {...x,connected:false}}
   }))
   setAccounts(checked);setCapabilities(b);setHealth(h)
   setAccount(old=>checked.some(x=>x.id===old&&x.connected)?old:(checked.find(x=>x.connected)?.id||''))
  }catch(e){setErrorSafe(e)}
 },[])
 useEffect(()=>{void refresh().finally(()=>setBooting(false))},[refresh])
 const loadHistory=useCallback(async(fetchBroker:boolean)=>{
  if(!account||!connected)return
  setBusy(true);setError('')
  try{
   const path='/history?'+q({account,exchange,symbol,segment,interval,refresh:fetchBroker,limit:5000})
   const rows=await api<Candle[]>(path);setCandles(rows)
   done(`${rows.length} candles ${fetchBroker?'requested from broker':'loaded from local cache'}`)
  }catch(e){setErrorSafe(e)}finally{setBusy(false)}
 },[account,connected,exchange,symbol,segment,interval])
 // The workspace owns symbol history and broker streaming. Legacy backtesting calls
 // loadHistory explicitly; a second unconditional fetch here would duplicate API calls.
 useEffect(()=>{setCandles([])},[account,connected,exchange,symbol,segment,interval])
 // Chart and index streams are managed by one account-scoped client in TerminalWorkspace.
 const login=async(e:FormEvent)=>{
  e.preventDefault();setBusy(true)
  try{const body={broker,account_id:accountId.trim(),credentials:Object.fromEntries(Object.entries(creds).filter(([,v])=>v.trim()))}
   const result=await post<any>('/accounts/connect',body);await post('/accounts/verify',{account:result.account});const state=await api<Account[]>('/accounts');if(!state.some(a=>a.id===result.account&&a.connected))throw new Error('Backend did not confirm the authenticated broker session');await refresh();setAccount(result.account);done(`Connected ${broker} account ${accountId}`);setCreds({});setScreen('terminal')
  }catch(e){setErrorSafe(e)}finally{setBusy(false)}
 }
 const logout=async(id:string)=>{
  if(!window.confirm(`Disconnect ${id}?`))return
  try{await api(`/accounts/${encodeURIComponent(id)}`,{method:'DELETE'});await refresh();done('Broker disconnected')}catch(e){setErrorSafe(e)}
 }
 const rules=()=>({entry:{left:{indicator:'ema',params:{length:fast}},operator:'crosses_above',right:{indicator:'ema',params:{length:slow}}},
  exit:{left:{indicator:'ema',params:{length:fast}},operator:'crosses_below',right:{indicator:'ema',params:{length:slow}}},quantity:stratQty,sl_pct:1,tp_pct:2})
 const reloadStrategies=async()=>{try{setStrategies(await api<Strategy[]>('/strategies'))}catch(e){setErrorSafe(e)}}
 const saveStrategy=async()=>{
  if(!account)return setError('Connect a broker account to save a strategy')
  setBusy(true)
  try{const data=await post<Strategy>('/strategies',{name:strategyName,account,exchange,symbol,segment,interval:'1m',mode:strategyMode,definition:rules()});await reloadStrategies();done(`Saved ${data.name} (${data.mode})`)}
  catch(e){setErrorSafe(e)}finally{setBusy(false)}
 }
 const changeStrategy=async(id:string,start:boolean)=>{
  try{await post(`/strategies/${id}/${start?'start':'stop'}`,{});await reloadStrategies();done(`Strategy ${start?'started':'stopped'}`)}catch(e){setErrorSafe(e)}
 }
 const backtest=async()=>{
  if(candles.length<30){setError('Fetch at least 30 historical candles before backtesting');return}
  setBusy(true);setError('')
  try{const result=await post('/backtest',{account,exchange,symbol,segment,interval,definition:rules(),initial_capital:100000,slippage_bps:1,candles});setBacktestResult(result);done('Backtest completed on supplied broker/cache candles')}
  catch(e){setErrorSafe(e)}finally{setBusy(false)}
 }
 const loadPortfolio=async()=>{
  if(!account)return
  setBusy(true)
  const results=await Promise.allSettled(['paper/'+encodeURIComponent(account),'orders/'+encodeURIComponent(account),'tradebook/'+encodeURIComponent(account),'positions/'+encodeURIComponent(account),'holdings/'+encodeURIComponent(account),'funds/'+encodeURIComponent(account)].map(x=>api('/'+x)))
  setPortfolio(Object.fromEntries(results.map((r,i)=>[['paper','orders','tradebook','positions','holdings','funds'][i],r.status==='fulfilled'?r.value:{error:(r.reason as Error).message}])));setBusy(false)
 }
 const loadEvents=async()=>{try{setEvents(await api<EventRow[]>('/events?limit=200'))}catch(e){setErrorSafe(e)}}
 const loadOptionChain=useCallback(async()=>{
  if(!account||!connected||!expiry)return
  setChainBusy(true);setChainError('')
  try{const result=await api<any>('/options/chain?'+q({account,underlying,expiry}));setChain(result)}
  catch(e){setChain(null);const msg=e instanceof Error?e.message:String(e);setChainError(msg);setErrorSafe(e)}
  finally{setChainBusy(false)}
 },[account,connected,underlying,expiry])
 // The broker, not the UI, decides available expiries. Never invent a date.
 useEffect(()=>{
  setExpiries([]);setChain(null);setChainError('');setExpiry('')
  if(!connected||!underlying.trim())return
  let active=true
  const timer=window.setTimeout(()=>{
   void api<{expiries:string[]}>('/options/expiries?'+q({account,underlying})).then(x=>{
    if(!active)return
    setExpiries(x.expiries);setExpiry(x.expiries[0]||'')
    if(!x.expiries.length)setChainError('No option expiries returned by the broker')
   }).catch(e=>{if(active){setChainError(e instanceof Error?e.message:String(e));setExpiry('')}})
  },450)
  return ()=>{active=false;window.clearTimeout(timer)}
 },[connected,account,underlying])
 useEffect(()=>{if(expiry&&connected&&expiries.includes(expiry))void loadOptionChain()},[expiry,connected,expiries,loadOptionChain])
 const calcPayoff=async()=>{try{const r=await post('/options/payoff',{spot:Number(legs[0]?.strike||0),legs:legs.map(l=>({kind:l.kind.replace('short_','').replace('long_',''),strike:Number(l.strike),premium:Number(l.premium),qty:Number(l.qty)*(l.kind.startsWith('short_')?-1:1)}))});setPayoff(r)}catch(e){setErrorSafe(e)}}
 useEffect(()=>{if(connected)void loadPortfolio()},[account,connected])
 const renderBrokers=()=> <div className="two-cols"><Section title="Connect brokerage account"><p className="muted small">Use credentials issued by the broker. Broker credentials are handled server-side. On Windows, optional local session recovery uses encrypted DPAPI storage; do not share the vault file or your Windows account.</p><form onSubmit={e=>void login(e)} className="form-stack">
   <Field label="Broker"><select value={broker} onChange={e=>{setBroker(e.target.value);setCreds({})}}>{BROKERS.map(b=><option value={b} key={b}>{b.toUpperCase()}</option>)}<option value="mock">Mock (testing only)</option></select></Field>
   <Field label="Local account label / broker user ID"><input value={accountId} onChange={e=>setAccountId(e.target.value)} required placeholder="e.g. my-zerodha"/></Field>
   {(broker==='flattrade'||broker==='finvasia')&&<Field label="Broker user ID"><input value={creds.user_id||''} onChange={e=>setCreds(c=>({...c,user_id:e.target.value}))} placeholder="Broker login ID"/></Field>}
   {broker==='groww'&&<Field label="Groww authentication method"><select value={creds.auth_method||'token'} onChange={e=>setCreds({auth_method:e.target.value})}><option value="token">Current access token</option><option value="api_key">API key + secret</option><option value="totp">TOTP token + secret/code</option></select></Field>}
   {(broker==='zerodha'||broker==='fyers'||broker==='upstox'||(broker==='groww'&&creds.auth_method==='api_key'))&&<Field label={broker==='fyers'?'Client ID':broker==='groww'?'API key (optional if access token provided)':'API key / client ID'}><input value={creds[broker==='fyers'?'client_id':'api_key']||''} onChange={e=>setCreds(c=>({...c,[broker==='fyers'?'client_id':'api_key']:e.target.value}))} placeholder="Issued by broker"/></Field>}
   {(broker!=='groww'||(creds.auth_method||'token')==='token')&&<Field label={broker==='finvasia'||broker==='flattrade'?'Session token (jKey / token)':'Access token'}><input type="password" autoComplete="off" value={creds.access_token||''} onChange={e=>setCreds(c=>({...c,access_token:e.target.value}))} placeholder="Current authorized broker session token"/></Field>}
   {(broker==='zerodha'||(broker==='groww'&&creds.auth_method==='api_key'))&&<Field label={broker==='groww'?'Groww API secret':'API secret (optional if bearer token used)'}><input type="password" autoComplete="off" value={creds.api_secret||''} onChange={e=>setCreds(c=>({...c,api_secret:e.target.value}))}/></Field>}
   {broker==='groww'&&creds.auth_method==='totp'&&<><Field label="Groww TOTP token"><input value={creds.totp_key||''} onChange={e=>setCreds(c=>({...c,totp_key:e.target.value}))}/></Field><Field label="TOTP Base32 secret (or enter 6-digit code below)"><input type="password" value={creds.totp_secret||''} onChange={e=>setCreds(c=>({...c,totp_secret:e.target.value}))}/></Field><Field label="Current 6-digit code (optional if secret entered)"><input type="password" value={creds.totp_code||''} onChange={e=>setCreds(c=>({...c,totp_code:e.target.value}))}/></Field></>}
   {broker==='zerodha'&&<Field label="Request token (optional exchange flow)"><input value={creds.request_token||''} onChange={e=>setCreds(c=>({...c,request_token:e.target.value}))}/></Field>}
   <Button type="submit" kind="primary" disabled={busy||!accountId}>{busy?<Loader2 size={15}/>:<Link2 size={15}/>} Connect account</Button><div className="muted tiny">Some brokers require their own OAuth login, TOTP, approval, or paid API entitlement. This form does not bypass those requirements.</div>
  </form></Section><Section title="My connections" action={<Button onClick={()=>void refresh()}><RefreshCcw size={14}/> Refresh</Button>}><div className="account-list">{accounts.length?accounts.map(x=><div className="account-tile" key={x.id}><div><div className="strong">{x.broker.toUpperCase()} <span className={x.connected?'tag':'tag muted-tag'}>{x.connected?'Connected':'Offline'}</span></div><div className="muted small">{x.display_name||x.user_id||x.id}</div><div className="muted tiny">{x.id} · {capabilities[x.broker]?.verification||'needs validation'}</div></div>{x.connected&&<Button kind="quiet" onClick={()=>void logout(x.id)}><LogOut size={16}/></Button>}</div>):<div className="empty">No brokerage accounts configured yet.</div>}</div><div className="subtle-note"><ShieldCheck size={17}/> Broker credentials are never sent to the charting library or exposed through portfolio endpoints.</div></Section><BrokerGateway compact onConnected={async id=>{await refresh();setAccount(id);setScreen('terminal')}}/></div>
 const renderStrategies=()=> <div className="two-cols"><Section title="New visual strategy"><p className="muted small">Built-in crossover strategy. The same indicator definitions are used for backtesting and on closed live one-minute candles.</p><div className="form-stack"><Field label="Strategy name"><input value={strategyName} onChange={e=>setStrategyName(e.target.value)}/></Field><div className="split"><Field label="Fast EMA"><input type="number" min="2" max="100" value={fast} onChange={e=>setFast(Number(e.target.value))}/></Field><Field label="Slow EMA"><input type="number" min="3" max="200" value={slow} onChange={e=>setSlow(Number(e.target.value))}/></Field></div><div className="split"><Field label="Order quantity"><input type="number" min="1" max="10000" value={stratQty} onChange={e=>setStratQty(Number(e.target.value))}/></Field><Field label="Execution"><select value={strategyMode} onChange={e=>setStrategyMode(e.target.value)}><option value="paper">Paper</option><option value="live">Live (locked by default)</option></select></Field></div><div className="rule-summary"><div>Entry: <b>EMA {fast} crosses above EMA {slow}</b></div><div>Exit: <b>EMA {fast} crosses below EMA {slow}</b></div><div>Stop-loss <b>1%</b> • Take-profit <b>2%</b> (backtest assumptions)</div><div>Instrument: <b>{exchange}:{symbol}</b> • 1m bars</div></div><Button onClick={()=>void saveStrategy()} kind="primary" disabled={busy||!connected||fast>=slow}><Plus size={15}/> Save strategy</Button><p className="muted tiny">This release supports a declarative JSON rule engine. Arbitrary Python execution and drag-and-drop visual blocks are not implemented.</p></div></Section><Section title="Saved strategies" action={<Button onClick={()=>void reloadStrategies()}><RefreshCcw size={14}/> Reload</Button>}><div className="account-list">{strategies.length?strategies.map(x=><div className="account-tile" key={x.id}><div><div className="strong">{x.name} <span className={x.active?'tag':'tag muted-tag'}>{x.active?'Running':'Stopped'}</span></div><div className="muted small">{x.account} · {x.exchange}:{x.symbol} · {x.mode.toUpperCase()}</div></div><Button kind={x.active?'danger':'primary'} onClick={()=>void changeStrategy(x.id,!x.active)}>{x.active?<Square size={14}/>:<Play size={14}/>} {x.active?'Stop':'Run'}</Button></div>):<div className="empty">No strategies saved. Configure an EMA crossover and save it.</div>}</div><div className="subtle-note"><AlertTriangle size={17}/> Live strategies require a working broker market feed and risk controls. They stop on backend restart.</div></Section></div>
 const renderBacktest=()=> <div className="backtest-layout"><Section title="Backtest setup"><div className="backtest-config"><div><b>{exchange}:{symbol}</b><div className="muted small">{candles.length} cached candles • {interval} timeframe</div></div><div className="tag">₹1,00,000 starting capital</div><Button disabled={busy} onClick={()=>void loadHistory(true)}><RefreshCcw size={14}/> Fetch chart history</Button><Button kind="primary" disabled={busy||candles.length<30} onClick={()=>void backtest()}><Play size={14}/> Run backtest</Button></div><div className="muted small">Uses loaded historical candles with next-bar execution and illustrative fees. Results are simulations, not guaranteed performance.</div></Section>{backtestResult&&<><div className="metric-grid">{Object.entries(backtestResult.metrics||{}).slice(0,12).map(([k,v])=><Stat key={k} label={k.replaceAll('_',' ')} value={typeof v==='number'?fmt(v):String(v)}/>)}</div><Section title="Simulated trade history">{table(backtestResult.trades||[])}</Section><Section title="Equity snapshots">{table(backtestResult.equity||[],['ts','value'])}</Section></>}</div>
 const renderOptions=()=> <div className="backtest-layout"><Section title="Broker option chain" action={<span className="tag muted-tag">Broker data only</span>}><div className="symbol-row"><Field label="Underlying"><input value={underlying} onChange={e=>setUnderlying(e.target.value.toUpperCase())}/></Field><Field label="Available expiry"><select value={expiry} onChange={e=>setExpiry(e.target.value)}><option value="">{expiries.length?'Select expiry':'No broker expiries yet'}</option>{expiries.map(x=><option key={x}>{x}</option>)}</select></Field><Button kind="primary" disabled={!connected||chainBusy||!expiry} onClick={()=>void loadOptionChain()}>Fetch option chain</Button></div><div className="muted small">Expiries fetched from the broker; complete chain normalization is available for Upstox and FYERS only.</div>{chainError&&<ErrorLine message={chainError}/>} {chain?.rows&&<div className="chain-result">{table(chain.rows.map((r:any)=>({strike:r.strike,call_ltp:r.call?.ltp,call_oi:r.call?.oi,call_iv:r.call?.iv,call_delta:r.call?.delta,put_ltp:r.put?.ltp,put_oi:r.put?.oi,put_iv:r.put?.iv,put_delta:r.put?.delta})))}</div>}</Section>
 <Section title="Options expiry payoff calculator"><div className="muted small">Illustrative payoff at expiry, excluding brokerage, interest, taxes, and margin; no broker orders are placed.</div><div className="leg-list">{legs.map((l,i)=><div className="leg-row" key={i}><select value={l.kind} onChange={e=>setLegs(v=>v.map((j,k)=>k===i?{...j,kind:e.target.value}:j))}>{['CE','PE','short_CE','short_PE'].map(x=><option key={x} value={x}>{x.replace('short_','Short ').replace('CE','Call').replace('PE','Put')}</option>)}</select>{(['strike','premium','qty'] as const).map(k=><input key={k} type="number" title={k} min={k==='qty'?'1':'0'} step="any" value={l[k]} onChange={e=>setLegs(v=>v.map((j,n)=>n===i?{...j,[k]:e.target.value}:j))}/>)}<Button kind="quiet" disabled={legs.length===1} onClick={()=>setLegs(v=>v.filter((_,k)=>k!==i))}><X size={15}/></Button></div>)}</div><div className="toolbar-inline"><Button onClick={()=>setLegs(v=>[...v,{kind:'CE',strike:'25000',premium:'100',qty:'1'}])} disabled={legs.length>=16}><Plus size={15}/> Add leg</Button><Button kind="primary" onClick={()=>void calcPayoff()}>Calculate payoff</Button></div>{payoff&&<><div className="metric-grid">{Object.entries(payoff.summary||{}).map(([k,v])=><Stat label={k.replaceAll('_',' ')} key={k} value={typeof v==='number'?fmt(v):String(v)}/>)}</div><div className="muted small">Payoff samples: {Array.isArray(payoff.curve)?payoff.curve.length:'—'}</div></>}</Section></div>
 const renderPortfolio=()=> <div className="backtest-layout"><div className="toolbar-inline"><Button kind="primary" onClick={()=>void loadPortfolio()} disabled={busy||!connected}><RefreshCcw size={15}/> Refresh selected account</Button><span className="muted small">{account||'Connect a broker to view your account'}</span></div>{['paper','orders','tradebook','positions','holdings','funds'].map(k=><Section key={k} title={k==='paper'?'Paper account':k.charAt(0).toUpperCase()+k.slice(1)}>{portfolio[k]?.error?<ErrorLine message={portfolio[k].error}/>:Array.isArray(portfolio[k])?table(portfolio[k]):portfolio[k]?<pre className="json-panel">{JSON.stringify(portfolio[k],null,2).slice(0,14000)}</pre>:<div className="empty">Refresh to fetch {k}.</div>}</Section>)}</div>
 const renderActivity=()=> <Section title="Local audit events" action={<Button onClick={()=>void loadEvents()}><RefreshCcw size={15}/> Refresh events</Button>}>{events.length?table(events.map(e=>({...e,payload:JSON.stringify(e.payload)}))):<div className="empty">No events loaded. Click Refresh events.</div>}</Section>
 const renderSettings=()=> <div className="two-cols"><Section title="Local application security"><div className="form-stack"><Field label="Optional local API token"><input type="password" value={savedToken} onChange={e=>setSavedToken(e.target.value)} placeholder="Matches APP_LOCAL_TOKEN on backend"/></Field><Button onClick={()=>{localStorage.setItem('personal_algo_app_token',savedToken);void refresh();done('Local API token saved in this browser')}}><KeyRound size={15}/> Save local token</Button><p className="muted tiny">The backend listens on 127.0.0.1. Do not expose port 8000 publicly. Access tokens stay only in backend process memory; app token is stored in this browser.</p></div></Section><Section title="Trading controls"><div className="form-stack"><div className="risk-panel"><ShieldCheck size={20}/><span>Live order execution</span><strong>{health.live_trading_enabled?'ENABLED':'DISABLED'}</strong></div><p className="muted small">To enable live trading, set ALLOW_LIVE_TRADING=yes on the backend, verify relevant API entitlements and compliance, then explicitly confirm the action below.</p><Button kind="danger" onClick={async()=>{if(window.prompt('Type ENABLE LIVE TRADING')!=='ENABLE LIVE TRADING')return;try{await post('/live/enable',{confirm:'ENABLE LIVE TRADING'});await refresh();done('Live mode enabled')}catch(e){setErrorSafe(e)}}}>Enable live trading</Button><Button onClick={async()=>{try{await post('/live/disable',{});await refresh();done('Live trading disabled; kill switch engaged')}catch(e){setErrorSafe(e)}}}><ShieldCheck size={15}/> Disable live + kill switch</Button><Button onClick={async()=>{if(window.prompt('Type RELEASE KILL SWITCH')!=='RELEASE KILL SWITCH')return;try{await post('/live/release-kill-switch',{confirm:'RELEASE KILL SWITCH'});done('Global kill switch released; live remains disabled unless separately enabled')}catch(e){setErrorSafe(e)}}}>Release global kill switch</Button></div></Section></div>
 if(booting)return <div className="tv-boot"><Loader2 size={32} className="spin"/><b>TradeVerse Pro</b><span>Checking for an authenticated broker session…</span></div>
 if(!connected)return <BrokerGateway onConnected={async id=>{await refresh();setAccount(id);setScreen('terminal');done('Broker authenticated. Loading market instruments and history…')}}/>
 const legacyPage=screen==='terminal'?undefined:<div className="tv-page"><div className="tv-page-hero"><div><span className="eyebrow">TRADEVERSE PRO · {selected?.broker.toUpperCase()} {selected?.read_only?'DATA-ONLY':'CONNECTED'}</span><h1>{MENU.find(m=>m.id===screen)?.label}</h1><p>Account: {selected?.display_name||selected?.user_id||account} · Data from your authenticated broker</p></div><button className="btn secondary" onClick={()=>setScreen('terminal')}><BarChart3 size={15}/> Back to workspace</button></div><div className="tv-page-content">{screen==='brokers'?renderBrokers():screen==='strategies'?renderStrategies():screen==='backtest'?renderBacktest():screen==='options'?renderOptions():screen==='portfolio'?renderPortfolio():screen==='activity'?renderActivity():renderSettings()}</div></div>
 return <>
  {error&&<div className="tv-alert error" role="alert"><AlertTriangle size={17}/><span>{error}</span><button onClick={()=>setError('')}><X size={16}/></button></div>}
  {notice&&<div className="tv-alert success"><CheckCircle2 size={17}/><span>{notice}</span><button onClick={()=>setNotice('')}><X size={16}/></button></div>}
  <TerminalWorkspace account={account} accounts={accounts.filter(a=>a.connected)} onAccount={setAccount}
   onActiveChart={x=>{setExchange(x.exchange);setSymbol(x.symbol);setSegment(x.segment);setInterval(x.interval)}}
   onDisconnect={id=>void logout(id)} onPage={setScreen} liveEnabled={!!health.live_trading_enabled&&!selected?.read_only}
   legacyPage={legacyPage}/>
 </>
}
