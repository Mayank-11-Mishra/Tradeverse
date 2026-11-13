import {useEffect,useRef,useState} from 'react'
import {BarChart3,BookOpen,Briefcase,ChartNoAxesCombined,ChevronLeft,ChevronRight,ClipboardList,Cog,Layers3,Link2,Search,ShieldCheck,Star,Sun,Wallet,X,Zap} from 'lucide-react'
import {api,q,type Account} from './api'
import {useTheme} from './ThemeProvider'
import {type WindowType} from './workspaceLayout'
import type {InstrumentId,FeedState} from './marketFeed'
type Instrument=InstrumentId&{name?:string,broker_token?:string}
type Props={account:string,accounts:Account[],open:boolean,onOpen:(value:boolean)=>void,onWindow:(kind:WindowType)=>void,onInstrument:(instrument:InstrumentId,destination:'chart'|'optionchain'|'watchlist')=>void,
 onAccount:(account:string)=>void,onSave:()=>void,onReset:()=>void,onConnect:()=>void,onLogout:(account:string)=>void,status:FeedState,debug:boolean,onDebug:(enabled:boolean)=>void,focused:'chart'|'optionchain'|'watchlist'|'other'}
const ITEMS:{type:WindowType,label:string,icon:any}[]=[
 {type:'chart',label:'Charts',icon:BarChart3},{type:'watchlist',label:'Watchlist',icon:Star},{type:'optionchain',label:'Option Chain',icon:ChartNoAxesCombined},
 {type:'orders',label:'Orderbook',icon:ClipboardList},{type:'tradebook',label:'Tradebook',icon:BookOpen},{type:'positions',label:'Positions',icon:Briefcase},
 {type:'funds',label:'Funds & Margins',icon:Wallet},{type:'strategies',label:'Live Strategies',icon:Zap},{type:'portfolio',label:'Combined Portfolio',icon:Layers3},
 {type:'brokers',label:'Broker Accounts',icon:Link2},{type:'settings',label:'Settings & Safety',icon:Cog}]
export default function NavigationDrawer(p:Props){
 const {theme,setTheme}=useTheme(),[query,setQuery]=useState(''),[results,setResults]=useState<Instrument[]>([]),[recent,setRecent]=useState<Instrument[]>([]),[highlight,setHighlight]=useState(0),[searching,setSearching]=useState(false)
 const input=useRef<HTMLInputElement>(null)
 useEffect(()=>{try{setRecent(JSON.parse(localStorage.getItem('tv_recent_symbols')||'[]'))}catch{}},[])
 useEffect(()=>{const cb=(e:KeyboardEvent)=>{
  const tag=(e.target as HTMLElement)?.tagName
  if(e.key==='Escape'&&p.open){p.onOpen(false);return}
  if((e.key==='/'&&!['INPUT','TEXTAREA'].includes(tag))||(e.ctrlKey&&e.key.toLowerCase()==='k')){e.preventDefault();p.onOpen(true);setTimeout(()=>input.current?.focus(),0)}
 };document.addEventListener('keydown',cb);return ()=>document.removeEventListener('keydown',cb)},[p.open,p.onOpen])
 useEffect(()=>{if(!p.open||!query.trim()){setResults([]);return}
  let active=true;setSearching(true)
  const timer=setTimeout(()=>{void api<Instrument[]>('/instruments?'+q({account:p.account,query:query.trim(),limit:100,fuzzy:true})).then(rows=>{
   if(!active)return
   const text=query.toUpperCase();const score=(x:Instrument)=>{const sym=x.symbol.toUpperCase();return sym===text?0:sym.startsWith(text)?1:sym.includes(text)?2:3}
   setResults([...rows].sort((a,b)=>score(a)-score(b)||a.symbol.length-b.symbol.length).slice(0,40));setHighlight(0)
  }).catch(()=>{if(active)setResults([])}).finally(()=>{if(active)setSearching(false)})},220)
  return ()=>{active=false;clearTimeout(timer)}
 },[query,p.account,p.open])
 const candidates=query.trim()?results:recent
 const pick=(symbol:Instrument,destination:'chart'|'optionchain'|'watchlist')=>{
  const next=[symbol,...recent.filter(x=>x.exchange!==symbol.exchange||x.symbol!==symbol.symbol)].slice(0,10)
  setRecent(next);localStorage.setItem('tv_recent_symbols',JSON.stringify(next));void api('/preferences/recent_searches',{method:'PUT',body:JSON.stringify({items:next})}).catch(()=>{})
  p.onInstrument(symbol,destination);p.onOpen(false);setQuery('')
 }
 return <>
  <button className="drawer-edge-handle" title={p.open?'Close navigation':'Open navigation'} aria-label={p.open?'Close navigation drawer':'Open navigation drawer'} aria-expanded={p.open} onClick={()=>p.onOpen(!p.open)}>{p.open?<ChevronLeft size={18}/>:<ChevronRight size={18}/>}</button>
  {p.open&&<div className="drawer-overlay" onMouseDown={()=>p.onOpen(false)}/>}
  <aside className={'drawer-v2 '+(p.open?'open':'')} role="dialog" aria-modal="true" aria-label="Trading navigation" aria-hidden={!p.open}>
   <header><b>TradeVerse Pro</b><button title="Close navigation" onClick={()=>p.onOpen(false)}><X size={18}/></button></header>
   <div className="drawer-v2-body">
    <div className="drawer-v2-search"><Search size={16}/><input ref={input} aria-label="Search broker instruments" placeholder="Search symbols  / or Ctrl+K" value={query} onChange={e=>setQuery(e.target.value.toUpperCase())}
     onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();setHighlight(x=>Math.min(x+1,candidates.length-1))}else if(e.key==='ArrowUp'){e.preventDefault();setHighlight(x=>Math.max(0,x-1))}else if(e.key==='Enter'&&candidates[highlight])pick(candidates[highlight],p.focused==='other'?'chart':p.focused)}}/></div>
    {Boolean(query||recent.length)&&<div className="drawer-search-results"><div className="drawer-small-title">{query?(searching?'Searching broker instruments…':results.length?'BROKER MATCHES':'No cached matches — try exact broker symbol'):'RECENT SEARCHES'}</div>
     {candidates.slice(0,10).map((x,i)=><div className={'drawer-search-result '+(highlight===i?'focused':'')} key={x.exchange+x.symbol+i}>
      <button className="drawer-symbol" onClick={()=>pick(x,p.focused==='optionchain'?'optionchain':'chart')}><b>{x.symbol}</b><small>{x.exchange} · {x.segment} · {x.name||''}</small></button>
      <div className="drawer-result-actions"><button onClick={()=>pick(x,'chart')} title="Open chart">Chart</button><button onClick={()=>pick(x,'optionchain')} title="Open option chain">Chain</button><button onClick={()=>pick(x,'watchlist')} title="Add watchlist">+</button></div>
     </div>)}
    </div>}
    <div className="drawer-small-title">WORKSPACE WINDOWS</div>
    <nav className="drawer-v2-links">{ITEMS.map(item=><button key={item.type} onClick={()=>{p.onWindow(item.type);p.onOpen(false)}}><item.icon size={17}/><span>{item.label}</span></button>)}</nav>
    <div className="drawer-small-title">CONNECTED BROKERS</div>
    <div className="drawer-accounts">{p.accounts.filter(a=>a.connected).map(a=><div key={a.id} className="drawer-account"><button className={a.id===p.account?'selected':''} onClick={()=>p.onAccount(a.id)}><span className="drawer-live-dot"/><span>{a.broker.toUpperCase()} · {a.user_id||a.display_name||a.id}</span><small>{a.read_only?'DATA':'TRADE'}</small></button><button title={`Disconnect ${a.broker}`} onClick={()=>p.onLogout(a.id)}><X size={13}/></button></div>)}<button className="drawer-connect" onClick={p.onConnect}>+ Connect another broker</button></div>
    <div className="drawer-small-title">APPEARANCE</div><div className="drawer-theme"><Sun size={17}/><label htmlFor="tv-theme-select">Theme</label><select id="tv-theme-select" value={theme} onChange={e=>setTheme(e.target.value as 'light'|'dark'|'system')}><option value="dark">Dark</option><option value="light">Light</option><option value="system">System</option></select></div>
    <div className="drawer-actions"><button onClick={p.onSave}>Save layout</button><button onClick={p.onReset}>Reset to chart only</button></div>
    <div className="drawer-connection"><ShieldCheck size={15}/><span>Feed: {p.status}</span><label><input type="checkbox" checked={p.debug} onChange={e=>p.onDebug(e.target.checked)}/> Debug</label></div>
   </div>
  </aside>
 </>
}
