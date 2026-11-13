import {useEffect,useMemo,useRef,useState} from 'react'
import {RefreshCw,TrendingUp} from 'lucide-react'
import {api,q} from './api'
import type {TicketRequest} from './OrderTicket'
import {getMarketFeed,type InstrumentId} from './marketFeed'
const num=(x:any)=>x===null||x===undefined||!Number.isFinite(Number(x))?'—':Number(x).toLocaleString('en-IN',{maximumFractionDigits:2})
const rowsOf=(chain:any):any[]=>Array.isArray(chain?.rows)?chain.rows:[]
type Props={account:string,initialUnderlying?:string,onOrder:(t:TicketRequest)=>void,onUnderlying?:(s:string)=>void}
export default function OptionChainPanel({account,initialUnderlying='NIFTY',onOrder,onUnderlying}:Props){
 const [underlying,setUnderlying]=useState(initialUnderlying),[expiry,setExpiry]=useState(''),[expiries,setExpiries]=useState<string[]>([]),[chain,setChain]=useState<any>(null)
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[greeks,setGreeks]=useState(false),[range,setRange]=useState(20),[scrollTop,setScrollTop]=useState(0),[updates,setUpdates]=useState<Record<string,number>>({})
 const scrollRef=useRef<HTMLDivElement>(null)
 useEffect(()=>{setUnderlying(initialUnderlying)},[initialUnderlying])
 useEffect(()=>{let current=true;setExpiry('');setExpiries([]);setChain(null)
  const timer=setTimeout(()=>{void api<{expiries:string[]}>('/options/expiries?'+q({account,underlying})).then(x=>{if(current){setExpiries(x.expiries);setExpiry(x.expiries[0]||'')}}).catch(e=>{if(current)setError(e.message)})},300)
  return ()=>{current=false;clearTimeout(timer)}
 },[account,underlying])
 const load=async()=>{if(!expiry)return;setBusy(true);try{const response=await api<any>('/options/chain?'+q({account,underlying,expiry}));setChain(response);setError('');onUnderlying?.(underlying)}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
 useEffect(()=>{if(!expiry)return;void load();const timer=setInterval(()=>void load(),12000);return ()=>clearInterval(timer)},[account,underlying,expiry])
 const all=rowsOf(chain)
 const spot=chain?.spot_price??chain?.underlying_spot_price??null
 const atm=all.length?all.reduce((a,b)=>Math.abs(Number(a.strike)-Number(spot??all[Math.floor(all.length/2)].strike))<Math.abs(Number(b.strike)-Number(spot??all[Math.floor(all.length/2)].strike))?a:b).strike:null
 const atmIndex=all.findIndex(r=>r.strike===atm)
 const display=useMemo(()=>all.filter((_:any,i:number)=>atmIndex<0||Math.abs(i-atmIndex)<=range),[all,atmIndex,range])
 const rowHeight=38,viewport=400,first=Math.max(0,Math.floor(scrollTop/rowHeight)-5),last=Math.min(display.length,first+Math.ceil(viewport/rowHeight)+12)
 const visible=display.slice(first,last)
 const keys=useMemo(()=>all.flatMap((r:any)=>[r.call,r.put]).filter((leg:any)=>leg?.symbol&&leg?.instrument_key).slice(0,70).map((leg:any):InstrumentId=>({exchange:leg.symbol.startsWith('BSE')?'BFO':'NFO',symbol:leg.symbol,segment:'OPT'})),[chain?.expiry,chain?.as_of])
 useEffect(()=>{
  if(!keys.length)return
  return getMarketFeed(account).subscribe(keys,msg=>{if(msg.event==='tick'&&msg.key){setUpdates(prev=>({...prev,[msg.key!.symbol]:Number(msg.data?.ltp)||prev[msg.key!.symbol]}))}})
 },[account,keys.map(x=>x.symbol).join('|')])
 const oiBar=(x:any,max:number)=>{const value=Number(x||0);return <span className="oi-bar"><span style={{width:`${max>0?Math.min(100,value/max*100):0}%`}}/>{num(x)}</span>}
 const maxOI=Math.max(1,...display.flatMap(r=>[Number(r.call?.oi||0),Number(r.put?.oi||0)]))
 const legCell=(leg:any,kind:'CE'|'PE')=>{const ltp=updates[leg?.symbol]??leg?.ltp;const disabled=!leg?.symbol||!Number.isFinite(Number(ltp));const open=(side:'BUY'|'SELL')=>onOrder({instrument:{exchange:leg.exchange||'NFO',symbol:leg.symbol,segment:'OPT'},side,lastPrice:Number(ltp)})
  return <td className={`chain-ltp ${kind==='CE'?'up':'down'}`}><span>{num(ltp)}</span><span className="chain-order-actions"><button disabled={disabled} title={`Buy ${leg?.symbol||kind}`} onClick={()=>open('BUY')}>B</button><button disabled={disabled} title={`Sell ${leg?.symbol||kind}`} onClick={()=>open('SELL')}>S</button></span></td>}
 return <div className="chain-v2"><div className="chain-controls"><label>Underlying<input value={underlying} onChange={e=>setUnderlying(e.target.value.toUpperCase())} aria-label="Option underlying"/></label><label>Expiry<select value={expiry} onChange={e=>setExpiry(e.target.value)} aria-label="Expiry date"><option value="">Select expiry</option>{expiries.map(x=><option key={x}>{x}</option>)}</select></label><label>Strikes either side<select value={range} onChange={e=>setRange(Number(e.target.value))}><option value={10}>10</option><option value={20}>20</option><option value={40}>40</option><option value={100}>All nearby</option></select></label><label className="chain-greeks"><input type="checkbox" checked={greeks} onChange={e=>setGreeks(e.target.checked)}/> Greeks</label><button title="Refresh option chain" disabled={busy||!expiry} onClick={()=>void load()}><RefreshCw size={16}/></button></div>
 <div className="chain-summary"><b>{underlying}</b><span>Spot {num(spot)} · ATM {num(atm)}</span><span>{chain?.pcr!==undefined&&chain?.pcr!==null?'PCR '+num(chain.pcr)+' · ':''}{chain?.max_pain!==undefined?'Max pain '+num(chain.max_pain):''}</span><small>{chain?.note||'Broker snapshot · streaming LTP where tokens are mapped'}</small></div>
 {error&&<div className="ticket-warning">{error}</div>}
 <div className="chain-sides"><strong>CALLS</strong><strong>STRIKE</strong><strong>PUTS</strong></div>
 <div className="chain-table-scroll" ref={scrollRef} onScroll={e=>setScrollTop(e.currentTarget.scrollTop)}>
 <table className="chain-table"><thead><tr><th>OI</th><th>OI Δ</th><th>Vol</th>{greeks&&<><th>Δ</th><th>θ</th><th>Γ</th><th>ν</th></>}<th>IV</th><th>LTP / Order</th><th>STRIKE</th><th>LTP / Order</th><th>IV</th>{greeks&&<><th>Δ</th><th>θ</th><th>Γ</th><th>ν</th></>}<th>Vol</th><th>OI Δ</th><th>OI</th></tr></thead>
 <tbody>{first>0&&<tr style={{height:first*rowHeight}}><td colSpan={greeks?19:11}/></tr>}{visible.map((r:any,i:number)=>{
 const c=r.call||{},p=r.put||{},isAtm=r.strike===atm
 const oiChange=(l:any)=>l.prev_oi===null||l.prev_oi===undefined?null:Number(l.oi)-Number(l.prev_oi)
 const deltaCells=(l:any)=><><td>{num(l.delta)}</td><td>{num(l.theta)}</td><td>{num(l.gamma)}</td><td>{num(l.vega)}</td></>
 return <tr key={`${r.strike}-${i}`} className={`${isAtm?'chain-atm':''} ${r.strike<Number(atm)?'chain-call-itm':'chain-put-itm'}`}>
 <td>{oiBar(c.oi,maxOI)}</td><td>{num(oiChange(c))}</td><td>{num(c.volume)}</td>{greeks&&deltaCells(c)}<td>{num(c.iv)}</td>{legCell(c,'CE')}<th className="chain-strike">{num(r.strike)}{isAtm&&<small>ATM</small>}</th>{legCell(p,'PE')}<td>{num(p.iv)}</td>{greeks&&deltaCells(p)}<td>{num(p.volume)}</td><td>{num(oiChange(p))}</td><td>{oiBar(p.oi,maxOI)}</td></tr>})}{last<display.length&&<tr style={{height:(display.length-last)*rowHeight}}><td colSpan={greeks?19:11}/></tr>}</tbody></table>
 {!display.length&&<div className="chain-placeholder"><TrendingUp size={25}/>{busy?'Fetching broker option chain…':'No broker option-chain rows available. Choose an expiry, or check broker support.'}</div>}
 </div><footer>Option quotes are broker-sourced. Snapshot OI/Greeks refresh periodically; streaming LTP requires mapped option contracts. Order requests open a confirmation ticket.</footer></div>
}
