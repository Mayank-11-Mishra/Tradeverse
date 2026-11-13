import {useEffect,useRef,useState,type FormEvent} from 'react'
import {Activity,ArrowRight,CheckCircle2,KeyRound,LockKeyhole,Server,ShieldCheck,TrendingUp,Wifi,XCircle} from 'lucide-react'
import {api,post,token,ROOT,type Account} from './api'

type BrokerId='groww'|'zerodha'|'upstox'|'fyers'|'flattrade'|'finvasia'
const BROKERS:{id:BrokerId,name:string,initials:string,detail:string,accent:string}[]=[
 {id:'zerodha',name:'Zerodha',initials:'Z',detail:'Kite Connect',accent:'#2387e9'},
 {id:'upstox',name:'Upstox',initials:'U',detail:'Developer API',accent:'#8157ef'},
 {id:'groww',name:'Groww',initials:'G',detail:'Trading API',accent:'#22bfa5'},
 {id:'fyers',name:'FYERS',initials:'F',detail:'API v3',accent:'#e26060'},
 {id:'flattrade',name:'Flattrade',initials:'FT',detail:'Pi API',accent:'#ef9842'},
 {id:'finvasia',name:'Finvasia',initials:'S',detail:'Shoonya API',accent:'#69a2e9'},
]
const FIELD_HELP:Record<BrokerId,string>={
 zerodha:'Use an authorized Kite Connect access token, or a fresh redirect request token and API secret. Access tokens typically expire daily.',
 upstox:'Choose Analytics for market-data-only access (no order placement), or OAuth for trading. A token copied with Bearer is accepted. Standard OAuth tokens expire daily.',
 groww:'Choose exactly one Groww authentication method. Access tokens expire at 6 AM IST; API key + secret requires daily approval; TOTP uses a separately generated TOTP token and secret.',
 fyers:'FYERS API v3 requires the exact registered redirect URL; OAuth token exchange is handled server-side.',
 flattrade:'Use official Flattrade authorization and register the exact callback URL plus your static IP.',
 finvasia:'Shoonya now supports official OAuth login. Register the correct callback and whitelist the broker-required IP; the older automated password/TOTP flow is no longer supported by current documentation.',
}
export default function BrokerGateway({onConnected,compact=false}:{onConnected:(account:string)=>Promise<void>,compact?:boolean}){
 const [broker,setBroker]=useState<BrokerId>('zerodha')
 const [accountId,setAccountId]=useState('')
 const [credentials,setCredentials]=useState<Record<string,string>>({})
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[oauthMode,setOauthMode]=useState(true),[connected,setConnected]=useState<Account[]>([])
 const [showLocal,setShowLocal]=useState(false),[localToken,setLocalToken]=useState(token())
 const [loginErrors,setLoginErrors]=useState<Partial<Record<BrokerId,string>>>({})
 const popupWatch=useRef<number|null>(null)
 const clearPopupWatch=()=>{if(popupWatch.current!==null){window.clearInterval(popupWatch.current);popupWatch.current=null}}
 useEffect(()=>{void api<Account[]>('/accounts').then(setConnected).catch(()=>{})},[])
 useEffect(()=>{const listener=(event:MessageEvent)=>{if(event.origin!==new URL(ROOT||window.location.origin).origin||event.data?.source!=='tradeverse-oauth')return
   if(!event.data.ok){clearPopupWatch();setBusy(false);const message=event.data.error||'Broker authorization did not complete';setError(message);setLoginErrors(v=>({...v,[broker]:message}));return}
   void (async()=>{try{const id=String(event.data.account);const verification=await post<{verified:boolean}>('/accounts/verify',{account:id});if(!verification.verified)throw new Error('Broker session verification failed');setConnected(await api<Account[]>('/accounts'));await onConnected(id);setLoginErrors(v=>({...v,[broker]:''}))}catch(e){setError(String(e));setLoginErrors(v=>({...v,[broker]:String(e)}))}finally{clearPopupWatch();setBusy(false)}})()
  };window.addEventListener('message',listener);return()=>window.removeEventListener('message',listener)},[onConnected,broker])
 const edit=(key:string,value:string)=>setCredentials(old=>({...old,[key]:value}))
 const input=(label:string,key:string,secret=false,required=false,placeholder='')=><label className="gateway-field" key={key}><span>{label}</span><input autoComplete="off" type={secret?'password':'text'} required={required} placeholder={placeholder} value={credentials[key]||''} onChange={e=>edit(key,e.target.value)}/></label>
 const fields=()=>{
  if(broker==='flattrade'||broker==='finvasia'||broker==='fyers')return <>
   <label className="gateway-field"><span>Authentication method</span><select value={oauthMode?'oauth':'token'} onChange={e=>setOauthMode(e.target.value==='oauth')}><option value="oauth">Sign in through broker (OAuth)</option><option value="token">Use existing authorized access token</option></select></label>
   {oauthMode?broker==='flattrade'?<>{input('Flattrade API key','api_key',false,true)}{input('Flattrade API secret','api_secret',true,true)}{input('Broker user ID','user_id',false,true)}</>:broker==='finvasia'?<>{input('Shoonya OAuth client ID','client_id',false,true)}{input('Shoonya secret code','secret_key',true,true)}{input('Broker user ID','user_id',false,true)}</>:<>{input('FYERS App ID','client_id',false,true,'APPID-100')}{input('FYERS App Secret','api_secret',true,true)}</>:
    broker==='fyers'?<>{input('FYERS client ID','client_id',false,true)}{input('Access token','access_token',true,true)}</>:<>{input('Broker user ID','user_id',false,true)}{input('Authenticated session token','access_token',true,true)}</>}
   {oauthMode&&<p className="gateway-callback">Register this exact redirect URL in your broker app dashboard: <code>{ROOT}/api/auth/callback/{broker}</code></p>}
  </>
  if(broker==='upstox')return <><label className="gateway-field"><span>Upstox token type</span><select value={credentials.token_type||'oauth'} onChange={e=>edit('token_type',e.target.value)}><option value="oauth">OAuth trading token</option><option value="analytics">Analytics token (data only)</option></select></label>{input('Access token','access_token',true,true,'Upstox token from Developer Apps')}</>
  if(broker==='groww')return <>
   <label className="gateway-field"><span>Groww authentication method</span><select value={credentials.auth_method||'token'} onChange={e=>setCredentials({auth_method:e.target.value})}>
    <option value="token">Today's access token</option><option value="api_key">API key + secret (daily approval)</option><option value="totp">TOTP token + secret / 6-digit code</option>
   </select></label>
   {(credentials.auth_method||'token')==='token'?input('Current Groww access token','access_token',true,true,'Expires daily at 6:00 AM IST'):
   credentials.auth_method==='api_key'?<>{input('Groww API key','api_key',false,true)}{input('Groww API secret','api_secret',true,true)}</>:
   <>{input('Groww TOTP token (NOT regular API key)','totp_key',false,true)}{input('Base32 TOTP secret (preferred)','totp_secret',true,false)}{input('Or current 6-digit authenticator code','totp_code',true,false,'6 digits; leave blank if using secret')}</>}
   <p className="gateway-callback">Access token and API key are different. Choose the matching credential type created in Groww Cloud. <a href="https://groww.in/trade-api/docs/python-sdk" target="_blank" rel="noreferrer">Groww official documentation</a>.</p>
  </>
  return <>{input('Kite API key','api_key',false,true,'Required API key')}{input('Access token (or request token below)','access_token',true,false,'Current access token')}{input('Redirect request token (alternative)','request_token',false,false)}{input('API secret (required for request-token flow)','api_secret',true,false)}</>
 }
 const connect=async(e:FormEvent)=>{
  e.preventDefault();setError('');setLoginErrors(v=>({...v,[broker]:''}));setBusy(true)
  try{
   if(oauthMode&&['fyers','flattrade','finvasia'].includes(broker)){
    const popup=window.open('about:blank','tradeverse-broker-oauth','popup=yes,width=850,height=780')
    if(!popup)throw new Error('Enable popups for the TradeVerse site to complete broker OAuth login')
    try{
     const result=await post<{authorization_url:string}>('/auth/start',{broker,account_id:accountId.trim(),credentials})
     popup.location.href=result.authorization_url
     clearPopupWatch()
     popupWatch.current=window.setInterval(()=>{if(popup.closed){clearPopupWatch();setBusy(false);setError('Broker authorization popup was closed before login completed.');setLoginErrors(v=>({...v,[broker]:'Authorization popup closed'}))}},600)
     return
    }catch(e){popup.close();throw e}
   }
   const result=await post<{account:string,profile:{account_id:string}}>('/accounts/connect',{broker,account_id:accountId.trim(),credentials:Object.fromEntries(Object.entries(credentials).filter(([,v])=>v.trim()))})
   // Do not unlock navigation on an HTTP success alone: confirm the backend registered a live session.
   const verification=await post<{verified:boolean}>('/accounts/verify',{account:result.account})
   if(!verification.verified)throw new Error('Broker session verification failed.')
   const accounts=await api<Account[]>('/accounts')
   setConnected(accounts)
   if(!accounts.some(a=>a.id===result.account&&a.connected&&a.broker===broker))throw new Error('Broker login was not confirmed by the application. Access remains locked.')
   setCredentials({});await onConnected(result.account)
  }catch(ex){const message=ex instanceof Error?ex.message:String(ex);setError(message);setLoginErrors(v=>({...v,[broker]:message}));setBusy(false)}finally{if(!oauthMode||!['fyers','flattrade','finvasia'].includes(broker))setBusy(false)}
 }
 const saveLocal=()=>{localStorage.setItem('personal_algo_app_token',localToken);setError('');setShowLocal(false)}
 return <div className={'gateway-root'+(compact?' compact':'')}>
  <div className="gateway-top"><div className="gateway-logo"><TrendingUp size={23}/></div><div className="gateway-wordmark">TradeVerse <strong>Pro</strong></div><span className="gateway-top-pill"><span/> PERSONAL TRADING WORKSPACE</span></div>
  <div className="gateway-layout">
   <div className="gateway-story"><span className="gateway-kicker"><Activity size={14}/> YOUR MARKETS. YOUR STRATEGIES.</span><h1>A trading terminal,<br/><em>connected to your broker.</em></h1><p>Connect an authorized brokerage account to unlock live market data, professional charts, options analytics and strategy execution.</p>
    <div className="gateway-flow"><div><span className="gateway-flow-num">01</span><div><b>Choose a broker</b><small>Six supported Indian broker adapters</small></div></div><div><span className="gateway-flow-num">02</span><div><b>Authenticate securely</b><small>Your credentials are checked by the backend</small></div></div><div><span className="gateway-flow-num">03</span><div><b>Enter the trading workspace</b><small>Market data starts loading after login</small></div></div></div>
    <div className="gateway-features"><span><ShieldCheck size={15}/> Broker-first access</span><span><Server size={15}/> Secure broker API</span><span><Wifi size={15}/> Broker-sourced quotes</span></div>
   </div>
   <div className="gateway-card"><div className="gateway-card-heading"><span className="gateway-lock"><LockKeyhole size={20}/></span><div><h2>Connect your broker</h2><p>Sign in to access your trading terminal</p></div></div>
    <form onSubmit={connect} className="gateway-form"><div className="gateway-section-label">SELECT BROKER</div><div className="gateway-brokers">{BROKERS.map(b=><button type="button" key={b.id} className={'gateway-broker '+(broker===b.id?'selected':'')} onClick={()=>{setBroker(b.id);setOauthMode(true);setCredentials({});setError('')}} aria-pressed={broker===b.id}><span className="gateway-broker-icon" style={{background:b.accent+'24',color:b.accent}}>{b.initials}</span><b>{b.name}</b><small>{b.detail}</small>{broker===b.id&&<CheckCircle2 className="gateway-selected-check" size={14}/>}</button>)}</div>
     <div className="gateway-status-row">{BROKERS.map(b=><span key={b.id} className={connected.some(a=>a.broker===b.id&&a.connected)?'broker-connected':loginErrors[b.id]?'broker-error':'broker-disconnected'}>{b.name}: {connected.some(a=>a.broker===b.id&&a.connected)?'Connected':loginErrors[b.id]?'Error':'Disconnected'}</span>)}</div><div className="gateway-section-label">BROKER CREDENTIALS <span>Only official, authorized API sessions</span></div><label className="gateway-field"><span>Account label</span><input required placeholder="e.g. my-trading-account" autoComplete="off" value={accountId} onChange={e=>setAccountId(e.target.value)}/></label><div className="gateway-credential-grid">{fields()}</div>
     <div className="gateway-hint"><KeyRound size={16}/><span>{FIELD_HELP[broker]}</span></div>{error&&<div className="gateway-error" role="alert"><XCircle size={16}/><span>{error}{broker==='groww'&&<small style={{display:'block',marginTop:7}}>Check that your Groww Trading API subscription is active and, for API key + secret, that today's approval is complete. Access tokens expire at 6 AM IST. Do not share credentials.</small>}{broker==='upstox'&&<small style={{display:'block',marginTop:7}}>Generate a fresh live access token at <a href="https://account.upstox.com/developer/apps" target="_blank" rel="noreferrer">Upstox Developer Apps</a>. Analytics tokens are verified using a read-only quote endpoint; OAuth tokens use the Profile API. Never paste your token into chat or a bug report.</small>}</span></div>}
     <button className="gateway-submit" type="submit" disabled={busy||!accountId.trim()}>{busy?'Waiting for broker authorization…':oauthMode&&['fyers','flattrade','finvasia'].includes(broker)?'Sign in with broker':'Connect & open terminal'}<ArrowRight size={17}/></button>
     <p className="gateway-disclaimer">Market data and account access require a successful broker API response. Passwords, OTPs and OAuth approvals must be completed using official broker channels. Tokens are not stored in the local database.</p>
    </form>{!import.meta.env.PROD&&<div className="gateway-card-bottom"><button type="button" onClick={()=>setShowLocal(v=>!v)}><KeyRound size={13}/> Local API token settings</button>{showLocal&&<div className="gateway-local"><input type="password" autoComplete="off" placeholder="APP_LOCAL_TOKEN (if configured)" value={localToken} onChange={e=>setLocalToken(e.target.value)}/><button type="button" onClick={saveLocal}>Save</button></div>}</div>}</div>
  </div><div className="gateway-footer">TRADEVERSE PRO <span>·</span> Private trading workstation <span>·</span> Live order execution remains disabled until explicitly enabled</div>
 </div>
}
